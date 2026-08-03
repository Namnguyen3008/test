"""Generate a PHI-free dual-embedding execution plan without API calls."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Literal, cast

from services.retrieval import (
    EMBEDDING_DIMENSIONS,
    PRIMARY_EMBEDDING_MODEL,
    TEXT_FALLBACK_EMBEDDING_MODEL,
    CitationRegistry,
    candidate_from_dataset_row,
    plan_embedding_backfill,
    retrieval_eligibility,
)

DataMode = Literal["development", "review", "production"]


def build_report(catalog: Path, release_id: str, mode: DataMode) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{catalog.resolve().as_posix()}?mode=ro", uri=True)
    try:
        release = connection.execute(
            "SELECT mode, status FROM dataset_releases WHERE release_id=?", (release_id,)
        ).fetchone()
        if release is None or release[1] != "completed":
            raise RuntimeError("Requested completed release is unavailable")
        ledger_rows = [
            json.loads(raw)
            for (raw,) in connection.execute(
                "SELECT payload_json FROM global_sources WHERE release_id=?", (release_id,)
            )
        ]
        citations = CitationRegistry.from_global_ledger(ledger_rows)
        candidates = []
        for table, row_id, content_hash, raw in connection.execute(
            "SELECT table_name,row_key,content_hash,payload_json FROM dataset_rows WHERE release_id=?",
            (release_id,),
        ):
            payload = json.loads(raw)
            candidate = candidate_from_dataset_row(table, row_id, content_hash, payload)
            if candidate.text:
                candidates.append(candidate)
        decisions = [retrieval_eligibility(item, mode=mode, citations=citations) for item in candidates]
        reasons = Counter(decision.reason.value for decision in decisions)
        allow_full = os.environ.get("VMEC_ALLOW_FULL_EMBEDDING_BACKFILL", "").lower() == "true"
        persistent_ready = os.environ.get("VMEC_PERSISTENT_PGVECTOR_VERIFIED", "").lower() == "true"
        plan = plan_embedding_backfill(
            candidates,
            mode=mode,
            citations=citations,
            allow_full_backfill=allow_full,
            persistent_pgvector_ready=persistent_ready,
        )
        return {
            "release_id": release_id,
            "mode": mode,
            "candidate_count": plan.candidate_count,
            "eligible_count": plan.eligible_count,
            "eligibility_reasons": dict(sorted(reasons.items())),
            "total_characters": plan.total_characters,
            "estimated_chunks": plan.estimated_chunks,
            "registry_digest": plan.registry_digest,
            "primary": {"model": PRIMARY_EMBEDDING_MODEL, "dimensions": EMBEDDING_DIMENSIONS},
            "text_fallback": {"model": TEXT_FALLBACK_EMBEDDING_MODEL, "dimensions": EMBEDDING_DIMENSIONS},
            "full_backfill_permitted": plan.full_backfill_permitted,
            "refusal_reason": plan.refusal_reason,
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("data/staging/vmec_catalog.sqlite3"))
    parser.add_argument("--release-id", default="vmec-development-v2")
    parser.add_argument("--mode", choices=("development", "review", "production"), default="development")
    parser.add_argument("--output", type=Path, default=Path("data/reports/embedding-backfill-plan.json"))
    args = parser.parse_args()
    report = build_report(args.catalog, args.release_id, cast(DataMode, args.mode))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PLAN_WRITTEN={args.output}")
    print(f"ELIGIBLE_COUNT={report['eligible_count']}")
    print(f"FULL_BACKFILL_PERMITTED={report['full_backfill_permitted']}")


if __name__ == "__main__":
    main()
