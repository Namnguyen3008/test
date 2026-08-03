"""Provision local V8 PostgreSQL LOGIN members without printing credentials."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy import create_engine, text

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
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("dedicated database URL must be PostgreSQL")
    try:
        credentials = url.split("://", 1)[1].split("@", 1)[0]
        login, password = credentials.split(":", 1)
    except ValueError as exc:
        raise RuntimeError("dedicated database URL must contain a login and password") from exc
    if login != expected_login or not password:
        raise RuntimeError("dedicated database URL does not match the expected local login")
    return password


def main() -> None:
    owner_url = os.environ.get("MIGRATION_DATABASE_URL", "")
    if not owner_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("MIGRATION_DATABASE_URL is required for local role provisioning")
    values = {key: _password(os.environ.get(key, ""), login) for key, (login, _) in ROLE_CONFIG.items()}
    engine = create_engine(owner_url, pool_pre_ping=True)
    with engine.begin() as connection:
        for key, (login, group) in ROLE_CONFIG.items():
            existing = connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": login})
            if existing is None:
                connection.execute(
                    text(
                        f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS PASSWORD :password"
                    ),
                    {"password": values[key]},
                )
            connection.execute(text(f"GRANT {group} TO {login}"))
    print("V8 local PostgreSQL login memberships provisioned")


if __name__ == "__main__":
    main()
