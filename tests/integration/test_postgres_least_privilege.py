"""Real-PostgreSQL privilege checks; never counted as PASS without dedicated logins."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

URLS = {
    role: os.environ.get(variable, "")
    for role, variable in {
        "migration": "VMEC_TEST_MIGRATION_DATABASE_URL",
        "api": "VMEC_TEST_API_DATABASE_URL",
        "worker": "VMEC_TEST_WORKER_DATABASE_URL",
        "importer": "VMEC_TEST_IMPORTER_DATABASE_URL",
        "governance": "VMEC_TEST_GOVERNANCE_DATABASE_URL",
        "analytics": "VMEC_TEST_ANALYTICS_DATABASE_URL",
        "clinical": "VMEC_TEST_CLINICAL_DATABASE_URL",
        "backup": "VMEC_TEST_BACKUP_DATABASE_URL",
    }.items()
}
pytestmark = pytest.mark.skipif(
    not all(URLS.values()), reason="all dedicated VMEC_TEST_*_DATABASE_URL role logins are required"
)


def _scalar(role: str, statement: str):
    with create_engine(URLS[role], pool_pre_ping=True).connect() as connection:
        return connection.scalar(text(statement))


def _denied(role: str, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with create_engine(URLS[role], pool_pre_ping=True).begin() as connection:
            connection.execute(text(statement))


def test_roles_have_no_runtime_admin_capabilities() -> None:
    rows = []
    with create_engine(URLS["migration"], pool_pre_ping=True).connect() as connection:
        rows = list(
            connection.execute(
                text("SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname LIKE 'vmec_%'")
            )
        )
    assert rows
    assert all(not any(row[1:]) for row in rows)


def test_runtime_roles_exercise_positive_and_negative_boundaries() -> None:
    assert _scalar("api", "SELECT count(*) FROM governance_release_routes") in {0, 1}
    _denied("api", "DELETE FROM governance_promotions")
    _denied("worker", "SELECT password_hash FROM users")
    _denied("importer", "INSERT INTO dataset_releases(id,logical_release_id,mode,source_hashes,status) VALUES('ffffffff-ffff-ffff-ffff-ffffffffffff','forbidden-production','production','{}','importing')")
    _denied("governance", "DELETE FROM governance_release_transitions")
    assert _scalar("analytics", "SELECT count(*) FROM vmec_analytics_events") is not None
    _denied("analytics", "SELECT password_hash FROM users")
    assert _scalar("clinical", "SELECT count(*) FROM vmec_clinical_review_report") is not None
    _denied("clinical", "SELECT * FROM auth_sessions")
    assert _scalar("backup", "SELECT count(*) FROM governance_lifecycle_artifacts") is not None
    _denied("backup", "UPDATE users SET active=false")


@pytest.mark.parametrize("role", ["api", "worker", "importer", "governance", "analytics", "clinical", "backup"])
def test_runtime_roles_cannot_create_schema(role: str) -> None:
    _denied(role, "CREATE TABLE vmec_forbidden_privilege_probe(id integer)")
