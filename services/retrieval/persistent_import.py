"""Read-only catalog projection and idempotent PostgreSQL retrieval import."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .chunking import CanonicalChunk, canonical_chunks
from .registry import (
    BackfillPlan,
    CitationRegistry,
    DataMode,
    candidate_from_dataset_row,
    governance_classification,
    plan_embedding_backfill,
    retrieval_eligibility,
)

_SAFE_METADATA_FIELDS = (
    "primary_specialty_code",
    "specialty_code",
    "route_type",
    "age_group",
    "service_code",
)


def _affected(result: Any) -> int:
    return int(getattr(result, "rowcount", -1))


@dataclass(frozen=True, slots=True)
class PersistentSource:
    source_id: str
    canonical_url: str
    title: str


@dataclass(frozen=True, slots=True)
class PersistentRecordProjection:
    id: str
    release_id: str
    origin_table: str
    origin_row_id: str
    mode: DataMode
    canonical_status: str
    review_status: str
    conflict_status: str
    safety_critical: bool
    gold_candidate: bool
    gold_reason: str
    normalized_text: str
    content_hash: str
    metadata: Mapping[str, str]
    sources: tuple[PersistentSource, ...]
    chunks: tuple[CanonicalChunk, ...]


@dataclass(frozen=True, slots=True)
class PersistentImportResult:
    release_id: str
    job_id: str
    logical_release_id: str
    eligible_records: int
    processed_records: int
    processed_chunks: int
    registry_digest: str


class CatalogProjection:
    """Projects only citation-gated retrieval fields from an immutable SQLite catalog."""

    def __init__(self, catalog: Path, logical_release_id: str, mode: DataMode) -> None:
        self.catalog = catalog.resolve()
        self.logical_release_id = logical_release_id
        self.mode = mode
        self.release_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-dataset-release:{logical_release_id}:{mode}"))

    def _connect(self) -> sqlite3.Connection:
        if not self.catalog.is_file():
            raise FileNotFoundError("Catalog database is unavailable")
        return sqlite3.connect(f"file:{self.catalog.as_posix()}?mode=ro", uri=True)

    def _header(self) -> tuple[str, CitationRegistry]:
        connection = self._connect()
        try:
            release = connection.execute(
                "SELECT mode,status,source_hash FROM dataset_releases WHERE release_id=?",
                (self.logical_release_id,),
            ).fetchone()
            if release is None or release[0] != self.mode or release[1] != "completed":
                raise RuntimeError("Requested completed catalog release/mode is unavailable")
            ledger = [
                json.loads(raw)
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM global_sources WHERE release_id=?",
                    (self.logical_release_id,),
                )
            ]
            return str(release[2]), CitationRegistry.from_global_ledger(ledger)
        finally:
            connection.close()

    def _rows(self) -> Iterator[tuple[str, str, str, str]]:
        connection = self._connect()
        try:
            yield from connection.execute(
                "SELECT table_name,row_key,content_hash,payload_json FROM dataset_rows "
                "WHERE release_id=? ORDER BY table_name,row_key",
                (self.logical_release_id,),
            )
        finally:
            connection.close()

    def plan(self) -> BackfillPlan:
        _, citations = self._header()
        candidates = []
        for table, row_id, content_hash, raw in self._rows():
            candidate = candidate_from_dataset_row(table, row_id, content_hash, json.loads(raw))
            if candidate.text:
                candidates.append(candidate)
        return plan_embedding_backfill(candidates, mode=self.mode, citations=citations)

    def source_hash(self) -> str:
        value, _ = self._header()
        return value

    def ledger_sources(self) -> tuple[PersistentSource, ...]:
        _, citations = self._header()
        return tuple(PersistentSource(item.source_id, item.canonical_url, item.title) for item in citations.entries())

    def records(self) -> Iterator[PersistentRecordProjection]:
        _, citations = self._header()
        for table, row_id, content_hash, raw in self._rows():
            payload: dict[str, Any] = json.loads(raw)
            candidate = candidate_from_dataset_row(table, row_id, content_hash, payload)
            if not retrieval_eligibility(candidate, mode=self.mode, citations=citations).eligible:
                continue
            record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-record:{self.release_id}:{table}:{row_id}"))
            resolved_sources = citations.resolve(candidate.source_ids)
            chunks = tuple(
                CanonicalChunk(
                    chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-chunk:{chunk.chunk_id}")),
                    record_id=record_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                )
                for chunk in canonical_chunks(record_id, candidate.text)
            )
            metadata = {
                field: str(payload[field]).strip()
                for field in _SAFE_METADATA_FIELDS
                if payload.get(field) is not None and str(payload[field]).strip()
            }
            classification = governance_classification(table, payload)
            yield PersistentRecordProjection(
                id=record_id,
                release_id=self.release_id,
                origin_table=table,
                origin_row_id=row_id,
                mode=self.mode,
                canonical_status=candidate.canonical_status,
                review_status=candidate.review_status,
                conflict_status=candidate.conflict_status,
                safety_critical=classification.safety_critical,
                gold_candidate=classification.gold_candidate,
                gold_reason=classification.gold_reason,
                normalized_text=candidate.text,
                content_hash=candidate.content_hash,
                metadata=metadata,
                sources=tuple(
                    PersistentSource(value.source_id, value.canonical_url, value.title) for value in resolved_sources
                ),
                chunks=chunks,
            )


class PersistentCatalogImporter:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    @staticmethod
    def job_id(release_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-dataset-import:{release_id}"))

    def _prepare(self, projection: CatalogProjection, plan: BackfillPlan) -> str:
        if projection.mode == "production" and plan.eligible_count == 0:
            raise RuntimeError("Production import refused: approved eligible row count is zero")
        job_id = self.job_id(projection.release_id)
        checkpoint = json.dumps(
            {"logical_release_id": projection.logical_release_id, "processed_records": 0},
            sort_keys=True,
            separators=(",", ":"),
        )
        source_hashes = json.dumps(
            {"catalog_source_hash": projection.source_hash()}, sort_keys=True, separators=(",", ":")
        )
        with self._factory() as session, session.begin():
            release_result = session.execute(
                text(
                    "INSERT INTO dataset_releases("
                    "id,logical_release_id,mode,source_hashes,status,registry_digest,imported_records,updated_at) "
                    "VALUES(:id,:logical_release_id,:mode,cast(:source_hashes AS jsonb),'importing',"
                    ":registry_digest,0,now()) ON CONFLICT(id) DO UPDATE SET status='importing',updated_at=now() "
                    "WHERE dataset_releases.logical_release_id=excluded.logical_release_id "
                    "AND dataset_releases.mode=excluded.mode AND dataset_releases.source_hashes=excluded.source_hashes"
                ),
                {
                    "id": projection.release_id,
                    "logical_release_id": projection.logical_release_id,
                    "mode": projection.mode,
                    "source_hashes": source_hashes,
                    "registry_digest": plan.registry_digest,
                },
            )
            if _affected(release_result) == 0:
                raise RuntimeError("Persistent release identity conflicts with a prior import")
            for source in projection.ledger_sources():
                source_result = session.execute(
                    text(
                        "INSERT INTO global_sources(id,canonical_url,title,metadata) "
                        "VALUES(:id,:url,:title,'{}'::jsonb) ON CONFLICT(id) DO UPDATE SET title=excluded.title "
                        "WHERE global_sources.canonical_url=excluded.canonical_url"
                    ),
                    {"id": source.source_id, "url": source.canonical_url, "title": source.title},
                )
                if _affected(source_result) == 0:
                    raise RuntimeError("Canonical ledger source conflicts with a different URL")
                session.execute(
                    text(
                        "INSERT INTO dataset_release_sources(release_id,source_id) VALUES(:release_id,:source_id) "
                        "ON CONFLICT(release_id,source_id) DO NOTHING"
                    ),
                    {"release_id": projection.release_id, "source_id": source.source_id},
                )
            session.execute(
                text(
                    "INSERT INTO dataset_import_jobs(id,release_id,status,checkpoint,started_at,updated_at) "
                    "VALUES(:id,:release_id,'running',cast(:checkpoint AS jsonb),now(),now()) "
                    "ON CONFLICT(id) DO UPDATE SET status='running',error_code=NULL,updated_at=now()"
                ),
                {"id": job_id, "release_id": projection.release_id, "checkpoint": checkpoint},
            )
        return job_id

    @staticmethod
    def _upsert_record(session: Session, record: PersistentRecordProjection) -> tuple[int, int]:
        for source in record.sources:
            result = session.execute(
                text(
                    "INSERT INTO global_sources(id,canonical_url,title,metadata) "
                    "VALUES(:id,:url,:title,'{}'::jsonb) ON CONFLICT(id) DO UPDATE SET title=excluded.title "
                    "WHERE global_sources.canonical_url=excluded.canonical_url"
                ),
                {"id": source.source_id, "url": source.canonical_url, "title": source.title},
            )
            if _affected(result) == 0:
                raise RuntimeError("Canonical source identifier conflicts with a different URL")
        inserted = session.execute(
            text(
                "INSERT INTO knowledge_records("
                "id,release_id,origin_table,origin_row_id,mode,canonical_status,review_status,conflict_status,"
                "safety_critical,gold_candidate,gold_reason,"
                "normalized_text,content_hash,metadata) VALUES("
                ":id,:release_id,:origin_table,:origin_row_id,:mode,:canonical_status,:review_status,"
                ":conflict_status,:safety_critical,:gold_candidate,:gold_reason,:normalized_text,:content_hash,"
                "cast(:metadata AS jsonb)) "
                "ON CONFLICT(id) DO UPDATE SET normalized_text=excluded.normalized_text "
                "WHERE knowledge_records.content_hash=excluded.content_hash"
            ),
            {
                "id": record.id,
                "release_id": record.release_id,
                "origin_table": record.origin_table,
                "origin_row_id": record.origin_row_id,
                "mode": record.mode,
                "canonical_status": record.canonical_status,
                "review_status": record.review_status,
                "conflict_status": record.conflict_status,
                "safety_critical": record.safety_critical,
                "gold_candidate": record.gold_candidate,
                "gold_reason": record.gold_reason,
                "normalized_text": record.normalized_text,
                "content_hash": record.content_hash,
                "metadata": json.dumps(record.metadata, sort_keys=True, separators=(",", ":")),
            },
        )
        if _affected(inserted) == 0:
            raise RuntimeError("Catalog origin conflicts with previously imported content")
        for source in record.sources:
            session.execute(
                text(
                    "INSERT INTO knowledge_record_sources(record_id,source_id,evidence_locator) "
                    "VALUES(:record_id,:source_id,'') ON CONFLICT(record_id,source_id) DO NOTHING"
                ),
                {"record_id": record.id, "source_id": source.source_id},
            )
        for chunk in record.chunks:
            result = session.execute(
                text(
                    "INSERT INTO knowledge_chunks(id,record_id,ordinal,normalized_text,content_hash,token_count) "
                    "VALUES(:id,:record_id,:ordinal,:normalized_text,:content_hash,:token_count) "
                    "ON CONFLICT(id) DO UPDATE SET normalized_text=excluded.normalized_text "
                    "WHERE knowledge_chunks.content_hash=excluded.content_hash"
                ),
                {
                    "id": chunk.chunk_id,
                    "record_id": record.id,
                    "ordinal": chunk.ordinal,
                    "normalized_text": chunk.text,
                    "content_hash": chunk.content_hash,
                    "token_count": max(1, len(chunk.text.split())),
                },
            )
            if _affected(result) == 0:
                raise RuntimeError("Canonical chunk conflicts with previously imported content")
        return 1, len(record.chunks)

    def _mark_failed(self, *, release_id: str, job_id: str, exc: Exception) -> None:
        with self._factory() as session, session.begin():
            session.execute(
                text("UPDATE dataset_releases SET status='failed',updated_at=now() WHERE id=:release_id"),
                {"release_id": release_id},
            )
            session.execute(
                text(
                    "UPDATE dataset_import_jobs SET status='failed',error_code=:error_code,updated_at=now() "
                    "WHERE id=:job_id"
                ),
                {"job_id": job_id, "error_code": type(exc).__name__[:100]},
            )

    def run(self, projection: CatalogProjection, *, batch_size: int = 250) -> PersistentImportResult:
        if not 1 <= batch_size <= 1_000:
            raise ValueError("Persistent import batch size is outside the safe bound")
        plan = projection.plan()
        job_id = self._prepare(projection, plan)
        inserted_records = 0
        inserted_chunks = 0
        batch: list[PersistentRecordProjection] = []

        def flush() -> None:
            nonlocal inserted_records, inserted_chunks
            if not batch:
                return
            with self._factory() as session, session.begin():
                for record in batch:
                    records, chunks = self._upsert_record(session, record)
                    inserted_records += records
                    inserted_chunks += chunks
                checkpoint = json.dumps(
                    {"processed_records": inserted_records, "last_record_id": batch[-1].id},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                session.execute(
                    text(
                        "UPDATE dataset_import_jobs SET checkpoint=checkpoint || cast(:checkpoint AS jsonb),"
                        "updated_at=now() WHERE id=:job_id"
                    ),
                    {"job_id": job_id, "checkpoint": checkpoint},
                )
            batch.clear()

        try:
            for record in projection.records():
                batch.append(record)
                if len(batch) >= batch_size:
                    flush()
            flush()
            with self._factory() as session, session.begin():
                session.execute(
                    text(
                        "UPDATE dataset_releases SET status='completed',imported_records=:count,updated_at=now() "
                        "WHERE id=:release_id"
                    ),
                    {"release_id": projection.release_id, "count": inserted_records},
                )
                session.execute(
                    text(
                        "UPDATE dataset_import_jobs SET status='completed',completed_at=now(),updated_at=now() "
                        "WHERE id=:job_id"
                    ),
                    {"job_id": job_id},
                )
        except Exception as exc:
            self._mark_failed(release_id=projection.release_id, job_id=job_id, exc=exc)
            raise
        return PersistentImportResult(
            release_id=projection.release_id,
            job_id=job_id,
            logical_release_id=projection.logical_release_id,
            eligible_records=plan.eligible_count,
            processed_records=inserted_records,
            processed_chunks=inserted_chunks,
            registry_digest=plan.registry_digest,
        )
