import json
import sqlite3

import pytest

from src.config import Settings
from src.services import routing as routing_module
from src.services.routing import CatalogRoutingRetriever


def insert_row(connection, release_id: str, table: str, key: str, payload: dict) -> None:
    connection.execute(
        "INSERT INTO dataset_rows VALUES (?,?,?,?,?)",
        (release_id, table, key, "hash-" + key, json.dumps(payload, ensure_ascii=False)),
    )


@pytest.mark.asyncio
async def test_catalog_runtime_is_citation_gated_and_lexical_only(tmp_path):
    database = tmp_path / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE dataset_releases (release_id TEXT PRIMARY KEY, mode TEXT, status TEXT);
        CREATE TABLE dataset_rows (
          release_id TEXT, table_name TEXT, row_key TEXT, content_hash TEXT, payload_json TEXT
        );
        CREATE TABLE global_sources (release_id TEXT, global_source_id TEXT, payload_json TEXT);
        INSERT INTO dataset_releases VALUES ('dev', 'development', 'completed');
        """
    )
    connection.execute(
        "INSERT INTO global_sources VALUES (?,?,?)",
        (
            "dev",
            "GLOBAL-1",
            json.dumps(
                {
                    "global_source_id": "GLOBAL-1",
                    "source_id": "LOCAL-1",
                    "canonical_url": "https://example.test/source",
                }
            ),
        ),
    )
    insert_row(
        connection,
        "dev",
        "specialty_reference",
        "specialty-1",
        {"specialty_code": "CARDIOLOGY", "name_vi": "Tim mạch"},
    )
    insert_row(
        connection,
        "dev",
        "routing_rows",
        "route-1",
        {
            "user_utterance_vi": "đau ngực khi vận động",
            "primary_specialty_code": "CARDIOLOGY",
            "source_id": "LOCAL-1",
            "canonical_status": "REVIEW_REQUIRED",
            "review_status": "PENDING_CLINICAL_REVIEW",
        },
    )
    insert_row(
        connection,
        "dev",
        "routing_rows",
        "route-without-source",
        {
            "user_utterance_vi": "đau ngực không nguồn",
            "primary_specialty_code": "CARDIOLOGY",
        },
    )
    connection.commit()
    connection.close()

    retriever = CatalogRoutingRetriever.from_catalog(database, release_id="dev", mode="development")
    result = await retriever.retrieve("đau ngực vận động")

    assert result.mode == "lexical-only"
    assert [record.record_id for record in result.records] == ["route-1"]
    assert result.valid_source_ids == frozenset({"GLOBAL-1"})
    assert result.allowed_specialty_ids == frozenset({"CARDIOLOGY"})


@pytest.mark.asyncio
async def test_production_runtime_fails_closed_for_review_required_rows(tmp_path):
    database = tmp_path / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE dataset_releases (release_id TEXT PRIMARY KEY, mode TEXT, status TEXT);
        CREATE TABLE dataset_rows (
          release_id TEXT, table_name TEXT, row_key TEXT, content_hash TEXT, payload_json TEXT
        );
        CREATE TABLE global_sources (release_id TEXT, global_source_id TEXT, payload_json TEXT);
        INSERT INTO dataset_releases VALUES ('prod', 'production', 'completed');
        """
    )
    connection.execute(
        "INSERT INTO global_sources VALUES (?,?,?)",
        (
            "prod",
            "GLOBAL-1",
            json.dumps(
                {
                    "global_source_id": "GLOBAL-1",
                    "source_id": "LOCAL-1",
                    "canonical_url": "https://example.test/source",
                }
            ),
        ),
    )
    insert_row(connection, "prod", "specialty_reference", "s", {"specialty_code": "CARDIOLOGY"})
    insert_row(
        connection,
        "prod",
        "routing_rows",
        "route-1",
        {
            "user_utterance_vi": "đau ngực",
            "primary_specialty_code": "CARDIOLOGY",
            "source_id": "LOCAL-1",
            "canonical_status": "REVIEW_REQUIRED",
            "review_status": "PENDING_CLINICAL_REVIEW",
        },
    )
    connection.commit()
    connection.close()

    retriever = CatalogRoutingRetriever.from_catalog(database, release_id="prod", mode="production")
    assert not (await retriever.retrieve("đau ngực")).records


def test_postgres_runtime_mode_refuses_non_postgres_database(monkeypatch) -> None:
    routing_module.get_routing_retriever.cache_clear()
    monkeypatch.setattr(
        routing_module,
        "get_settings",
        lambda: Settings(retrieval_runtime_mode="postgres", database_url="sqlite:///unsafe.db"),
    )
    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        routing_module.get_routing_retriever()
    routing_module.get_routing_retriever.cache_clear()


def test_configured_persistent_runtime_selects_postgres_adapter(monkeypatch) -> None:
    constructed: dict[str, object] = {}

    class FakeGateway:
        def __init__(self, api_key: str) -> None:
            constructed["key_present"] = bool(api_key)

        async def embed_query(self, query, space):  # pragma: no cover - construction-only test
            raise AssertionError

        async def aclose(self) -> None:
            return None

    class FakePersistentRetriever:
        def __init__(self, factory, embed_query, **kwargs) -> None:
            constructed["factory"] = factory
            constructed.update(kwargs)

    sentinel_factory = object()
    routing_module.get_routing_retriever.cache_clear()
    monkeypatch.setattr(
        routing_module,
        "get_settings",
        lambda: Settings(
            retrieval_runtime_mode="postgres",
            database_url="postgresql+psycopg://vmec.invalid/test",
            gemini_api_key="configured-not-returned",
        ),
    )
    monkeypatch.setattr(routing_module, "GeminiQueryEmbeddingGateway", FakeGateway)
    monkeypatch.setattr(routing_module, "PostgresHybridRetriever", FakePersistentRetriever)
    monkeypatch.setattr(routing_module, "get_session_factory", lambda: sentinel_factory)

    selected = routing_module.get_routing_retriever()
    assert isinstance(selected, routing_module.PostgresRoutingRetriever)
    assert constructed["factory"] is sentinel_factory
    assert constructed["release_id"] == "vmec-development-v2"
    assert constructed["data_mode"] == "development"
    assert constructed["key_present"] is True
    routing_module.get_routing_retriever.cache_clear()
