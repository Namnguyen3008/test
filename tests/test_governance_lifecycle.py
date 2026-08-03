from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from src.governance.canonical import signature_payload
from src.governance.lifecycle import GovernanceRevocation, GovernanceSupersession, verify_lifecycle_artifact
from src.governance.manifest import TrustRegistry

NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)


def _key(capability: str):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    key_id = hashlib.sha256(public).hexdigest()
    registry = TrustRegistry.model_validate(
        {
            "schema_version": "vmec.governance-trust-registry.v1",
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "Ed25519",
                    "public_key_base64": base64.b64encode(public).decode(),
                    "capabilities": [capability],
                    "valid_from": "2026-01-01T00:00:00Z",
                    "not_after": "2027-01-01T00:00:00Z",
                    "revoked_at": None,
                    "revocation_reason": None,
                }
            ],
        }
    )
    return private, key_id, registry


def _binding(prefix: str, scope: str = "c") -> dict[str, str]:
    return {
        "manifest_id": f"manifest-{prefix}",
        "manifest_digest": prefix * 64,
        "production_release_id": f"00000000-0000-0000-0000-0000000000{prefix}{prefix}",
        "promotion_receipt_digest": ("d" if prefix == "a" else "e") * 64,
        "clinical_scope_digest": scope * 64,
    }


def _base(key_id: str) -> dict[str, object]:
    return {
        "artifact_id": "lifecycle-0001",
        "project_id": "VMEC-01",
        "route_name": "vmec-production-v1",
        "expected_generation": 1,
        "reason": "Approved emergency production lifecycle change",
        "effective_at": "2026-08-03T11:00:00Z",
        "owner_authorization": {
            "owner_id": "release-owner",
            "authorization_reference": "OWNER-AUTH-9001",
            "authorized_at": "2026-08-03T10:00:00Z",
        },
        "issued_at": "2026-08-03T10:30:00Z",
        "expires_at": "2026-08-04T10:30:00Z",
        "signature": {"algorithm": "Ed25519", "key_id": key_id, "value_base64": base64.b64encode(b"0" * 64).decode()},
    }


def _signed_revocation():
    private, key_id, registry = _key("GOVERNANCE_REVOCATION")
    raw = {
        **_base(key_id),
        "schema_version": "vmec.governance-revocation.v1",
        "target": _binding("a"),
        "emergency_withdrawal": True,
    }
    artifact = GovernanceRevocation.model_validate(raw)
    raw["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(artifact.model_dump(mode="json"), domain="revocation"))
    ).decode()
    return GovernanceRevocation.model_validate(raw), registry


def test_valid_revocation_and_tampering_fail_closed() -> None:
    artifact, registry = _signed_revocation()
    assert len(verify_lifecycle_artifact(artifact, registry, now=NOW)) == 64
    tampered = artifact.model_copy(update={"expected_generation": 2})
    with pytest.raises(ValueError, match="verification failed"):
        verify_lifecycle_artifact(tampered, registry, now=NOW)


def test_cross_domain_and_wrong_capability_are_rejected() -> None:
    artifact, registry = _signed_revocation()
    private, key_id, wrong_registry = _key("GOVERNANCE_SUPERSESSION")
    raw = artifact.model_dump(mode="json")
    raw["signature"]["key_id"] = key_id
    raw["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(raw, domain="supersession"))
    ).decode()
    with pytest.raises(ValueError, match="capability"):
        verify_lifecycle_artifact(GovernanceRevocation.model_validate(raw), wrong_registry, now=NOW)
    raw["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(raw, domain="revocation"))
    ).decode()
    with pytest.raises(ValueError, match="capability"):
        verify_lifecycle_artifact(GovernanceRevocation.model_validate(raw), wrong_registry, now=NOW)


def test_supersession_clinical_change_requires_two_independent_reviewers() -> None:
    _, key_id, _ = _key("GOVERNANCE_SUPERSESSION")
    raw = {
        **_base(key_id),
        "schema_version": "vmec.governance-supersession.v1",
        "previous": _binding("a", "a"),
        "replacement": _binding("b", "b"),
        "clinical_scope_changed": True,
        "clinical_attestations": [],
    }
    with pytest.raises(ValidationError, match="two independent"):
        GovernanceSupersession.model_validate(raw)


def test_valid_supersession_uses_distinct_domain_and_capability() -> None:
    private, key_id, registry = _key("GOVERNANCE_SUPERSESSION")
    raw = {
        **_base(key_id),
        "schema_version": "vmec.governance-supersession.v1",
        "previous": _binding("a"),
        "replacement": _binding("b"),
        "clinical_scope_changed": False,
        "clinical_attestations": [],
    }
    artifact = GovernanceSupersession.model_validate(raw)
    raw["signature"]["value_base64"] = base64.b64encode(
        private.sign(signature_payload(artifact.model_dump(mode="json"), domain="supersession"))
    ).decode()
    signed = GovernanceSupersession.model_validate(raw)
    assert len(verify_lifecycle_artifact(signed, registry, now=NOW)) == 64


def test_stale_expired_future_and_naive_artifacts_are_rejected() -> None:
    artifact, registry = _signed_revocation()
    with pytest.raises(ValueError, match="expired"):
        verify_lifecycle_artifact(artifact, registry, now=NOW + timedelta(days=2))
    with pytest.raises(ValueError, match="future|not effective"):
        verify_lifecycle_artifact(artifact, registry, now=NOW - timedelta(hours=2))
    raw = artifact.model_dump(mode="json")
    raw["issued_at"] = "2026-08-03T10:30:00"
    with pytest.raises(ValidationError, match="timezone-aware"):
        GovernanceRevocation.model_validate(raw)
