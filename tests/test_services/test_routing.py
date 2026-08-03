import json
import sqlite3

import pytest

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
