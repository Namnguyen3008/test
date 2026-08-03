"""Atomic PostgreSQL governance promotion and signed receipt creation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .canonical import canonical_json, digest, signature_payload
from .manifest import GovernanceManifest, TrustRegistry, verify_evidence, verify_manifest

_BLOCKED_CONFLICT_STATUSES = {"CONFLICT", "REJECTED", "BLOCKED"}
_BLOCKED_CANONICAL_STATUSES = {"REJECTED", "BLOCKED"}
_BLOCKED_REVIEW_STATUSES = {"REJECTED", "CHANGES_REQUESTED", "BLOCKED"}


def _affected(result: Any) -> int:
    return int(getattr(result, "rowcount", -1))


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    record_id: str
    logical_release_id: str
    origin_table: str
    origin_row_id: str
    content_hash: str
    canonical_status: str
    review_status: str
    conflict_status: str
    source_ids: tuple[str, ...]
    safety_critical: bool = False
    gold_candidate_flag: bool = False
    normalized_text_hash: str = ""
    gold_reason: str = ""

    @property
    def gold_candidate(self) -> bool:
        return self.safety_critical or self.gold_candidate_flag


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    records: tuple[PromotionRecord, ...]
    registry_digest: str
    row_hashes_digest: str
    canonical_sources: int
    included_tables: tuple[str, ...]
    scope_digest: str


def scope_snapshot(records: list[PromotionRecord], *, canonical_sources: int | None = None) -> ScopeSnapshot:
    eligible = tuple(
        sorted(
            (
                record
                for record in records
                if record.conflict_status.upper() not in _BLOCKED_CONFLICT_STATUSES
                and record.canonical_status.upper() not in _BLOCKED_CANONICAL_STATUSES
                and record.review_status.upper() not in _BLOCKED_REVIEW_STATUSES
                and bool(record.source_ids)
            ),
            key=lambda item: (item.logical_release_id, item.origin_table, item.origin_row_id, item.record_id),
        )
    )
    registry_lines = sorted(
        f"{record.origin_table}\0{record.origin_row_id}\0{record.content_hash}" for record in eligible
    )
    row_lines = sorted(
        "\0".join(
            (
                record.logical_release_id,
                record.origin_table,
                record.origin_row_id,
                record.content_hash,
                record.normalized_text_hash,
                ",".join(record.source_ids),
                "1" if record.safety_critical else "0",
                "1" if record.gold_candidate_flag else "0",
                record.gold_reason,
            )
        )
        for record in eligible
    )
    sources = {source_id for record in eligible for source_id in record.source_ids}
    source_count = len(sources) if canonical_sources is None else canonical_sources
    tables = tuple(sorted({record.origin_table for record in eligible}))
    registry_digest = hashlib.sha256("\n".join(registry_lines).encode()).hexdigest()
    row_hashes_digest = hashlib.sha256("\n".join(row_lines).encode()).hexdigest()
    payload = {
        "release_ids": sorted({record.logical_release_id for record in eligible}),
        "registry_digest": registry_digest,
        "expected_rows": len(eligible),
        "canonical_sources": source_count,
        "included_tables": list(tables),
        "included_row_hashes_digest": row_hashes_digest,
    }
    return ScopeSnapshot(eligible, registry_digest, row_hashes_digest, source_count, tables, digest(payload))


def assert_manifest_scope(manifest: GovernanceManifest, snapshot: ScopeSnapshot) -> None:
    expected = manifest.release_scope
    actual = {
        "release_ids": sorted({record.logical_release_id for record in snapshot.records}),
        "registry_digest": snapshot.registry_digest,
        "expected_rows": len(snapshot.records),
        "canonical_sources": snapshot.canonical_sources,
        "included_tables": list(snapshot.included_tables),
        "included_row_hashes_digest": snapshot.row_hashes_digest,
    }
    if actual != expected.model_dump(mode="json"):
        raise ValueError("manifest scope does not match the locked persistent records")


def _load_receipt_key(path: Path) -> tuple[Ed25519PrivateKey, str]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("receipt signing key must be a regular external file")
    try:
        raw = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("receipt signing key must be strict base64") from exc
    if len(raw) != 32:
        raise ValueError("receipt signing key must contain 32 Ed25519 private bytes")
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    public = private_key.public_key().public_bytes_raw()
    return private_key, hashlib.sha256(public).hexdigest()


class GovernancePromotionRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    @staticmethod
    def _records(session: Session, release_ids: list[str]) -> list[PromotionRecord]:
        rows = session.execute(
            text(
                "SELECT kr.id::text,dr.logical_release_id,kr.origin_table,kr.origin_row_id,kr.content_hash,"
                "kr.canonical_status,coalesce(kr.review_status,''),coalesce(kr.conflict_status,''),"
                "kr.safety_critical,kr.gold_candidate,kr.normalized_text,kr.gold_reason,"
                "ARRAY(SELECT krs.source_id FROM knowledge_record_sources krs "
                "WHERE krs.record_id=kr.id ORDER BY krs.source_id) "
                "FROM knowledge_records kr JOIN dataset_releases dr ON dr.id=kr.release_id "
                "WHERE dr.logical_release_id = ANY(:release_ids) AND dr.status='completed' "
                "FOR UPDATE OF kr"
            ),
            {"release_ids": release_ids},
        )
        return [
            PromotionRecord(
                record_id=str(row[0]),
                logical_release_id=str(row[1]),
                origin_table=str(row[2]),
                origin_row_id=str(row[3]),
                content_hash=str(row[4]),
                canonical_status=str(row[5]),
                review_status=str(row[6]),
                conflict_status=str(row[7]),
                safety_critical=bool(row[8]),
                gold_candidate_flag=bool(row[9]),
                normalized_text_hash=hashlib.sha256(str(row[10]).encode()).hexdigest(),
                gold_reason=str(row[11]),
                source_ids=tuple(str(item) for item in row[12]),
            )
            for row in rows
        ]

    def promote(
        self,
        manifest: GovernanceManifest,
        registry: TrustRegistry,
        *,
        receipt_key_path: Path,
        evidence_path: Path,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if os.environ.get("VMEC_ALLOW_GOVERNANCE_PROMOTION") != "true":
            raise RuntimeError("governance promotion gate is disabled")
        manifest_digest = verify_manifest(manifest, registry, now=now)
        verify_evidence(manifest, evidence_path)
        private_key, receipt_key_id = _load_receipt_key(receipt_key_path)
        current = (now or datetime.now(UTC)).astimezone(UTC)
        receipt_trust = next((key for key in registry.keys if key.key_id == receipt_key_id), None)
        if (
            receipt_trust is None
            or "PROMOTION_RECEIPT" not in receipt_trust.capabilities
            or receipt_trust.revoked_at is not None
            or current < receipt_trust.valid_from.astimezone(UTC)
            or (receipt_trust.not_after is not None and current > receipt_trust.not_after.astimezone(UTC))
        ):
            raise ValueError("receipt signing key is not currently trusted for receipt capability")
        receipt_trust.raw_public_key()
        with self._factory() as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext('vmec-governance-promotion'))"))
            prior = session.execute(
                text(
                    "SELECT manifest_digest,receipt FROM governance_manifests gm "
                    "LEFT JOIN governance_promotions gp ON gp.manifest_id=gm.manifest_id "
                    "WHERE gm.manifest_id=:manifest_id"
                ),
                {"manifest_id": manifest.manifest_id},
            ).one_or_none()
            if prior is not None:
                if str(prior[0]) != manifest_digest:
                    raise RuntimeError("manifest id replayed with different bytes")
                if prior[1] is None:
                    raise RuntimeError("prior manifest verification did not complete promotion")
                return dict(prior[1])

            records = self._records(session, manifest.release_scope.release_ids)
            source_count = session.execute(
                text(
                    "SELECT count(DISTINCT drs.source_id) FROM dataset_release_sources drs "
                    "JOIN dataset_releases dr ON dr.id=drs.release_id "
                    "WHERE dr.logical_release_id = ANY(:release_ids)"
                ),
                {"release_ids": manifest.release_scope.release_ids},
            ).scalar_one()
            snapshot = scope_snapshot(records, canonical_sources=int(source_count))
            assert_manifest_scope(manifest, snapshot)
            duplicate_scope = session.execute(
                text("SELECT manifest_id FROM governance_manifests WHERE scope_digest=:scope_digest"),
                {"scope_digest": snapshot.scope_digest},
            ).scalar_one_or_none()
            if duplicate_scope is not None:
                raise RuntimeError("scope was already bound to another manifest")
            session.execute(
                text(
                    "INSERT INTO governance_manifests(manifest_id,manifest_digest,scope_digest,key_id,"
                    "release_scope,evidence_digest,status,verified_at) VALUES(:manifest_id,:manifest_digest,"
                    ":scope_digest,:key_id,cast(:scope AS jsonb),:evidence,'VERIFIED',:verified_at)"
                ),
                {
                    "manifest_id": manifest.manifest_id,
                    "manifest_digest": manifest_digest,
                    "scope_digest": snapshot.scope_digest,
                    "key_id": manifest.signature.key_id,
                    "scope": json.dumps(manifest.release_scope.model_dump(mode="json"), sort_keys=True),
                    "evidence": manifest.evidence_package.package_digest,
                    "verified_at": current,
                },
            )
            promotion_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-promotion:{manifest_digest}"))
            production_release_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-production-release:{manifest_digest}"))
            production_logical_id = "vmec-production-v1"
            source_hashes = json.dumps(
                {
                    "governance_manifest_digest": manifest_digest,
                    "source_release_ids": manifest.release_scope.release_ids,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            production_release = session.execute(
                text(
                    "INSERT INTO dataset_releases(id,logical_release_id,mode,source_hashes,status,registry_digest,"
                    "imported_records,updated_at) VALUES(:id,:logical,'production',cast(:source_hashes AS jsonb),"
                    "'importing',:registry,0,now()) ON CONFLICT(logical_release_id) DO NOTHING"
                ),
                {
                    "id": production_release_id,
                    "logical": production_logical_id,
                    "source_hashes": source_hashes,
                    "registry": snapshot.registry_digest,
                },
            )
            if _affected(production_release) != 1:
                raise RuntimeError("production release name is already occupied; signed supersession is required")
            session.execute(
                text(
                    "INSERT INTO dataset_release_sources(release_id,source_id) "
                    "SELECT :production_release_id,drs.source_id FROM dataset_release_sources drs "
                    "JOIN dataset_releases dr ON dr.id=drs.release_id "
                    "WHERE dr.logical_release_id = ANY(:release_ids) ON CONFLICT DO NOTHING"
                ),
                {
                    "production_release_id": production_release_id,
                    "release_ids": manifest.release_scope.release_ids,
                },
            )
            audit_lines: list[str] = []
            accepted = 0
            gold = 0
            for record in snapshot.records:
                policy_gold_candidate = (
                    record.safety_critical
                    if manifest.policy.gold_policy == "SAFETY_CRITICAL_TWO_REVIEWERS"
                    else record.gold_candidate
                )
                new_status = (
                    "GOLD"
                    if manifest.promotion.gold_mode == "PROMOTE_POLICY_GOLD_ONLY" and policy_gold_candidate
                    else "ACCEPTED"
                )
                production_record_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"vmec-production-record:{manifest_digest}:{record.record_id}")
                )
                result = session.execute(
                    text(
                        "INSERT INTO knowledge_records(id,release_id,origin_table,origin_row_id,mode,canonical_status,"
                        "review_status,conflict_status,safety_critical,gold_candidate,gold_reason,normalized_text,"
                        "content_hash,metadata) SELECT :production_record_id,:production_release_id,origin_table,"
                        "origin_row_id,'production',:canonical_status,'CLINICALLY_APPROVED',conflict_status,"
                        "safety_critical,gold_candidate,gold_reason,normalized_text,content_hash,metadata "
                        "FROM knowledge_records WHERE id=:source_record_id AND content_hash=:content_hash"
                    ),
                    {
                        "production_record_id": production_record_id,
                        "production_release_id": production_release_id,
                        "canonical_status": new_status,
                        "source_record_id": record.record_id,
                        "content_hash": record.content_hash,
                    },
                )
                if _affected(result) != 1:
                    raise RuntimeError("locked governance row changed during promotion")
                session.execute(
                    text(
                        "INSERT INTO knowledge_record_sources(record_id,source_id,evidence_locator) "
                        "SELECT :production_record_id,source_id,evidence_locator FROM knowledge_record_sources "
                        "WHERE record_id=:source_record_id"
                    ),
                    {"production_record_id": production_record_id, "source_record_id": record.record_id},
                )
                chunks = session.execute(
                    text(
                        "SELECT ordinal,normalized_text,content_hash,token_count FROM knowledge_chunks "
                        "WHERE record_id=:source_record_id ORDER BY ordinal"
                    ),
                    {"source_record_id": record.record_id},
                )
                for chunk in chunks:
                    production_chunk_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"vmec-production-chunk:{manifest_digest}:{record.record_id}:{int(chunk[0])}",
                        )
                    )
                    session.execute(
                        text(
                            "INSERT INTO knowledge_chunks(id,record_id,ordinal,normalized_text,content_hash,token_count) "
                            "VALUES(:id,:record_id,:ordinal,:text,:content_hash,:token_count)"
                        ),
                        {
                            "id": production_chunk_id,
                            "record_id": production_record_id,
                            "ordinal": int(chunk[0]),
                            "text": str(chunk[1]),
                            "content_hash": str(chunk[2]),
                            "token_count": int(chunk[3]),
                        },
                    )
                source_digest = hashlib.sha256("\n".join(record.source_ids).encode()).hexdigest()
                session.execute(
                    text(
                        "INSERT INTO governance_row_promotions(promotion_id,manifest_id,source_record_id,record_id,content_hash,"
                        "source_digest,before_canonical_status,before_review_status,after_canonical_status,"
                        "after_review_status,created_at) VALUES(:promotion_id,:manifest_id,:source_record_id,:record_id,"
                        ":content_hash,:source_digest,:before_canonical,:before_review,:after_canonical,"
                        "'CLINICALLY_APPROVED',:created_at)"
                    ),
                    {
                        "promotion_id": promotion_id,
                        "manifest_id": manifest.manifest_id,
                        "source_record_id": record.record_id,
                        "record_id": production_record_id,
                        "content_hash": record.content_hash,
                        "source_digest": source_digest,
                        "before_canonical": record.canonical_status,
                        "before_review": record.review_status,
                        "after_canonical": new_status,
                        "created_at": current,
                    },
                )
                audit_lines.append(
                    f"{record.record_id}\0{production_record_id}\0{record.content_hash}\0{source_digest}\0{new_status}"
                )
                if new_status == "GOLD":
                    gold += 1
                else:
                    accepted += 1
            audit_digest = hashlib.sha256("\n".join(sorted(audit_lines)).encode()).hexdigest()
            session.execute(
                text(
                    "UPDATE dataset_releases SET status='completed',imported_records=:count,updated_at=now() "
                    "WHERE id=:release_id"
                ),
                {"count": accepted + gold, "release_id": production_release_id},
            )
            receipt: dict[str, Any] = {
                "schema_version": "vmec.governance-promotion-receipt.v1",
                "promotion_id": promotion_id,
                "manifest_id": manifest.manifest_id,
                "manifest_digest": manifest_digest,
                "scope_digest": snapshot.scope_digest,
                "production_release_id": production_release_id,
                "production_logical_release_id": production_logical_id,
                "accepted_rows": accepted,
                "gold_rows": gold,
                "excluded_rows": len(records) - len(snapshot.records),
                "audit_digest": audit_digest,
                "committed_at": current.isoformat().replace("+00:00", "Z"),
                "signature": {"algorithm": "Ed25519", "key_id": receipt_key_id, "value_base64": ""},
            }
            receipt["signature"]["value_base64"] = base64.b64encode(
                private_key.sign(signature_payload(receipt, receipt=True))
            ).decode("ascii")
            receipt_digest = digest(receipt)
            session.execute(
                text(
                    "INSERT INTO governance_promotions(id,manifest_id,receipt,receipt_digest,receipt_key_id,"
                    "created_at) VALUES(:id,:manifest_id,cast(:receipt AS jsonb),:receipt_digest,:key_id,:created_at)"
                ),
                {
                    "id": promotion_id,
                    "manifest_id": manifest.manifest_id,
                    "receipt": canonical_json(receipt).decode(),
                    "receipt_digest": receipt_digest,
                    "key_id": receipt_key_id,
                    "created_at": current,
                },
            )
            session.execute(
                text(
                    "UPDATE governance_manifests SET status='PROMOTED',promoted_at=:promoted_at "
                    "WHERE manifest_id=:manifest_id"
                ),
                {"promoted_at": current, "manifest_id": manifest.manifest_id},
            )
            return receipt
