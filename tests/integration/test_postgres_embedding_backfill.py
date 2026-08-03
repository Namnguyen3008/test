import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.retrieval import (
    EMBEDDING_DIMENSIONS,
    FALLBACK_EMBEDDING_SPACE,
    PRIMARY_EMBEDDING_SPACE,
    CatalogProjection,
    PersistentCatalogImporter,
    PersistentEmbeddingBackfill,
)

POSTGRES_URL = os.environ.get("VMEC_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="VMEC_TEST_POSTGRES_URL is not configured")


def _catalog(path: Path, source_id: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE dataset_releases(
          release_id TEXT PRIMARY KEY, mode TEXT, source_hash TEXT, created_at TEXT, status TEXT
        );
        CREATE TABLE global_sources(release_id TEXT, global_source_id TEXT, payload_json TEXT);
        CREATE TABLE dataset_rows(
          release_id TEXT, table_name TEXT, row_key TEXT, content_hash TEXT,
          payload_json TEXT, origin_row_number INTEGER
        );
        INSERT INTO dataset_releases VALUES('ci-development','development','ci-source-hash','now','completed');
        """
    )
    source = {
        "global_source_id": source_id,
        "source_id": source_id,
        "canonical_url": "https://example.test/import-source",
        "source_title": "CI import source",
    }
    payload = {
        "user_utterance_vi": "Grounded persistent import record.",
        "source_id": source_id,
        "specialty_code": "CI-SPECIALTY",
        "canonical_status": "REVIEW_REQUIRED",
        "review_status": "PENDING_CLINICAL_REVIEW",
    }
    connection.execute("INSERT INTO global_sources VALUES(?,?,?)", ("ci-development", source_id, json.dumps(source)))
    connection.execute(
        "INSERT INTO dataset_rows VALUES(?,?,?,?,?,1)",
        (
            "ci-development",
            "routing_rows",
            "ci-route-1",
            hashlib.sha256(b"ci-route-1").hexdigest(),
            json.dumps(payload),
        ),
    )
    connection.commit()
    connection.close()


def test_real_postgres_catalog_import_is_idempotent(tmp_path) -> None:
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    source_id = f"CI-IMPORT-{uuid.uuid4().hex}"
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog, source_id)
    projection = CatalogProjection(catalog, "ci-development", "development")
    importer = PersistentCatalogImporter(factory)
    try:
        first = importer.run(projection, batch_size=1)
        second = importer.run(projection, batch_size=1)
        assert first.release_id == second.release_id
        assert first.processed_records == second.processed_records == 1
        with factory() as session:
            records = session.scalar(
                text("SELECT count(*) FROM knowledge_records WHERE release_id=:release_id"),
                {"release_id": projection.release_id},
            )
            chunks = session.scalar(
                text(
                    "SELECT count(*) FROM knowledge_chunks kc JOIN knowledge_records kr ON kr.id=kc.record_id "
                    "WHERE kr.release_id=:release_id"
                ),
                {"release_id": projection.release_id},
            )
            status = session.scalar(
                text("SELECT status FROM dataset_releases WHERE id=:release_id"),
                {"release_id": projection.release_id},
            )
        assert records == 1 and chunks == 1 and status == "completed"
    finally:
        with factory() as session, session.begin():
            session.execute(
                text(
                    "DELETE FROM knowledge_chunks WHERE record_id IN "
                    "(SELECT id FROM knowledge_records WHERE release_id=:release_id)"
                ),
                {"release_id": projection.release_id},
            )
            session.execute(
                text(
                    "DELETE FROM knowledge_record_sources WHERE record_id IN "
                    "(SELECT id FROM knowledge_records WHERE release_id=:release_id)"
                ),
                {"release_id": projection.release_id},
            )
            session.execute(
                text("DELETE FROM knowledge_records WHERE release_id=:release_id"),
                {"release_id": projection.release_id},
            )
            session.execute(
                text("DELETE FROM dataset_import_jobs WHERE release_id=:release_id"),
                {"release_id": projection.release_id},
            )
            session.execute(
                text("DELETE FROM dataset_releases WHERE id=:release_id"),
                {"release_id": projection.release_id},
            )
            session.execute(text("DELETE FROM global_sources WHERE id=:source_id"), {"source_id": source_id})
        engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_dual_backfill_is_resumable_and_model_isolated() -> None:
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    release_id = str(uuid.uuid4())
    record_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    chunk_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    source_id = f"CI-{uuid.uuid4().hex}"
    document = "Grounded integration-test corpus text."
    content_hash = hashlib.sha256(document.encode()).hexdigest()
    calls: list[str] = []

    async def embed(value, space):
        calls.append(space.model_id)
        return (1.0,) + (0.0,) * (EMBEDDING_DIMENSIONS - 1)

    try:
        with factory() as session, session.begin():
            session.execute(
                text("INSERT INTO dataset_releases(id,mode,source_hashes) VALUES(:id,'development','{}'::jsonb)"),
                {"id": release_id},
            )
            session.execute(
                text(
                    "INSERT INTO global_sources(id,canonical_url,title,metadata) "
                    "VALUES(:id,'https://example.test/canonical','CI source','{}'::jsonb)"
                ),
                {"id": source_id},
            )
            for ordinal, (record_id, chunk_id) in enumerate(zip(record_ids, chunk_ids, strict=True)):
                session.execute(
                    text(
                        "INSERT INTO knowledge_records("
                        "id,release_id,origin_table,origin_row_id,mode,canonical_status,review_status,"
                        "conflict_status,normalized_text,content_hash,metadata) VALUES("
                        ":id,:release_id,'routing_rows',:origin_row_id,'development','REVIEW_REQUIRED',"
                        "'PENDING_CLINICAL_REVIEW','',:document,:content_hash,cast(:metadata AS jsonb))"
                    ),
                    {
                        "id": record_id,
                        "release_id": release_id,
                        "origin_row_id": f"ci-row-{ordinal}",
                        "document": document,
                        "content_hash": content_hash,
                        "metadata": json.dumps({"specialty_code": "CI-SPECIALTY"}),
                    },
                )
                session.execute(
                    text(
                        "INSERT INTO knowledge_record_sources(record_id,source_id,evidence_locator) "
                        "VALUES(:record_id,:source_id,'CI locator')"
                    ),
                    {"record_id": record_id, "source_id": source_id},
                )
                session.execute(
                    text(
                        "INSERT INTO knowledge_chunks(id,record_id,ordinal,normalized_text,content_hash,token_count) "
                        "VALUES(:id,:record_id,0,:document,:content_hash,8)"
                    ),
                    {
                        "id": chunk_id,
                        "record_id": record_id,
                        "document": document,
                        "content_hash": content_hash,
                    },
                )

        runner = PersistentEmbeddingBackfill(factory, embed)
        primary = await runner.run(
            release_id=release_id,
            data_mode="development",
            space=PRIMARY_EMBEDDING_SPACE,
            max_items=10,
        )
        assert calls == ["gemini-embedding-2"]
        assert primary.complete == 1

        calls.clear()
        resumed = await runner.run(
            release_id=release_id,
            data_mode="development",
            space=PRIMARY_EMBEDDING_SPACE,
            max_items=10,
        )
        assert calls == []
        assert resumed.complete == 1

        fallback = await runner.run(
            release_id=release_id,
            data_mode="development",
            space=FALLBACK_EMBEDDING_SPACE,
            max_items=10,
        )
        assert calls == ["gemini-embedding-001"]
        assert fallback.complete == 1
        with factory() as session:
            counts = dict(
                session.execute(
                    text(
                        "SELECT model_id,count(*) FROM knowledge_embeddings "
                        "WHERE chunk_id IN (:chunk_1,:chunk_2) GROUP BY model_id"
                    ),
                    {"chunk_1": chunk_ids[0], "chunk_2": chunk_ids[1]},
                )
            )
        assert counts == {"gemini-embedding-2": 2, "gemini-embedding-001": 2}
    finally:
        with factory() as session, session.begin():
            session.execute(
                text(
                    "DELETE FROM embedding_quarantine WHERE job_id IN (SELECT id FROM embedding_jobs WHERE checkpoint->>'release_id'=:release_id)"
                ),
                {"release_id": release_id},
            )
            session.execute(
                text(
                    "DELETE FROM embedding_job_items WHERE job_id IN (SELECT id FROM embedding_jobs WHERE checkpoint->>'release_id'=:release_id)"
                ),
                {"release_id": release_id},
            )
            session.execute(
                text("DELETE FROM embedding_jobs WHERE checkpoint->>'release_id'=:release_id"),
                {"release_id": release_id},
            )
            session.execute(
                text("DELETE FROM knowledge_embeddings WHERE chunk_id IN (:a,:b)"),
                {"a": chunk_ids[0], "b": chunk_ids[1]},
            )
            session.execute(
                text("DELETE FROM knowledge_chunks WHERE record_id IN (:a,:b)"),
                {"a": record_ids[0], "b": record_ids[1]},
            )
            session.execute(
                text("DELETE FROM knowledge_record_sources WHERE record_id IN (:a,:b)"),
                {"a": record_ids[0], "b": record_ids[1]},
            )
            session.execute(
                text("DELETE FROM knowledge_records WHERE release_id=:release_id"), {"release_id": release_id}
            )
            session.execute(text("DELETE FROM global_sources WHERE id=:source_id"), {"source_id": source_id})
            session.execute(text("DELETE FROM dataset_releases WHERE id=:release_id"), {"release_id": release_id})
        engine.dispose()
