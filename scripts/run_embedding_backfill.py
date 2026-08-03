"""Run a bounded persistent embedding smoke job or explicitly authorized full job."""

# ruff: noqa: E402 -- direct script execution bootstraps the repository import root.

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from services.retrieval import (
    FALLBACK_EMBEDDING_SPACE,
    PRIMARY_EMBEDDING_SPACE,
    GeminiQueryEmbeddingGateway,
    PersistentEmbeddingBackfill,
)
from services.retrieval.spaces import EmbeddingSpace
from src.config import Settings, get_settings

ExecutionMode = Literal["smoke", "full"]


def execution_gate(mode: ExecutionMode, settings: Settings) -> tuple[bool, str]:
    if not settings.database_url.startswith(("postgresql://", "postgresql+")):
        return False, "persistent PostgreSQL is not configured"
    if not settings.vmec_persistent_pgvector_verified:
        return False, "VMEC_PERSISTENT_PGVECTOR_VERIFIED is not enabled"
    if not settings.gemini_api_key.get_secret_value():
        return False, "GEMINI_API_KEY is not configured"
    if mode == "full" and not settings.vmec_allow_full_embedding_backfill:
        return False, "VMEC_ALLOW_FULL_EMBEDDING_BACKFILL is not enabled"
    return True, ""


def verify_runtime(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        vector = session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"))
        migration = session.scalar(text("SELECT version_num FROM alembic_version"))
    if vector is not True:
        raise RuntimeError("pgvector extension is not available")
    if migration != "20260803_0008_persistent_import":
        raise RuntimeError("persistent database is not at the required migration head")


async def execute(args: argparse.Namespace, settings: Settings) -> int:
    mode = cast(ExecutionMode, args.execution)
    permitted, reason = execution_gate(mode, settings)
    if not permitted:
        print("BACKFILL_STARTED=false")
        print(f"REFUSAL_REASON={reason}")
        return 2

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    gateway = GeminiQueryEmbeddingGateway(settings.gemini_api_key.get_secret_value())
    try:
        await asyncio.to_thread(verify_runtime, factory)
        runner = PersistentEmbeddingBackfill(
            factory,
            gateway.embed_document,
            max_attempts=args.max_attempts,
            retry_base_seconds=args.retry_base_seconds,
            rate_limit_seconds=args.rate_limit_seconds,
        )
        spaces: tuple[EmbeddingSpace, ...]
        if args.space == "primary":
            spaces = (PRIMARY_EMBEDDING_SPACE,)
        elif args.space == "fallback":
            spaces = (FALLBACK_EMBEDDING_SPACE,)
        else:
            spaces = (PRIMARY_EMBEDDING_SPACE, FALLBACK_EMBEDDING_SPACE)
        for space in spaces:
            result = await runner.run(
                release_id=args.release_id,
                data_mode=args.data_mode,
                space=space,
                batch_limit=args.batch_limit,
                max_items=args.smoke_items if mode == "smoke" else None,
            )
            print(f"MODEL={result.model_id}")
            print(f"COMPLETE={result.complete}")
            print(f"PENDING={result.pending}")
            print(f"FAILED={result.failed}")
            print(f"QUARANTINED={result.quarantined}")
        return 0
    except Exception as exc:
        print("BACKFILL_COMPLETED=false")
        print(f"ERROR_CODE={type(exc).__name__}")
        return 1
    finally:
        await gateway.aclose()
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--release-id", required=True, help="Persistent dataset_releases UUID")
    parser.add_argument("--data-mode", choices=("development", "review", "production"), required=True)
    parser.add_argument("--space", choices=("primary", "fallback", "both"), default="both")
    parser.add_argument("--smoke-items", type=int, default=10)
    parser.add_argument("--batch-limit", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=30)
    parser.add_argument("--rate-limit-seconds", type=float, default=0.2)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(execute(parse_args(), get_settings())))


if __name__ == "__main__":
    main()
