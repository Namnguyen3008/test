from __future__ import annotations

import csv
import gzip
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from vmec_data.classification import EXPECTED_TABLE_COUNT, TABLE_CLASSIFICATION
from vmec_data.importer import ImportConfig, inspect_xlsx, run_import


def _gzip_csv(header: list[str], rows: list[list[str]]) -> bytes:
    target = io.BytesIO()
    with gzip.GzipFile(fileobj=target, mode="wb") as compressed:
        text = io.TextIOWrapper(compressed, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(text)
        writer.writerow(header)
        writer.writerows(rows)
        text.flush()
    return target.getvalue()


def _xlsx(path: Path) -> None:
    content_types = """<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>"""
    workbook = """<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Inventory" sheetId="1" r:id="rId1"/></sheets></workbook>"""
    relations = """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>"""
    sheet = """<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"/></row><row r="2"><c r="A2"/></row></sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("[Content_Types].xml", content_types)
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", relations)
        book.writestr("xl/worksheets/sheet1.xml", sheet)


def _artifacts(tmp_path: Path, *, malformed: bool = False, production_rows: int = 0) -> dict[str, Path]:
    development = tmp_path / "development.zip"
    research = tmp_path / "research.zip"
    header = ["global_row_id", "content_hash", "question_vi"]
    rows = [["row-1", "hash-1", "Cau hoi"]]
    if malformed:
        rows.append(["row-2", "hash-2"])
    summary = json.dumps({"production_ready_rows": production_rows})
    for archive, prefix in ((development, "csv_development_ready"), (research, "csv_all")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(f"{prefix}/faq.csv.gz", _gzip_csv(header, rows))
            bundle.writestr("VMEC_FULL_DATA_SUMMARY.json", summary)
    ledger = tmp_path / "ledger.csv.gz"
    with gzip.open(ledger, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["global_source_id", "canonical_url"])
        writer.writerow(["src-1", "https://example.test"])
    index = tmp_path / "index.xlsx"
    _xlsx(index)
    return {"development_zip": development, "research_zip": research, "source_ledger": ledger, "master_index": index}


def _config(tmp_path: Path, **overrides) -> ImportConfig:
    values = _artifacts(
        tmp_path, malformed=overrides.pop("malformed", False), production_rows=overrides.pop("production_rows", 0)
    )
    values.update(
        {
            "database": tmp_path / "catalog.sqlite3",
            "report_dir": tmp_path / "reports",
            "release_id": "test-release",
            "table": "faq",
        }
    )
    values.update(overrides)
    return ImportConfig(**values)


def test_all_source_tables_have_an_authoritative_classification():
    assert len(TABLE_CLASSIFICATION) == EXPECTED_TABLE_COUNT == 101
    assert set(TABLE_CLASSIFICATION.values()) == {
        "emergency_safety",
        "routing_clarification",
        "language_nlu",
        "conversation_booking",
        "content_policy_notification",
        "evaluation_security",
        "synthetic_profile_analytics",
        "source_provenance",
    }


def test_stream_import_is_idempotent_and_resume_skips_completed_table(tmp_path: Path):
    config = _config(tmp_path)
    first = run_import(config)
    resumed = run_import(ImportConfig(**{**config.__dict__, "resume": True}))
    assert first.rows_imported == 1
    assert resumed.rows_imported == 0
    with sqlite3.connect(config.database) as connection:
        assert connection.execute("SELECT count(*) FROM dataset_rows").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM global_sources").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM dataset_import_jobs WHERE status='completed'").fetchone()[0] == 2
        )


def test_malformed_rows_are_quarantined_and_reports_are_written(tmp_path: Path):
    result = run_import(_config(tmp_path, malformed=True, release_id="=unsafe/release"))
    assert result.rows_imported == 1
    assert result.rows_quarantined == 1
    assert result.report_json.is_file()
    assert result.report_markdown.is_file()
    assert "import__unsafe_release" in result.report_json.name
    payload = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert payload["tables"]["faq"]["quarantined"] == 1


def test_production_mode_fails_closed_before_database_creation(tmp_path: Path):
    config = _config(tmp_path, mode="production")
    with pytest.raises(RuntimeError, match="approved production corpus is absent"):
        run_import(config)
    assert not config.database.exists()


def test_dry_run_streams_and_reports_without_creating_database(tmp_path: Path):
    config = _config(tmp_path, dry_run=True)
    result = run_import(config)
    assert result.status == "dry_run"
    assert result.rows_imported == 1
    assert result.report_json.is_file()
    assert not config.database.exists()


def test_xlsx_inventory_uses_standard_library_parser(tmp_path: Path):
    artifacts = _artifacts(tmp_path)
    metadata = inspect_xlsx(artifacts["master_index"])
    assert metadata == {"sheet_count": 1, "sheets": [{"name": "Inventory", "rows_including_header": 2}]}
