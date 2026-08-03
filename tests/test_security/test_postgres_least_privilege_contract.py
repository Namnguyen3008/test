from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v7_migration_defines_separate_nologin_roles_and_rls() -> None:
    migration = (ROOT / "migrations/versions/20260803_0010_signed_lifecycle_least_privilege.py").read_text(
        encoding="utf-8"
    )
    for role in (
        "vmec_migration_owner",
        "vmec_api",
        "vmec_worker",
        "vmec_importer",
        "vmec_analytics",
        "vmec_clinical_reporter",
        "vmec_governance",
        "vmec_backup",
    ):
        assert role in migration
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in migration
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "records_runtime_read" in migration
    assert "dataset_governance_update" in migration


def test_api_worker_and_migration_credentials_are_separate() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "MIGRATION_DATABASE_URL" in compose
    assert "API_DATABASE_URL" in compose
    assert "WORKER_DATABASE_URL" in compose
    assert "GOVERNANCE_DATABASE_URL" in compose
    values = (ROOT / "infra/helm/vmec/values.yaml").read_text(encoding="utf-8")
    assert "apiDatabaseUrlSecret" in values
    assert "workerDatabaseUrlSecret" in values
    assert "migrationDatabaseUrlSecret" in values


def test_completed_release_and_governance_audits_are_database_immutable() -> None:
    migration = (ROOT / "migrations/versions/20260803_0010_signed_lifecycle_least_privilege.py").read_text(
        encoding="utf-8"
    )
    assert "vmec_guard_completed_release_mutation" in migration
    assert "vmec_guard_completed_release_child_mutation" in migration
    assert 'for table in ("governance_lifecycle_artifacts", "governance_release_transitions")' in migration
    assert "vmec_prevent_governance_audit_mutation" in migration
