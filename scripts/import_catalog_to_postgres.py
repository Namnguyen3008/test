"""Import citation-gated retrieval records from an immutable catalog into PostgreSQL."""

# ruff: noqa: E402 -- direct script execution bootstraps the repository import root.

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from services.retrieval import CatalogProjection, PersistentCatalogImporter
from services.retrieval.registry import DataMode
from src.config import Settings, get_settings


def execution_gate(settings: Settings) -> tuple[bool, str]:
    if not settings.database_url.startswith(("postgresql://", "postgresql+")):
        return False, "persistent PostgreSQL is not configured"
    if not settings.vmec_persistent_pgvector_verified:
        return False, "VMEC_PERSISTENT_PGVECTOR_VERIFIED is not enabled"
    return True, ""


def verify_runtime(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        vector = session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"))
        migration = session.scalar(text("SELECT version_num FROM alembic_version"))
    if vector is not True:
        raise RuntimeError("pgvector extension is not available")
    if migration != "20260803_0008_persistent_import":
        raise RuntimeError("persistent database is not at the required migration head")


def execute(args: argparse.Namespace, settings: Settings) -> int:
    permitted, reason = execution_gate(settings)
    if not permitted:
        print("IMPORT_STARTED=false")
        print(f"REFUSAL_REASON={reason}")
        return 2
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        verify_runtime(factory)
        projection = CatalogProjection(args.catalog, args.logical_release_id, cast(DataMode, args.data_mode))
        result = PersistentCatalogImporter(factory).run(projection, batch_size=args.batch_size)
        print("IMPORT_COMPLETED=true")
        print(f"PERSISTENT_RELEASE_ID={result.release_id}")
        print(f"ELIGIBLE_RECORDS={result.eligible_records}")
        print(f"PROCESSED_RECORDS={result.processed_records}")
        print(f"PROCESSED_CHUNKS={result.processed_chunks}")
        print(f"REGISTRY_DIGEST={result.registry_digest}")
        return 0
    except Exception as exc:
        print("IMPORT_COMPLETED=false")
        print(f"ERROR_CODE={type(exc).__name__}")
        return 1
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("data/staging/vmec_catalog.sqlite3"))
    parser.add_argument("--logical-release-id", required=True)
    parser.add_argument("--data-mode", choices=("development", "review", "production"), required=True)
    parser.add_argument("--batch-size", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(execute(parse_args(), get_settings()))


if __name__ == "__main__":
    main()
