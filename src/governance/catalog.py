"""Read-only source-catalog scope and evidence derivation for governance drafts."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from services.retrieval.persistent_import import CatalogProjection

from .canonical import canonical_json, digest, strict_json_loads

_LEDGER_DOMAIN = b"VMEC\x00global-source-registry\x00v1\x00"


def _ledger_evidence(catalog: Path, release_id: str) -> tuple[int, str, int]:
    connection = sqlite3.connect(f"file:{catalog.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT global_source_id,payload_json FROM global_sources WHERE release_id=? ORDER BY global_source_id",
            (release_id,),
        ).fetchall()
        source_rows = int(
            connection.execute("SELECT count(*) FROM dataset_rows WHERE release_id=?", (release_id,)).fetchone()[0]
        )
    finally:
        connection.close()
    if not rows or any(not str(source_id).strip() for source_id, _ in rows):
        raise ValueError("canonical source ledger is empty or contains a blank id")
    source_ids = [str(source_id) for source_id, _ in rows]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("canonical source ledger contains duplicate ids")
    sha = hashlib.sha256(_LEDGER_DOMAIN)
    for source_id, raw_payload in rows:
        payload = str(source_id).encode() + b"\0" + canonical_json(strict_json_loads(str(raw_payload)))
        sha.update(len(payload).to_bytes(8, "big"))
        sha.update(payload)
    return len(rows), sha.hexdigest(), source_rows


def build_governance_draft(catalog: Path, release_id: str, mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if mode not in {"development", "review"}:
        raise ValueError("draft scope must originate from development or review mode")
    projection = CatalogProjection(catalog, release_id, mode)  # type: ignore[arg-type]
    plan = projection.plan()
    records = tuple(projection.records())
    row_lines = [
        "\0".join(
            (
                release_id,
                record.origin_table,
                record.origin_row_id,
                record.content_hash,
                hashlib.sha256(record.normalized_text.encode()).hexdigest(),
                ",".join(sorted(source.source_id for source in record.sources)),
                "1" if record.safety_critical else "0",
                "1" if record.gold_candidate else "0",
                record.gold_reason,
            )
        )
        for record in records
    ]
    row_digest = hashlib.sha256("\n".join(sorted(row_lines)).encode()).hexdigest()
    tables = sorted({record.origin_table for record in records})
    ledger_count, ledger_digest, source_rows = _ledger_evidence(catalog, release_id)
    machine_scope = {
        "release_ids": [release_id],
        "registry_digest": plan.registry_digest,
        "expected_rows": len(records),
        "canonical_sources": ledger_count,
        "included_tables": tables,
        "included_row_hashes_digest": row_digest,
    }
    scope_digest = digest(machine_scope)
    safety_count = sum(record.safety_critical for record in records)
    gold_count = sum(record.gold_candidate for record in records)
    evidence_payload = {
        "schema_version": "vmec.review-evidence.v1",
        "policy_version": "vmec-governance-policy-v1",
        "release_id": release_id,
        "release_mode": mode,
        "source_artifact_sha256": projection.source_hash(),
        "source_registry_digest": ledger_digest,
        "source_rows": source_rows,
        "retrieval_candidates": plan.candidate_count,
        "eligible_accepted": len(records),
        "gold_candidates": gold_count,
        "ordinary_accepted": len(records) - gold_count,
        "safety_critical": safety_count,
        "excluded_missing_source_or_ineligible": plan.candidate_count - plan.eligible_count,
        "included_row_hashes_digest": row_digest,
        "scope_digest": scope_digest,
    }
    evidence = {**evidence_payload, "package_digest": digest(evidence_payload)}
    draft = {
        "schema_version": "vmec.governance-approval-draft.v1",
        "draft_id": f"vmec-draft-{scope_digest[:24]}",
        "project_id": "VMEC-01",
        "release_scope": machine_scope,
        "candidate_counts": {
            "accepted_candidates": len(records),
            "ordinary_accepted_candidates": len(records) - gold_count,
            "gold_candidates": gold_count,
            "safety_critical_candidates": safety_count,
            "excluded_missing_source_or_ineligible": plan.candidate_count - plan.eligible_count,
        },
        "policy": {
            "policy_version": "vmec-governance-policy-v1",
            "accepted_policy": "ALL_ELIGIBLE_IN_SCOPE",
            "gold_policy": "EXPLICIT_GOLD_CANDIDATES_TWO_REVIEWERS",
        },
        "required_reviewer_slots": [
            {"scope": "ALL_APPROVED_RELEASE_ROWS", "minimum_independent_reviewers": 1},
            {"scope": "SAFETY_CRITICAL_AND_GOLD_CANDIDATES", "minimum_independent_reviewers": 2},
        ],
        "reviewers": None,
        "owner_authorization": None,
        "evidence_package": {
            "schema_version": "vmec.review-evidence.v1",
            "package_digest": evidence["package_digest"],
        },
        "issued_at": None,
        "expires_at": None,
        "signature": None,
        "missing_fields": [
            "manifest_id",
            "reviewers",
            "owner_authorization",
            "issued_at",
            "signature.key_id",
            "signature.value_base64",
        ],
    }
    return draft, evidence
