"""Signed, replay-safe governance release lifecycle artifacts."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, field_validator, model_validator

from .canonical import digest, signature_payload
from .manifest import HexDigest, OwnerAuthorization, Reviewer, Signature, StrictModel, TrustRegistry


class ReleaseBinding(StrictModel):
    manifest_id: str = Field(min_length=8)
    manifest_digest: HexDigest
    production_release_id: str = Field(min_length=8)
    promotion_receipt_digest: HexDigest
    clinical_scope_digest: HexDigest


class LifecycleBase(StrictModel):
    artifact_id: str = Field(min_length=8)
    project_id: Literal["VMEC-01"]
    route_name: Literal["vmec-production-v1"]
    expected_generation: int = Field(ge=1)
    reason: str = Field(min_length=8)
    effective_at: datetime
    owner_authorization: OwnerAuthorization
    issued_at: datetime
    expires_at: datetime | None = None
    signature: Signature

    @field_validator("artifact_id", "reason")
    @classmethod
    def no_placeholder(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(token in normalized.upper() for token in ("FILL_", "TBD", "TODO", "PLACEHOLDER")):
            raise ValueError("unresolved placeholder is forbidden")
        return normalized

    @model_validator(mode="after")
    def coherent_times(self) -> LifecycleBase:
        values = [self.effective_at, self.owner_authorization.authorized_at, self.issued_at]
        if any(value.tzinfo is None or value.utcoffset() is None for value in values):
            raise ValueError("lifecycle timestamps must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("lifecycle timestamps must be timezone-aware")
            if self.expires_at <= self.issued_at:
                raise ValueError("expires_at must follow issued_at")
        if self.owner_authorization.authorized_at > self.issued_at:
            raise ValueError("owner authorization cannot postdate issuance")
        return self


class GovernanceSupersession(LifecycleBase):
    schema_version: Literal["vmec.governance-supersession.v1"]
    previous: ReleaseBinding
    replacement: ReleaseBinding
    clinical_scope_changed: bool
    clinical_attestations: list[Reviewer] = Field(default_factory=list)

    @model_validator(mode="after")
    def independent_clinical_scope(self) -> GovernanceSupersession:
        actual_change = self.previous.clinical_scope_digest != self.replacement.clinical_scope_digest
        if self.clinical_scope_changed != actual_change:
            raise ValueError("clinical_scope_changed does not match bound scope digests")
        if actual_change:
            reviewers = {item.reviewer_id.casefold() for item in self.clinical_attestations}
            if len(reviewers) < 2:
                raise ValueError("clinical scope change requires two independent reviewers")
            if self.owner_authorization.owner_id.casefold() in reviewers:
                raise ValueError("clinical reviewers must be independent from the owner")
            if any(item.reviewed_at > self.issued_at for item in self.clinical_attestations):
                raise ValueError("clinical attestation cannot postdate issuance")
        elif self.clinical_attestations:
            raise ValueError("unchanged clinical scope must not carry unrelated attestations")
        if self.previous == self.replacement:
            raise ValueError("replacement must differ from previous release")
        return self


class GovernanceRevocation(LifecycleBase):
    schema_version: Literal["vmec.governance-revocation.v1"]
    target: ReleaseBinding
    emergency_withdrawal: Literal[True]


LifecycleArtifact = GovernanceSupersession | GovernanceRevocation


def verify_lifecycle_artifact(
    artifact: LifecycleArtifact, registry: TrustRegistry, *, now: datetime | None = None
) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    issued = artifact.issued_at.astimezone(UTC)
    if issued > current:
        raise ValueError("lifecycle artifact issued_at is in the future")
    if artifact.effective_at.astimezone(UTC) > current:
        raise ValueError("lifecycle artifact is not effective yet")
    if artifact.expires_at is not None and current >= artifact.expires_at.astimezone(UTC):
        raise ValueError("lifecycle artifact has expired")
    capability = (
        "GOVERNANCE_SUPERSESSION"
        if isinstance(artifact, GovernanceSupersession)
        else "GOVERNANCE_REVOCATION"
    )
    domain = "supersession" if isinstance(artifact, GovernanceSupersession) else "revocation"
    key = registry.capability_key(artifact.signature.key_id, capability, issued_at=issued, now=current)
    try:
        signature = base64.b64decode(artifact.signature.value_base64, validate=True)
    except ValueError as exc:
        raise ValueError("lifecycle signature is not strict base64") from exc
    if len(signature) != 64:
        raise ValueError("Ed25519 signature must contain 64 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(key.raw_public_key()).verify(
            signature, signature_payload(artifact.model_dump(mode="json"), domain=domain)
        )
    except InvalidSignature as exc:
        raise ValueError("lifecycle signature verification failed") from exc
    return digest(artifact.model_dump(mode="json"))
