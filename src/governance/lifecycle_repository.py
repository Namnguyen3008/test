"""Atomic persistence for signed supersession and emergency revocation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .canonical import canonical_json, digest
from .lifecycle import (
    GovernanceSupersession,
    LifecycleArtifact,
    ReleaseBinding,
    verify_lifecycle_artifact,
)
from .manifest import TrustRegistry


class GovernanceLifecycleRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    @staticmethod
    def _binding(session: Session, manifest_id: str) -> ReleaseBinding:
        row = session.execute(
            text(
                "SELECT gm.manifest_id,gm.manifest_digest,gp.receipt->>'production_release_id',"
                "gp.receipt_digest,gm.scope_digest FROM governance_manifests gm "
                "JOIN governance_promotions gp ON gp.manifest_id=gm.manifest_id "
                "JOIN dataset_releases dr ON dr.id::text=gp.receipt->>'production_release_id' "
                "WHERE gm.manifest_id=:manifest_id AND dr.status='completed' AND gm.status='PROMOTED'"
            ),
            {"manifest_id": manifest_id},
        ).one_or_none()
        if row is None:
            raise RuntimeError("bound manifest is not a completed promoted release")
        return ReleaseBinding(
            manifest_id=str(row[0]), manifest_digest=str(row[1]), production_release_id=str(row[2]),
            promotion_receipt_digest=str(row[3]), clinical_scope_digest=str(row[4])
        )

    def apply(
        self, artifact: LifecycleArtifact, registry: TrustRegistry, *, now: datetime | None = None
    ) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        artifact_digest = verify_lifecycle_artifact(artifact, registry, now=current)
        registry_digest = digest(registry.model_dump(mode="json"))
        kind = "SUPERSESSION" if isinstance(artifact, GovernanceSupersession) else "REVOCATION"
        with self._factory() as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext('vmec-governance-lifecycle'))"))
            prior = session.execute(
                text("SELECT artifact_digest FROM governance_lifecycle_artifacts WHERE artifact_id=:id"),
                {"id": artifact.artifact_id},
            ).scalar_one_or_none()
            if prior is not None:
                if str(prior) != artifact_digest:
                    raise RuntimeError("lifecycle artifact id replayed with different bytes")
                transition = session.execute(
                    text("SELECT row_to_json(t) FROM governance_release_transitions t WHERE artifact_id=:id"),
                    {"id": artifact.artifact_id},
                ).scalar_one()
                return dict(transition)
            if session.execute(
                text("SELECT 1 FROM governance_lifecycle_artifacts WHERE artifact_digest=:digest"),
                {"digest": artifact_digest},
            ).scalar_one_or_none():
                raise RuntimeError("lifecycle artifact bytes were replayed under another id")
            route = session.execute(
                text("SELECT state,generation,active_release_id::text,active_manifest_id FROM governance_release_routes WHERE route_name=:route FOR UPDATE"),
                {"route": artifact.route_name},
            ).one_or_none()
            if route is None:
                raise RuntimeError("governed production route does not exist")
            if int(route[1]) != artifact.expected_generation:
                raise RuntimeError("stale lifecycle artifact generation")
            if str(route[0]) not in {"ACTIVE", "REVOKED"}:
                raise RuntimeError("invalid route state")
            previous = artifact.previous if isinstance(artifact, GovernanceSupersession) else artifact.target
            if str(route[0]) != "ACTIVE" or str(route[2]) != previous.production_release_id or str(route[3]) != previous.manifest_id:
                raise RuntimeError("lifecycle previous binding is not the active route")
            if self._binding(session, previous.manifest_id) != previous:
                raise RuntimeError("lifecycle previous binding does not match persistent promotion")
            replacement: ReleaseBinding | None = None
            if isinstance(artifact, GovernanceSupersession):
                replacement = self._binding(session, artifact.replacement.manifest_id)
                if replacement != artifact.replacement:
                    raise RuntimeError("replacement binding does not match persistent promotion")
            session.execute(
                text("INSERT INTO governance_lifecycle_artifacts(artifact_id,artifact_digest,kind,key_id,trust_registry_digest,route_name,expected_generation,artifact,applied_at) VALUES(:id,:digest,:kind,:key,:registry,:route,:generation,cast(:artifact AS jsonb),:applied)"),
                {"id": artifact.artifact_id, "digest": artifact_digest, "kind": kind,
                 "key": artifact.signature.key_id, "registry": registry_digest, "route": artifact.route_name,
                 "generation": artifact.expected_generation,
                 "artifact": canonical_json(artifact.model_dump(mode="json")).decode(), "applied": current},
            )
            new_state = "ACTIVE" if replacement else "REVOKED"
            new_release = replacement.production_release_id if replacement else None
            new_manifest = replacement.manifest_id if replacement else None
            session.execute(
                text("UPDATE governance_release_routes SET state=:state,generation=generation+1,active_release_id=:release,active_manifest_id=:manifest,last_artifact_id=:artifact,transitioned_at=:at WHERE route_name=:route"),
                {"state": new_state, "release": new_release, "manifest": new_manifest,
                 "artifact": artifact.artifact_id, "at": current, "route": artifact.route_name},
            )
            session.execute(
                text("UPDATE governance_manifests SET status=:status WHERE manifest_id=:manifest"),
                {"status": "SUPERSEDED" if replacement else "REVOKED", "manifest": previous.manifest_id},
            )
            transition = {
                "artifact_id": artifact.artifact_id, "route_name": artifact.route_name,
                "previous_generation": artifact.expected_generation, "new_generation": artifact.expected_generation + 1,
                "previous_state": "ACTIVE", "new_state": new_state,
                "previous_release_id": previous.production_release_id, "new_release_id": new_release,
                "previous_manifest_id": previous.manifest_id, "new_manifest_id": new_manifest,
                "created_at": current,
            }
            session.execute(
                text("INSERT INTO governance_release_transitions(artifact_id,route_name,previous_generation,new_generation,previous_state,new_state,previous_release_id,new_release_id,previous_manifest_id,new_manifest_id,created_at) VALUES(:artifact_id,:route_name,:previous_generation,:new_generation,:previous_state,:new_state,:previous_release_id,:new_release_id,:previous_manifest_id,:new_manifest_id,:created_at)"),
                transition,
            )
            return {key: (value.isoformat() if isinstance(value, datetime) else value) for key, value in transition.items()}
