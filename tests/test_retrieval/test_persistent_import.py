import hashlib
import json
import sqlite3

import pytest

from scripts.import_catalog_to_postgres import execution_gate
from services.retrieval import CatalogProjection, PersistentCatalogImporter
from src.config import Settings


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.sqlite3"
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
        INSERT INTO dataset_releases VALUES('dev-v4','development','catalog-hash','now','completed');
        """
    )
    source = {
        "global_source_id": "GLOBAL-1",
        "source_id": "LOCAL-1",
        "canonical_url": "https://example.test/canonical",
        "source_title": "Canonical source",
    }
    eligible = {
        "user_utterance_vi": "Tôi cần khám tim mạch.",
        "source_id": "LOCAL-1",
        "specialty_code": "CARDIOLOGY",
        "canonical_status": "REVIEW_REQUIRED",
        "review_status": "PENDING_CLINICAL_REVIEW",
        "private_note": "must never enter persistent metadata",
    }
    forbidden = {
        "user_utterance_vi": "Synthetic private patient record.",
        "source_id": "LOCAL-1",
        "specialty_code": "CARDIOLOGY",
    }
    connection.execute("INSERT INTO global_sources VALUES(?,?,?)", ("dev-v4", "GLOBAL-1", json.dumps(source)))
    connection.execute(
        "INSERT INTO dataset_rows VALUES(?,?,?,?,?,?)",
        ("dev-v4", "routing_rows", "route-1", hashlib.sha256(b"route-1").hexdigest(), json.dumps(eligible), 1),
    )
    connection.execute(
        "INSERT INTO dataset_rows VALUES(?,?,?,?,?,?)",
        (
            "dev-v4",
            "synthetic_profiles",
            "private-1",
            hashlib.sha256(b"private-1").hexdigest(),
            json.dumps(forbidden),
            2,
        ),
    )
    connection.commit()
    connection.close()
    return path


def test_catalog_projection_is_deterministic_citation_gated_and_minimal(catalog) -> None:
    first = CatalogProjection(catalog, "dev-v4", "development")
    second = CatalogProjection(catalog, "dev-v4", "development")
    records = tuple(first.records())
    assert first.release_id == second.release_id
    assert len(records) == 1
    record = records[0]
    assert record.origin_table == "routing_rows"
    assert record.metadata == {"specialty_code": "CARDIOLOGY"}
    assert "private_note" not in str(record)
    assert [source.source_id for source in record.sources] == ["GLOBAL-1"]
    assert record.chunks and all(len(chunk.content_hash) == 64 for chunk in record.chunks)
    plan = first.plan()
    assert plan.eligible_count == 1 and plan.candidate_count == 1


def test_production_projection_with_zero_approved_rows_fails_before_persistence(catalog) -> None:
    connection = sqlite3.connect(catalog)
    connection.execute("UPDATE dataset_releases SET mode='production' WHERE release_id='dev-v4'")
    connection.commit()
    connection.close()
    projection = CatalogProjection(catalog, "dev-v4", "production")
    plan = projection.plan()
    assert plan.eligible_count == 0
    importer = PersistentCatalogImporter(None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="approved eligible row count is zero"):
        importer._prepare(projection, plan)


def test_import_execution_gate_requires_verified_postgres() -> None:
    settings = Settings(database_url="sqlite:///ignored.sqlite3")
    allowed, reason = execution_gate(settings)
    assert not allowed and "PostgreSQL" in reason
    settings = Settings(
        database_url="postgresql+psycopg://user:password@localhost/vmec",
        vmec_persistent_pgvector_verified=False,
    )
    allowed, reason = execution_gate(settings)
    assert not allowed and "PGVECTOR" in reason
    assert execution_gate(
        Settings(
            database_url="postgresql+psycopg://user:password@localhost/vmec",
            vmec_persistent_pgvector_verified=True,
        )
    ) == (True, "")
