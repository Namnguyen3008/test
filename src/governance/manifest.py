"""Strict manifest/trust-registry validation and Ed25519 verification."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import digest, signature_payload, strict_json_loads

HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _placeholder_free(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(token in normalized.upper() for token in ("FILL_", "TBD", "TODO", "PLACEHOLDER")):
        raise ValueError("unresolved placeholder is forbidden")
    return normalized


class StrictModel(BaseModel):
    # JSON date-times necessarily arrive as strings; nested fields still use
    # precise types and unknown fields are rejected.
    model_config = ConfigDict(extra="forbid")


class ReleaseScope(StrictModel):
    release_ids: list[str] = Field(min_length=1)
    registry_digest: HexDigest
    expected_rows: int = Field(ge=1)
    canonical_sources: int = Field(ge=1)
    included_tables: list[str] = Field(min_length=1)
    included_row_hashes_digest: HexDigest

    @model_validator(mode="after")
    def unique_scope(self) -> ReleaseScope:
        if len(self.release_ids) != 1:
            raise ValueError("governance manifest v1 supports exactly one immutable source release")
        if len(set(self.release_ids)) != len(self.release_ids) or len(set(self.included_tables)) != len(
            self.included_tables
        ):
            raise ValueError("release and table scope must be unique")
        if self.release_ids != sorted(self.release_ids) or self.included_tables != sorted(self.included_tables):
            raise ValueError("release and table scope must be canonical sorted order")
        return self


class Policy(StrictModel):
    policy_version: str
    accepted_policy: Literal["ALL_ELIGIBLE_IN_SCOPE"]
    gold_policy: Literal["SAFETY_CRITICAL_TWO_REVIEWERS", "EXPLICIT_GOLD_CANDIDATES_TWO_REVIEWERS"]


class Reviewer(StrictModel):
    reviewer_id: str = Field(min_length=3)
    organization: str = Field(min_length=2)
    authorization_reference: str = Field(min_length=3)
    scope: list[str] = Field(min_length=1)
    decision: Literal["APPROVE"]
    reviewed_at: datetime

    _reviewer = field_validator("reviewer_id", "organization", "authorization_reference")(_placeholder_free)

    @field_validator("scope")
    @classmethod
    def valid_scope(cls, value: list[str]) -> list[str]:
        allowed = {"ALL_APPROVED_RELEASE_ROWS", "SAFETY_CRITICAL_AND_GOLD_CANDIDATES"}
        if not value or set(value) - allowed or len(set(value)) != len(value):
            raise ValueError("reviewer scope is invalid")
        return sorted(value)


class OwnerAuthorization(StrictModel):
    owner_id: str
    authorization_reference: str
    authorized_at: datetime

    _owner = field_validator("owner_id", "authorization_reference")(_placeholder_free)


class EvidencePackage(StrictModel):
    schema_version: Literal["vmec.review-evidence.v1"]
    package_digest: HexDigest


class Promotion(StrictModel):
    accepted_mode: Literal["PROMOTE_ALL_ELIGIBLE_IN_SCOPE"]
    gold_mode: Literal["PROMOTE_POLICY_GOLD_ONLY", "NO_GOLD_PROMOTION"]


class Signature(StrictModel):
    algorithm: Literal["Ed25519"]
    key_id: HexDigest
    value_base64: str = Field(min_length=40)


class GovernanceManifest(StrictModel):
    schema_version: Literal["vmec.governance-approval.v1"]
    manifest_id: str = Field(min_length=8)
    project_id: Literal["VMEC-01"]
    release_scope: ReleaseScope
    policy: Policy
    reviewers: list[Reviewer] = Field(min_length=1)
    owner_authorization: OwnerAuthorization
    evidence_package: EvidencePackage
    promotion: Promotion
    issued_at: datetime
    expires_at: datetime | None = None
    signature: Signature

    _manifest_id = field_validator("manifest_id")(_placeholder_free)

    @model_validator(mode="after")
    def reviewer_policy(self) -> GovernanceManifest:
        reviewer_ids = [reviewer.reviewer_id.casefold() for reviewer in self.reviewers]
        if len(set(reviewer_ids)) != len(reviewer_ids):
            raise ValueError("reviewers must be independent and unique")
        if not any("ALL_APPROVED_RELEASE_ROWS" in reviewer.scope for reviewer in self.reviewers):
            raise ValueError("accepted rows require an all-approved-rows reviewer")
        if self.promotion.gold_mode == "PROMOTE_POLICY_GOLD_ONLY":
            gold_reviewers = [
                reviewer for reviewer in self.reviewers if "SAFETY_CRITICAL_AND_GOLD_CANDIDATES" in reviewer.scope
            ]
            if len({reviewer.reviewer_id.casefold() for reviewer in gold_reviewers}) < 2:
                raise ValueError("GOLD promotion requires two independent scoped reviewers")
        return self

    def unsigned_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class TrustedKey(StrictModel):
    key_id: HexDigest
    algorithm: Literal["Ed25519"]
    public_key_base64: str
    capabilities: list[Literal["APPROVAL_MANIFEST", "PROMOTION_RECEIPT"]]
    valid_from: datetime
    not_after: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> TrustedKey:
        if self.revoked_at is not None and not self.revocation_reason:
            raise ValueError("revoked keys require a reason")
        return self

    def raw_public_key(self) -> bytes:
        try:
            raw = base64.b64decode(self.public_key_base64, validate=True)
        except ValueError as exc:
            raise ValueError("trusted public key is not strict base64") from exc
        if len(raw) != 32 or hashlib.sha256(raw).hexdigest() != self.key_id:
            raise ValueError("trusted key fingerprint mismatch")
        return raw


class TrustRegistry(StrictModel):
    schema_version: Literal["vmec.governance-trust-registry.v1"]
    keys: list[TrustedKey] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> TrustRegistry:
        if len({key.key_id for key in self.keys}) != len(self.keys):
            raise ValueError("duplicate trusted key id")
        return self

    def approval_key(self, key_id: str, *, issued_at: datetime, now: datetime) -> TrustedKey:
        key = next((candidate for candidate in self.keys if candidate.key_id == key_id), None)
        if key is None or "APPROVAL_MANIFEST" not in key.capabilities:
            raise ValueError("approval key is not trusted for this capability")
        issued_at = issued_at.astimezone(UTC)
        now = now.astimezone(UTC)
        if issued_at < key.valid_from.astimezone(UTC) or (key.not_after and issued_at > key.not_after.astimezone(UTC)):
            raise ValueError("approval key was outside its validity window")
        if key.revoked_at is not None and key.revoked_at.astimezone(UTC) <= now:
            raise ValueError("approval key is revoked")
        return key


def verify_manifest(manifest: GovernanceManifest, registry: TrustRegistry, *, now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    issued = manifest.issued_at.astimezone(UTC)
    if issued > current:
        raise ValueError("manifest issued_at is in the future")
    if manifest.expires_at is not None and current >= manifest.expires_at.astimezone(UTC):
        raise ValueError("manifest has expired")
    if any(reviewer.reviewed_at.astimezone(UTC) > issued for reviewer in manifest.reviewers):
        raise ValueError("review decision cannot postdate manifest issuance")
    if manifest.owner_authorization.authorized_at.astimezone(UTC) > issued:
        raise ValueError("owner authorization cannot postdate manifest issuance")
    key = registry.approval_key(manifest.signature.key_id, issued_at=issued, now=current)
    try:
        signature = base64.b64decode(manifest.signature.value_base64, validate=True)
    except ValueError as exc:
        raise ValueError("manifest signature is not strict base64") from exc
    if len(signature) != 64:
        raise ValueError("Ed25519 signature must contain 64 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(key.raw_public_key()).verify(
            signature, signature_payload(manifest.unsigned_dict())
        )
    except InvalidSignature as exc:
        raise ValueError("manifest signature verification failed") from exc
    return digest(manifest.unsigned_dict())


def verify_evidence(manifest: GovernanceManifest, path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("evidence package must be a regular external file")
    artifact = strict_json_loads(path.read_text(encoding="utf-8"))
    stated = artifact.pop("package_digest", None)
    calculated = digest(artifact)
    if stated != calculated or manifest.evidence_package.package_digest != calculated:
        raise ValueError("evidence package digest mismatch")
    if artifact.get("schema_version") != manifest.evidence_package.schema_version:
        raise ValueError("evidence package schema mismatch")
    if artifact.get("included_row_hashes_digest") != manifest.release_scope.included_row_hashes_digest:
        raise ValueError("evidence row scope mismatch")
    if artifact.get("release_id") not in manifest.release_scope.release_ids:
        raise ValueError("evidence release scope mismatch")
    return calculated


def verify_receipt(receipt: dict[str, object], registry: TrustRegistry) -> str:
    required = {
        "schema_version",
        "promotion_id",
        "manifest_id",
        "manifest_digest",
        "scope_digest",
        "production_release_id",
        "production_logical_release_id",
        "accepted_rows",
        "gold_rows",
        "excluded_rows",
        "audit_digest",
        "committed_at",
        "signature",
    }
    if set(receipt) != required or receipt.get("schema_version") != "vmec.governance-promotion-receipt.v1":
        raise ValueError("receipt shape is invalid")
    signature = receipt.get("signature")
    if not isinstance(signature, dict):
        raise ValueError("receipt signature is missing")
    if set(signature) != {"algorithm", "key_id", "value_base64"} or signature.get("algorithm") != "Ed25519":
        raise ValueError("receipt signature envelope is invalid")
    key_id = signature.get("key_id")
    if not isinstance(key_id, str):
        raise ValueError("receipt key id is invalid")
    key = next((candidate for candidate in registry.keys if candidate.key_id == key_id), None)
    if key is None or "PROMOTION_RECEIPT" not in key.capabilities or key.revoked_at is not None:
        raise ValueError("receipt key is not currently trusted")
    try:
        committed_at = datetime.fromisoformat(str(receipt["committed_at"]).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise ValueError("receipt committed_at is invalid") from exc
    if committed_at < key.valid_from.astimezone(UTC) or (
        key.not_after and committed_at > key.not_after.astimezone(UTC)
    ):
        raise ValueError("receipt key was outside its validity window")
    for field in ("manifest_digest", "scope_digest", "audit_digest"):
        value = receipt[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"receipt {field} is invalid")
    try:
        raw_signature = base64.b64decode(str(signature.get("value_base64", "")), validate=True)
    except ValueError as exc:
        raise ValueError("receipt signature is not strict base64") from exc
    if len(raw_signature) != 64:
        raise ValueError("receipt Ed25519 signature must contain 64 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(key.raw_public_key()).verify(
            raw_signature, signature_payload(receipt, receipt=True)
        )
    except InvalidSignature as exc:
        raise ValueError("receipt signature verification failed") from exc
    return digest(receipt)
