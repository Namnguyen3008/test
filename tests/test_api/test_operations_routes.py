import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth_routes import AuthContext, authenticated_context
from src.api.operations_routes import router
from src.config import Settings
from src.security.auth import Principal, Role


def build_catalog(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE dataset_releases (release_id TEXT PRIMARY KEY, mode TEXT, source_hash TEXT, created_at TEXT, status TEXT);
        CREATE TABLE dataset_rows (release_id TEXT, table_name TEXT, row_key TEXT, content_hash TEXT, payload_json TEXT);
        CREATE TABLE global_sources (release_id TEXT, global_source_id TEXT, payload_json TEXT);
        INSERT INTO dataset_releases VALUES ('vmec-development-v2','development','hash','now','completed');
        """
    )
    connection.execute(
        "INSERT INTO global_sources VALUES (?,?,?)",
        ("vmec-development-v2", "GLOBAL-1", "{}"),
    )
    connection.execute(
        "INSERT INTO dataset_rows VALUES (?,?,?,?,?)",
        (
            "vmec-development-v2",
            "routing_rows",
            "route-1",
            "hash-route-1",
            json.dumps(
                {
                    "user_utterance_vi": "Nội dung cần duyệt",
                    "canonical_status": "REVIEW_REQUIRED",
                    "review_status": "PENDING_CLINICAL_REVIEW",
                    "source_id": "GLOBAL-1",
                },
                ensure_ascii=False,
            ),
        ),
    )
    connection.execute(
        "INSERT INTO dataset_rows VALUES (?,?,?,?,?)",
        (
            "vmec-development-v2",
            "prompt_injection",
            "hidden-1",
            "hash-hidden",
            json.dumps({"user_utterance_vi": "must never be shown"}),
        ),
    )
    connection.commit()
    connection.close()


def test_review_queue_is_role_restricted_allowlisted_and_read_only(tmp_path, monkeypatch) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    build_catalog(catalog)
    monkeypatch.setattr(
        "src.api.operations_routes.get_settings",
        lambda: Settings(emergency_catalog_path=str(catalog), gemini_api_key="configured-not-returned"),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[authenticated_context] = lambda: AuthContext(
        Principal("reviewer", Role.CLINICAL_REVIEWER), "session"
    )
    client = TestClient(app)
    response = client.get("/api/v1/review/items")
    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert [item["row_id"] for item in response.json()["items"]] == ["route-1"]
    assert "must never be shown" not in response.text


def test_admin_diagnostics_are_aggregate_and_do_not_expose_secret(tmp_path, monkeypatch) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    build_catalog(catalog)
    monkeypatch.setattr(
        "src.api.operations_routes.get_settings",
        lambda: Settings(emergency_catalog_path=str(catalog), gemini_api_key="configured-not-returned"),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[authenticated_context] = lambda: AuthContext(Principal("admin", Role.ADMIN), "session")
    response = TestClient(app).get("/api/v1/admin/diagnostics")
    assert response.status_code == 200
    assert response.json()["imported_rows"] == 2
    assert response.json()["gemini_key_configured"] is True
    assert "configured-not-returned" not in response.text
    assert response.json()["production_approved"] is False


def test_patient_cannot_access_review_or_admin(tmp_path, monkeypatch) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    build_catalog(catalog)
    monkeypatch.setattr(
        "src.api.operations_routes.get_settings",
        lambda: Settings(emergency_catalog_path=str(catalog)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[authenticated_context] = lambda: AuthContext(Principal("patient", Role.PATIENT), "session")
    client = TestClient(app)
    assert client.get("/api/v1/review/items").status_code == 403
    assert client.get("/api/v1/admin/diagnostics").status_code == 403
