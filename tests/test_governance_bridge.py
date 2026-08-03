from __future__ import annotations

import base64
import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from src.governance.canonical import DuplicateKeyError, canonical_json, digest, signature_payload, strict_json_loads
from src.governance.manifest import GovernanceManifest, TrustRegistry, verify_evidence, verify_manifest, verify_receipt
from src.governance.promotion import (
    GovernancePromotionRepository,
    PromotionRecord,
    assert_manifest_scope,
    scope_snapshot,
)

NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def _key(capabilities: list[str] | None = None) -> tuple[Ed25519PrivateKey, dict[str, object]]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    key_id = hashlib.sha256(public).hexdigest()
    return private, {
        "key_id": key_id,
        "algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public).decode(),
        "capabilities": capabilities or ["APPROVAL_MANIFEST"],
        "valid_from": "2026-01-01T00:00:00Z",
        "not_after": "2027-01-01T00:00:00Z",
        "revoked_at": None,
        "revocation_reason": None,
    }


def _records() -> list[PromotionRecord]:
    return [
        PromotionRecord(
            "00000000-0000-0000-0000-000000000001",
            "review-v1",
            "faq",
            "1",
            "a" * 64,
            "REVIEW_REQUIRED",
            "PENDING_CLINICAL_REVIEW",
            "NONE",
            ("source-1",),
        ),
        PromotionRecord(
            "00000000-0000-0000-0000-000000000002",
            "review-v1",
            "adult_emergency_rules",
            "2",
            "b" * 64,
            "REVIEW_REQUIRED",
            "PENDING_GOLD_REVIEW",
            "",
            ("source-2",),
            True,
        ),
        PromotionRecord(
            "00000000-0000-0000-0000-000000000003",
            "review-v1",
            "faq",
            "3",
            "c" * 64,
            "REJECTED",
            "REJECTED",
            "CONFLICT",
            ("source-3",),
        ),
    ]


def _signed_manifest(
    *, gold: bool = True, evidence_digest: str = "d" * 64
) -> tuple[GovernanceManifest, TrustRegistry, Ed25519PrivateKey]:
    private, trusted = _key()
    snapshot = scope_snapshot(_records())
    reviewers = [
        {
            "reviewer_id": "reviewer-one",
            "organization": "Hospital",
            "authorization_reference": "AUTH-001",
            "scope": ["ALL_APPROVED_RELEASE_ROWS", "SAFETY_CRITICAL_AND_GOLD_CANDIDATES"],
            "decision": "APPROVE",
            "reviewed_at": "2026-08-03T06:00:00Z",
        }
    ]
    if gold:
        reviewers.append(
            {
                "reviewer_id": "reviewer-two",
                "organization": "Hospital",
                "authorization_reference": "AUTH-002",
                "scope": ["SAFETY_CRITICAL_AND_GOLD_CANDIDATES"],
                "decision": "APPROVE",
                "reviewed_at": "2026-08-03T06:30:00Z",
            }
        )
    raw = {
        "schema_version": "vmec.governance-approval.v1",
        "manifest_id": "manifest-0001",
        "project_id": "VMEC-01",
        "release_scope": {
            "release_ids": ["review-v1"],
            "registry_digest": snapshot.registry_digest,
            "expected_rows": 2,
            "canonical_sources": 2,
            "included_tables": ["adult_emergency_rules", "faq"],
            "included_row_hashes_digest": snapshot.row_hashes_digest,
        },
        "policy": {
            "policy_version": "vmec-governance-policy-v1",
            "accepted_policy": "ALL_ELIGIBLE_IN_SCOPE",
            "gold_policy": "EXPLICIT_GOLD_CANDIDATES_TWO_REVIEWERS",
        },
        "reviewers": reviewers,
        "owner_authorization": {
            "owner_id": "owner-one",
            "authorization_reference": "OWNER-AUTH-001",
            "authorized_at": "2026-08-03T07:00:00Z",
        },
        "evidence_package": {"schema_version": "vmec.review-evidence.v1", "package_digest": evidence_digest},
        "promotion": {
            "accepted_mode": "PROMOTE_ALL_ELIGIBLE_IN_SCOPE",
            "gold_mode": "PROMOTE_POLICY_GOLD_ONLY" if gold else "NO_GOLD_PROMOTION",
        },
        "issued_at": "2026-08-03T07:30:00Z",
        "expires_at": "2026-08-04T07:30:00Z",
        "signature": {
            "algorithm": "Ed25519",
            "key_id": trusted["key_id"],
            "value_base64": base64.b64encode(b"0" * 64).decode(),
        },
    }
    unsigned = GovernanceManifest.model_validate(raw)
    raw["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(unsigned.model_dump(mode="json")))
    ).decode()
    manifest = GovernanceManifest.model_validate(raw)
    registry = TrustRegistry.model_validate({"schema_version": "vmec.governance-trust-registry.v1", "keys": [trusted]})
    return manifest, registry, private


def test_signed_manifest_verifies_and_tampering_is_rejected() -> None:
    manifest, registry, _ = _signed_manifest()
    assert len(verify_manifest(manifest, registry, now=NOW)) == 64
    tampered = manifest.model_dump(mode="json")
    tampered["release_scope"]["expected_rows"] = 3
    with pytest.raises(ValueError, match="signature verification failed"):
        verify_manifest(GovernanceManifest.model_validate(tampered), registry, now=NOW)


def test_duplicate_keys_and_placeholders_are_rejected() -> None:
    with pytest.raises(DuplicateKeyError):
        strict_json_loads('{"schema_version":"x","schema_version":"y"}')
    manifest, _, _ = _signed_manifest()
    raw = manifest.model_dump(mode="json")
    raw["owner_authorization"]["authorization_reference"] = "FILL_OWNER"
    with pytest.raises(ValidationError, match="placeholder"):
        GovernanceManifest.model_validate(raw)


def test_revoked_key_wrong_signature_and_non_independent_gold_review_are_rejected() -> None:
    manifest, registry, _ = _signed_manifest()
    revoked = registry.model_dump(mode="json")
    revoked["keys"][0]["revoked_at"] = "2026-08-03T07:45:00Z"
    revoked["keys"][0]["revocation_reason"] = "compromised"
    with pytest.raises(ValueError, match="revoked"):
        verify_manifest(manifest, TrustRegistry.model_validate(revoked), now=NOW)
    malformed = manifest.model_dump(mode="json")
    malformed["signature"]["value_base64"] = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(ValueError, match="verification failed"):
        verify_manifest(GovernanceManifest.model_validate(malformed), registry, now=NOW)
    duplicate = manifest.model_dump(mode="json")
    duplicate["reviewers"][1]["reviewer_id"] = "REVIEWER-ONE"
    with pytest.raises(ValidationError, match="independent"):
        GovernanceManifest.model_validate(duplicate)


def test_scope_excludes_conflict_and_detects_any_drift() -> None:
    snapshot = scope_snapshot(_records())
    assert len(snapshot.records) == 2
    manifest, _, _ = _signed_manifest()
    assert_manifest_scope(manifest, snapshot)
    drifted = copy.deepcopy(_records())
    drifted[0] = replace(drifted[0], content_hash="f" * 64)
    with pytest.raises(ValueError, match="does not match"):
        assert_manifest_scope(manifest, scope_snapshot(drifted))


def test_receipt_signature_and_tamper_detection() -> None:
    private, trusted = _key(["PROMOTION_RECEIPT"])
    registry = TrustRegistry.model_validate({"schema_version": "vmec.governance-trust-registry.v1", "keys": [trusted]})
    receipt = {
        "schema_version": "vmec.governance-promotion-receipt.v1",
        "promotion_id": "promotion-1",
        "manifest_id": "manifest-1",
        "manifest_digest": "a" * 64,
        "scope_digest": "b" * 64,
        "production_release_id": "00000000-0000-0000-0000-000000000010",
        "production_logical_release_id": "vmec-production-v1",
        "accepted_rows": 1,
        "gold_rows": 0,
        "excluded_rows": 1,
        "audit_digest": "c" * 64,
        "committed_at": NOW.isoformat(),
        "signature": {"algorithm": "Ed25519", "key_id": trusted["key_id"], "value_base64": ""},
    }
    receipt["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(receipt, receipt=True))
    ).decode()
    assert len(verify_receipt(receipt, registry)) == 64
    receipt["gold_rows"] = 1
    with pytest.raises(ValueError, match="verification failed"):
        verify_receipt(receipt, registry)


def test_future_and_expired_manifests_fail_closed() -> None:
    manifest, registry, _ = _signed_manifest()
    with pytest.raises(ValueError, match="expired"):
        verify_manifest(manifest, registry, now=NOW + timedelta(days=2))
    with pytest.raises(ValueError, match="future"):
        verify_manifest(manifest, registry, now=NOW - timedelta(days=1))


def test_evidence_artifact_is_recomputed_and_tamper_rejected(tmp_path: Path) -> None:
    snapshot = scope_snapshot(_records())
    payload = {
        "schema_version": "vmec.review-evidence.v1",
        "release_id": "review-v1",
        "included_row_hashes_digest": snapshot.row_hashes_digest,
    }
    evidence = {**payload, "package_digest": digest(payload)}
    path = tmp_path / "evidence.json"
    path.write_bytes(canonical_json(evidence))
    manifest, _, _ = _signed_manifest(evidence_digest=str(evidence["package_digest"]))
    assert verify_evidence(manifest, path) == evidence["package_digest"]
    evidence["release_id"] = "tampered"
    path.write_bytes(canonical_json(evidence))
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_evidence(manifest, path)


def test_promotion_has_no_implicit_or_api_bypass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VMEC_ALLOW_GOVERNANCE_PROMOTION", raising=False)
    manifest, registry, _ = _signed_manifest()
    repository = GovernancePromotionRepository(None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="gate is disabled"):
        repository.promote(
            manifest,
            registry,
            receipt_key_path=tmp_path / "absent.key",
            evidence_path=tmp_path / "absent.json",
            now=NOW,
        )
