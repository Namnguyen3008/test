"""Provision local V8 PostgreSQL LOGIN members without printing credentials."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROLE_CONFIG: Mapping[str, tuple[str, str]] = {
    "VMEC_MIGRATION_DATABASE_URL": ("vmec_v8_migrator", "vmec_migration_owner"),
    "VMEC_API_DATABASE_URL": ("vmec_v8_api", "vmec_api"),
    "VMEC_WORKER_DATABASE_URL": ("vmec_v8_worker", "vmec_worker"),
    "VMEC_IMPORTER_DATABASE_URL": ("vmec_v8_importer", "vmec_importer"),
    "VMEC_ANALYTICS_DATABASE_URL": ("vmec_v8_analytics", "vmec_analytics"),
    "VMEC_CLINICAL_DATABASE_URL": ("vmec_v8_clinical", "vmec_clinical_reporter"),
    "GOVERNANCE_DATABASE_URL": ("vmec_v8_governance", "vmec_governance"),
    "VMEC_BACKUP_DATABASE_URL": ("vmec_v8_backup", "vmec_backup"),
}


def _password(url: str, expected_login: str) -> str:
    try:
        parsed = make_url(url)
    except Exception as exc:
        raise RuntimeError("dedicated database URL must be a valid PostgreSQL URL") from exc
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise RuntimeError("dedicated database URL must be PostgreSQL")
    if parsed.username != expected_login or parsed.password is None:
        raise RuntimeError("dedicated database URL does not match the expected local login")
    return parsed.password


def main() -> None:
    owner_url = os.environ.get("MIGRATION_DATABASE_URL", "")
    try:
        owner = make_url(owner_url)
    except Exception as exc:
        raise RuntimeError("MIGRATION_DATABASE_URL is required for local role provisioning") from exc
    if owner.drivername not in {"postgresql", "postgresql+psycopg"} or not owner.username or owner.password is None:
        raise RuntimeError("MIGRATION_DATABASE_URL is required for local role provisioning")
    values = {key: _password(os.environ.get(key, ""), login) for key, (login, _) in ROLE_CONFIG.items()}
    engine = create_engine(owner_url, pool_pre_ping=True)
    with engine.begin() as connection:
        for key, (login, group) in ROLE_CONFIG.items():
            existing = connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": login})
            pwd = values[key].replace("'", "''")
            if existing is None:
                connection.execute(
                    text(
                        f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        f"NOREPLICATION NOBYPASSRLS PASSWORD '{pwd}'"
                    )
                )
            else:
                connection.execute(text(f"ALTER ROLE {login} WITH PASSWORD '{pwd}'"))
            connection.execute(text(f"GRANT {group} TO {login}"))
        connection.execute(text("GRANT SELECT ON TABLE alembic_version TO vmec_api, vmec_worker, vmec_migration_owner, vmec_importer"))
    print("V8 local PostgreSQL login memberships provisioned")


if __name__ == "__main__":
    main()
