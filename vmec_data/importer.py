"""Streaming, resumable importer for immutable VMEC source artifacts."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sqlite3
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from .classification import EXPECTED_TABLE_COUNT, classify_table

Mode = Literal["development", "review", "production"]


@dataclass(frozen=True)
class ImportConfig:
    development_zip: Path
    research_zip: Path
    source_ledger: Path
    master_index: Path
    mode: Mode = "development"
    database: Path = Path("data/staging/vmec_catalog.sqlite3")
    report_dir: Path = Path("data/reports")
    release_id: str | None = None
    table: str | None = None
    dry_run: bool = False
    resume: bool = False
    skip_embeddings: bool = False
    rebuild_embeddings: str | None = None
    max_workers: int = 1
    batch_size: int = 500


@dataclass(frozen=True)
class ImportResult:
    release_id: str
    job_id: int | None
    status: str
    rows_seen: int
    rows_imported: int
    rows_quarantined: int
    tables_seen: int
    report_json: Path
    report_markdown: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _table_name(member: str) -> str | None:
    name = Path(member).name
    return name[:-7] if name.endswith(".csv.gz") else None


def _source_zip(config: ImportConfig) -> Path:
    return config.development_zip if config.mode == "development" else config.research_zip


def _read_summary(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        try:
            return json.loads(bundle.read("VMEC_FULL_DATA_SUMMARY.json"))
        except KeyError:
            return {}


def inspect_xlsx(path: Path) -> dict[str, Any]:
    """Read workbook sheet names and approximate row counts with stdlib XML only."""
    namespace = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    rel_ns = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as book:
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = {node.attrib["Id"]: node.attrib["Target"] for node in rels.findall("p:Relationship", rel_ns)}
        sheets: list[dict[str, Any]] = []
        for sheet in workbook.findall("m:sheets/m:sheet", namespace):
            relation = sheet.attrib[f"{{{namespace['r']}}}id"]
            target = targets[relation].lstrip("/")
            member = target if target.startswith("xl/") else "xl/" + target
            rows = 0
            with book.open(member) as xml_stream:
                for _, element in ElementTree.iterparse(xml_stream, events=("end",)):
                    if element.tag.endswith("}row"):
                        rows += 1
                    element.clear()
            sheets.append({"name": sheet.attrib["name"], "rows_including_header": rows})
    return {"sheet_count": len(sheets), "sheets": sheets}


def _connect(path: Path, *, memory_only: bool = False) -> sqlite3.Connection:
    if not memory_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(":memory:" if memory_only else path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dataset_releases (
          release_id TEXT PRIMARY KEY, mode TEXT NOT NULL, source_hash TEXT NOT NULL,
          created_at TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dataset_files (
          release_id TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
          size_bytes INTEGER NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY (release_id, filename)
        );
        CREATE TABLE IF NOT EXISTS dataset_import_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, release_id TEXT NOT NULL, mode TEXT NOT NULL,
          status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
          rows_seen INTEGER NOT NULL DEFAULT 0, rows_imported INTEGER NOT NULL DEFAULT 0,
          rows_quarantined INTEGER NOT NULL DEFAULT 0, error TEXT
        );
        CREATE TABLE IF NOT EXISTS dataset_tables (
          release_id TEXT NOT NULL, table_name TEXT NOT NULL, category TEXT NOT NULL,
          header_json TEXT NOT NULL, source_member TEXT NOT NULL, rows_imported INTEGER NOT NULL DEFAULT 0,
          completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (release_id, table_name)
        );
        CREATE TABLE IF NOT EXISTS dataset_rows (
          release_id TEXT NOT NULL, table_name TEXT NOT NULL, row_key TEXT NOT NULL,
          content_hash TEXT NOT NULL, payload_json TEXT NOT NULL, origin_row_number INTEGER NOT NULL,
          PRIMARY KEY (release_id, table_name, row_key)
        );
        CREATE TABLE IF NOT EXISTS dataset_quarantine (
          id INTEGER PRIMARY KEY AUTOINCREMENT, release_id TEXT NOT NULL, table_name TEXT NOT NULL,
          source_member TEXT NOT NULL, row_number INTEGER NOT NULL, reason TEXT NOT NULL,
          safe_preview TEXT NOT NULL, UNIQUE(release_id, table_name, source_member, row_number, reason)
        );
        CREATE TABLE IF NOT EXISTS global_sources (
          release_id TEXT NOT NULL, global_source_id TEXT NOT NULL, payload_json TEXT NOT NULL,
          PRIMARY KEY (release_id, global_source_id)
        );
        """
    )
    return connection


def _iter_nested_csv(
    bundle: zipfile.ZipFile, member: str
) -> tuple[list[str], Iterator[tuple[int, dict[str, str | None]]]]:
    raw = bundle.open(member)
    compressed = gzip.GzipFile(fileobj=raw)
    text = io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text)
    header = list(reader.fieldnames or [])

    def rows() -> Iterator[tuple[int, dict[str, str | None]]]:
        try:
            yield from enumerate(reader, start=2)
        finally:
            text.close()

    return header, rows()


def _row_key(row: dict[str, Any], row_number: int) -> str:
    for field in ("global_row_id", "row_id", "case_id", "rule_id", "content_hash"):
        if row.get(field):
            return str(row[field])
    return f"row:{row_number}"


def _content_hash(row: dict[str, Any]) -> str:
    supplied = row.get("content_hash")
    if supplied:
        return str(supplied)
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _quarantine(
    connection: sqlite3.Connection, release_id: str, table: str, member: str, number: int, reason: str, row: object
) -> None:
    preview = _safe_cell(json.dumps(row, ensure_ascii=False, default=str))[:1000]
    connection.execute(
        "INSERT OR IGNORE INTO dataset_quarantine "
        "(release_id,table_name,source_member,row_number,reason,safe_preview) VALUES (?,?,?,?,?,?)",
        (release_id, table, member, number, reason, preview),
    )


def _import_ledger(connection: sqlite3.Connection, release_id: str, path: Path, dry_run: bool) -> int:
    count = 0
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_id = row.get("global_source_id")
            if not source_id:
                continue
            count += 1
            if not dry_run:
                connection.execute(
                    "INSERT OR REPLACE INTO global_sources(release_id,global_source_id,payload_json) VALUES(?,?,?)",
                    (release_id, source_id, json.dumps(row, ensure_ascii=False, sort_keys=True)),
                )
            if count % 500 == 0:
                connection.commit()
    return count


def _artifact_metadata(config: ImportConfig) -> list[dict[str, Any]]:
    artifacts = [config.development_zip, config.research_zip, config.source_ledger, config.master_index]
    return [
        {"filename": item.name, "path": str(item), "size_bytes": item.stat().st_size, "sha256": sha256_file(item)}
        for item in artifacts
    ]


def _write_reports(config: ImportConfig, payload: dict[str, Any]) -> tuple[Path, Path]:
    config.report_dir.mkdir(parents=True, exist_ok=True)
    safe_release = "".join(
        character if character.isalnum() or character in "-_." else "_" for character in str(payload["release_id"])
    )
    stem = f"import_{safe_release}"
    json_path = config.report_dir / f"{stem}.json"
    md_path = config.report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# VMEC import report",
        "",
        f"- Release: `{_safe_cell(payload['release_id'])}`",
        f"- Mode: `{_safe_cell(payload['mode'])}`",
        f"- Status: `{_safe_cell(payload['status'])}`",
        f"- Rows seen: {payload['rows_seen']}",
        f"- Rows imported: {payload['rows_imported']}",
        f"- Rows quarantined: {payload['rows_quarantined']}",
        f"- Tables: {payload['tables_seen']}",
        f"- Ledger sources: {payload['ledger_sources']}",
        "",
        "## Artifacts",
        "",
        "| File | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    for artifact in payload["artifacts"]:
        lines.append(f"| {_safe_cell(artifact['filename'])} | {artifact['size_bytes']} | `{artifact['sha256']}` |")
    lines.extend(["", "## Table counts", "", "| Table | Category | Imported | Quarantined |", "|---|---|---:|---:|"])
    for table, values in sorted(payload["tables"].items()):
        lines.append(
            f"| {_safe_cell(table)} | {_safe_cell(values['category'])} | {values['imported']} | {values['quarantined']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_import(config: ImportConfig) -> ImportResult:
    """Import a corpus in bounded transactions and produce deterministic reports."""
    for path in (config.development_zip, config.research_zip, config.source_ledger, config.master_index):
        if not path.is_file():
            raise FileNotFoundError(path)
    artifacts = _artifact_metadata(config)
    selected = _source_zip(config)
    summary = _read_summary(selected)
    if config.mode == "production" and int(summary.get("production_ready_rows", 0)) <= 0:
        raise RuntimeError("production import refused: approved production corpus is absent")
    release_id = (
        config.release_id or f"{config.mode}-{next(a['sha256'] for a in artifacts if a['path'] == str(selected))[:16]}"
    )
    connection = _connect(config.database, memory_only=config.dry_run)
    job_id: int | None = None
    rows_seen = rows_imported = rows_quarantined = 0
    table_report: dict[str, dict[str, Any]] = {}
    status = "dry_run" if config.dry_run else "completed"
    try:
        source_hash = next(a["sha256"] for a in artifacts if a["path"] == str(selected))
        connection.execute(
            "INSERT OR IGNORE INTO dataset_releases VALUES(?,?,?,?,?)",
            (release_id, config.mode, source_hash, _utc_now(), "running"),
        )
        if not config.dry_run:
            cursor = connection.execute(
                "INSERT INTO dataset_import_jobs(release_id,mode,status,started_at) VALUES(?,?,?,?)",
                (release_id, config.mode, "running", _utc_now()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Importer could not allocate a job identifier")
            job_id = int(cursor.lastrowid)
            for artifact in artifacts:
                metadata = inspect_xlsx(config.master_index) if artifact["path"] == str(config.master_index) else {}
                connection.execute(
                    "INSERT OR REPLACE INTO dataset_files VALUES(?,?,?,?,?)",
                    (
                        release_id,
                        artifact["filename"],
                        artifact["sha256"],
                        artifact["size_bytes"],
                        json.dumps(metadata),
                    ),
                )
        ledger_sources = _import_ledger(connection, release_id, config.source_ledger, config.dry_run)
        with zipfile.ZipFile(selected) as bundle:
            members = sorted(i.filename for i in bundle.infolist() if not i.is_dir() and i.filename.endswith(".csv.gz"))
            # The archive embeds a duplicate ledger; domain tables are directory members only.
            members = [m for m in members if "/" in m]
            discovered = {_table_name(m) for m in members}
            unknown = sorted(name for name in discovered if name and classify_table(name) is None)
            if unknown:
                raise RuntimeError(f"unclassified source tables: {', '.join(unknown)}")
            if config.table:
                members = [m for m in members if _table_name(m) == config.table]
                if not members:
                    raise ValueError(f"table not present in selected archive: {config.table}")
            elif len(discovered) != EXPECTED_TABLE_COUNT:
                raise RuntimeError(f"expected 101 classified tables, found {len(discovered)}")
            for member in members:
                table = _table_name(member)
                assert table is not None
                category = classify_table(table)
                assert category is not None
                if config.resume and connection.execute(
                    "SELECT completed FROM dataset_tables WHERE release_id=? AND table_name=?", (release_id, table)
                ).fetchone() == (1,):
                    prior = connection.execute(
                        "SELECT rows_imported FROM dataset_tables WHERE release_id=? AND table_name=?",
                        (release_id, table),
                    ).fetchone()
                    table_report[table] = {
                        "category": category,
                        "imported": int(prior[0]),
                        "quarantined": 0,
                        "resumed": True,
                    }
                    continue
                imported = quarantined = 0
                try:
                    header, stream = _iter_nested_csv(bundle, member)
                    if not header or len(header) != len(set(header)):
                        _quarantine(connection, release_id, table, member, 1, "invalid_or_duplicate_header", header)
                        rows_quarantined += 1
                        table_report[table] = {"category": category, "imported": 0, "quarantined": 1}
                        continue
                    if not config.dry_run:
                        connection.execute(
                            "INSERT OR REPLACE INTO dataset_tables VALUES(?,?,?,?,?,?,0)",
                            (release_id, table, category, json.dumps(header, ensure_ascii=False), member, 0),
                        )
                    for number, row in stream:
                        rows_seen += 1
                        invalid = None in row or any(value is None for key, value in row.items() if key is not None)
                        if invalid:
                            quarantined += 1
                            rows_quarantined += 1
                            if not config.dry_run:
                                _quarantine(
                                    connection, release_id, table, member, number, "malformed_column_count", row
                                )
                            continue
                        imported += 1
                        rows_imported += 1
                        if not config.dry_run:
                            connection.execute(
                                "INSERT OR IGNORE INTO dataset_rows VALUES(?,?,?,?,?,?)",
                                (
                                    release_id,
                                    table,
                                    _row_key(row, number),
                                    _content_hash(row),
                                    json.dumps(row, ensure_ascii=False, sort_keys=True),
                                    number,
                                ),
                            )
                        if rows_seen % config.batch_size == 0:
                            connection.commit()
                    if not config.dry_run:
                        connection.execute(
                            "UPDATE dataset_tables SET rows_imported=?,completed=1 WHERE release_id=? AND table_name=?",
                            (imported, release_id, table),
                        )
                    table_report[table] = {"category": category, "imported": imported, "quarantined": quarantined}
                    connection.commit()
                except (csv.Error, UnicodeError, EOFError, OSError) as error:
                    rows_quarantined += 1
                    if not config.dry_run:
                        _quarantine(
                            connection, release_id, table, member, 0, f"stream_error:{type(error).__name__}", str(error)
                        )
                    table_report[table] = {"category": category, "imported": imported, "quarantined": quarantined + 1}
        if not config.dry_run:
            connection.execute("UPDATE dataset_releases SET status='completed' WHERE release_id=?", (release_id,))
            connection.execute(
                "UPDATE dataset_import_jobs SET status='completed',completed_at=?,rows_seen=?,rows_imported=?,rows_quarantined=? WHERE id=?",
                (_utc_now(), rows_seen, rows_imported, rows_quarantined, job_id),
            )
            connection.commit()
        payload = {
            "release_id": release_id,
            "mode": config.mode,
            "status": status,
            "generated_at": _utc_now(),
            "rows_seen": rows_seen,
            "rows_imported": rows_imported,
            "rows_quarantined": rows_quarantined,
            "tables_seen": len(table_report),
            "ledger_sources": ledger_sources,
            "artifacts": artifacts,
            "tables": table_report,
            "xlsx_inventory": inspect_xlsx(config.master_index),
            "summary": summary,
            "embedding_request": {
                "skip": config.skip_embeddings,
                "rebuild": config.rebuild_embeddings,
                "max_workers": config.max_workers,
            },
        }
        report_json, report_markdown = _write_reports(config, payload)
        return ImportResult(
            release_id,
            job_id,
            status,
            rows_seen,
            rows_imported,
            rows_quarantined,
            len(table_report),
            report_json,
            report_markdown,
        )
    except Exception as error:
        if job_id is not None:
            connection.execute(
                "UPDATE dataset_import_jobs SET status='failed',completed_at=?,error=? WHERE id=?",
                (_utc_now(), type(error).__name__, job_id),
            )
            connection.commit()
        raise
    finally:
        connection.close()
