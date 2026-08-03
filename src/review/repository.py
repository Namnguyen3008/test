"""Transactional human review state machine; no method promotes production data."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from src.persistence.identity_models import AuditEventRecord
from src.review.models import ClinicalReviewDecision, ClinicalReviewItem


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReviewError(RuntimeError):
    pass


class ReviewConflictError(ReviewError):
    pass


class ReviewNotFoundError(ReviewError):
    pass


class ReviewForbiddenError(ReviewError):
    pass


class ReviewRepository:
    def __init__(self, session: Session, *, clock: Callable[[], datetime] = _now) -> None:
        self.session = session
        self.clock = clock

    def create_item(
        self,
        *,
        release_id: str,
        origin_table: str,
        origin_row_id: str,
        content_hash: str,
        evidence_summary: str,
        source_ids: list[str],
        safety_critical: bool,
        actor_id: str,
        record_id: str | None = None,
    ) -> ClinicalReviewItem:
        with self.session.begin():
            return self._create_item(
                release_id=release_id,
                origin_table=origin_table,
                origin_row_id=origin_row_id,
                content_hash=content_hash,
                evidence_summary=evidence_summary,
                source_ids=source_ids,
                safety_critical=safety_critical,
                actor_id=actor_id,
                record_id=record_id,
            )

    def import_package(
        self,
        items: Iterable[Mapping[str, object]],
        *,
        actor_id: str,
    ) -> list[ClinicalReviewItem]:
        """Import one validated package atomically; a conflict rolls back every item."""
        with self.session.begin():
            imported: list[ClinicalReviewItem] = []
            for item in items:
                raw_sources = item["source_ids"]
                if not isinstance(raw_sources, (list, tuple)):
                    raise ReviewConflictError("Review item sources must be a list")
                imported.append(
                    self._create_item(
                        release_id=str(item["release_id"]),
                        origin_table=str(item["origin_table"]),
                        origin_row_id=str(item["origin_row_id"]),
                        content_hash=str(item["content_hash"]),
                        evidence_summary=str(item["evidence_summary"]),
                        source_ids=[str(value) for value in raw_sources],
                        safety_critical=bool(item["safety_critical"]),
                        actor_id=actor_id,
                        record_id=str(item["record_id"]) if item.get("record_id") else None,
                    )
                )
            return imported

    def _create_item(
        self,
        *,
        release_id: str,
        origin_table: str,
        origin_row_id: str,
        content_hash: str,
        evidence_summary: str,
        source_ids: list[str],
        safety_critical: bool,
        actor_id: str,
        record_id: str | None,
    ) -> ClinicalReviewItem:
        if len(content_hash) != 64 or not evidence_summary.strip() or not source_ids:
            raise ReviewConflictError("Review item requires content hash, evidence and canonical sources")
        normalized_evidence = evidence_summary.strip()
        normalized_sources = list(dict.fromkeys(source_ids))
        existing = self.session.scalar(
            select(ClinicalReviewItem).where(
                ClinicalReviewItem.release_id == release_id,
                ClinicalReviewItem.origin_table == origin_table,
                ClinicalReviewItem.origin_row_id == origin_row_id,
            )
        )
        if existing:
            immutable = (
                existing.content_hash,
                existing.record_id,
                existing.evidence_summary,
                existing.source_ids,
                existing.safety_critical,
            )
            supplied = (content_hash, record_id, normalized_evidence, normalized_sources, safety_critical)
            if immutable != supplied:
                raise ReviewConflictError("Review origin was replayed with different immutable evidence")
            return existing
        now = self.clock()
        item = ClinicalReviewItem(
            id=str(uuid.uuid4()),
            release_id=release_id,
            record_id=record_id,
            origin_table=origin_table,
            origin_row_id=origin_row_id,
            content_hash=content_hash,
            evidence_summary=normalized_evidence,
            source_ids=normalized_sources,
            safety_critical=safety_critical,
            required_reviews=2 if safety_critical else 1,
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self._audit(actor_id, "review.item_create", item.id, "success", {"safety_critical": safety_critical})
        return item

    def queue(self) -> list[ClinicalReviewItem]:
        return list(
            self.session.scalars(
                select(ClinicalReviewItem).order_by(
                    case(
                        (ClinicalReviewItem.status == "ADJUDICATION_REQUIRED", 0),
                        (ClinicalReviewItem.safety_critical.is_(True), 1),
                        else_=2,
                    ),
                    ClinicalReviewItem.updated_at,
                    ClinicalReviewItem.id,
                )
            )
        )

    def claim(
        self,
        *,
        item_id: str,
        reviewer_id: str,
        expected_version: int,
        ttl_seconds: int = 900,
    ) -> ClinicalReviewItem:
        with self.session.begin():
            item = self._item(item_id, lock=True)
            self._expect_version(item, expected_version)
            now = self.clock()
            active_claim = item.claimed_by and item.claim_expires_at and _as_utc(item.claim_expires_at) > _as_utc(now)
            if active_claim and item.claimed_by != reviewer_id:
                raise ReviewConflictError("Review item is claimed by another reviewer")
            if item.status in {"APPROVED", "REJECTED"}:
                raise ReviewConflictError("Terminal review item cannot be claimed")
            if item.status == "ADJUDICATION_REQUIRED" and self._has_approved(item.id, reviewer_id):
                raise ReviewForbiddenError("Safety-critical second review requires a different reviewer")
            item.claimed_by = reviewer_id
            item.claim_expires_at = now + timedelta(seconds=ttl_seconds)
            item.status = "CLAIMED"
            item.version += 1
            item.updated_at = now
            self._audit(reviewer_id, "review.claim", item.id, "success", {"version": item.version})
            return item

    def release(self, *, item_id: str, reviewer_id: str, expected_version: int) -> ClinicalReviewItem:
        with self.session.begin():
            item = self._item(item_id, lock=True)
            self._expect_version(item, expected_version)
            if item.claimed_by != reviewer_id:
                raise ReviewForbiddenError("Only the claiming reviewer can release this item")
            item.claimed_by = None
            item.claim_expires_at = None
            item.status = "ADJUDICATION_REQUIRED" if self._approval_count(item.id) else "PENDING"
            item.version += 1
            item.updated_at = self.clock()
            self._audit(reviewer_id, "review.release", item.id, "success", {"version": item.version})
            return item

    def decide(
        self,
        *,
        item_id: str,
        reviewer_id: str,
        expected_version: int,
        decision: str,
        rationale: str,
    ) -> ClinicalReviewItem:
        normalized_decision = decision.upper()
        if normalized_decision not in {"APPROVE", "REJECT", "REQUEST_CHANGES"}:
            raise ReviewConflictError("Unsupported review decision")
        if len(rationale.strip()) < 20:
            raise ReviewConflictError("A substantive review rationale is required")
        with self.session.begin():
            item = self._item(item_id, lock=True)
            self._expect_version(item, expected_version)
            now = self.clock()
            if item.claimed_by != reviewer_id or not item.claim_expires_at:
                raise ReviewForbiddenError("Reviewer must hold the item claim")
            if _as_utc(item.claim_expires_at) <= _as_utc(now):
                raise ReviewConflictError("Review claim has expired")
            if normalized_decision == "APPROVE" and self._has_approved(item.id, reviewer_id):
                raise ReviewForbiddenError("The same reviewer cannot satisfy two approval rounds")
            self.session.add(
                ClinicalReviewDecision(
                    item_id=item.id,
                    reviewer_id=reviewer_id,
                    decision=normalized_decision,
                    rationale=rationale.strip(),
                    item_version=item.version,
                    created_at=now,
                )
            )
            self.session.flush()
            if normalized_decision == "APPROVE":
                item.status = (
                    "APPROVED" if self._approval_count(item.id) >= item.required_reviews else "ADJUDICATION_REQUIRED"
                )
            elif normalized_decision == "REJECT":
                item.status = "REJECTED"
            else:
                item.status = "CHANGES_REQUESTED"
            item.claimed_by = None
            item.claim_expires_at = None
            item.version += 1
            item.updated_at = now
            self._audit(
                reviewer_id,
                f"review.{normalized_decision.lower()}",
                item.id,
                "success",
                {"version": item.version, "status": item.status},
            )
            return item

    def promotion_report(self, release_id: str) -> dict[str, object]:
        items = list(
            self.session.scalars(select(ClinicalReviewItem).where(ClinicalReviewItem.release_id == release_id))
        )
        counts = Counter(item.status for item in items)
        ready = bool(items) and counts["APPROVED"] == len(items)
        payload: dict[str, object] = {
            "release_id": release_id,
            "item_count": len(items),
            "status_counts": dict(sorted(counts.items())),
            "safety_critical_count": sum(item.safety_critical for item in items),
            "all_sources_mapped": all(bool(item.source_ids) for item in items),
            "status": "ELIGIBLE_FOR_GOVERNANCE_REVIEW" if ready else "BLOCKED",
            "production_approved": False,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload["report_hash"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def safe_export(self, release_id: str) -> dict[str, object]:
        items = list(
            self.session.scalars(
                select(ClinicalReviewItem)
                .where(ClinicalReviewItem.release_id == release_id)
                .order_by(ClinicalReviewItem.id)
            )
        )
        decisions = (
            list(
                self.session.scalars(
                    select(ClinicalReviewDecision)
                    .where(ClinicalReviewDecision.item_id.in_([item.id for item in items]))
                    .order_by(
                        ClinicalReviewDecision.item_id, ClinicalReviewDecision.created_at, ClinicalReviewDecision.id
                    )
                )
            )
            if items
            else []
        )
        payload: dict[str, object] = {
            "schema_version": "vmec.review-evidence.v1",
            "release_id": release_id,
            "items": [
                {
                    "id": item.id,
                    "origin_table": item.origin_table,
                    "origin_row_id": item.origin_row_id,
                    "content_hash": item.content_hash,
                    "source_ids": item.source_ids,
                    "safety_critical": item.safety_critical,
                    "required_reviews": item.required_reviews,
                    "status": item.status,
                    "version": item.version,
                }
                for item in items
            ],
            "decisions": [
                {
                    "item_id": value.item_id,
                    "reviewer_id": value.reviewer_id,
                    "decision": value.decision,
                    "rationale_hash": hashlib.sha256(value.rationale.encode()).hexdigest(),
                    "item_version": value.item_version,
                    "created_at": value.created_at.isoformat(),
                }
                for value in decisions
            ],
            "contains_evidence_text": False,
            "production_approved": False,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload["package_digest"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def _item(self, item_id: str, *, lock: bool) -> ClinicalReviewItem:
        query = select(ClinicalReviewItem).where(ClinicalReviewItem.id == item_id)
        if lock:
            query = query.with_for_update()
        item = self.session.scalar(query)
        if item is None:
            raise ReviewNotFoundError("Review item was not found")
        return item

    @staticmethod
    def _expect_version(item: ClinicalReviewItem, expected_version: int) -> None:
        if item.version != expected_version:
            raise ReviewConflictError("Review item version changed; reload before retrying")

    def _approval_count(self, item_id: str) -> int:
        return len(
            set(
                self.session.scalars(
                    select(ClinicalReviewDecision.reviewer_id).where(
                        ClinicalReviewDecision.item_id == item_id,
                        ClinicalReviewDecision.decision == "APPROVE",
                    )
                )
            )
        )

    def _has_approved(self, item_id: str, reviewer_id: str) -> bool:
        return (
            self.session.scalar(
                select(ClinicalReviewDecision.id).where(
                    ClinicalReviewDecision.item_id == item_id,
                    ClinicalReviewDecision.reviewer_id == reviewer_id,
                    ClinicalReviewDecision.decision == "APPROVE",
                )
            )
            is not None
        )

    def _audit(
        self,
        actor_id: str,
        action: str,
        target_id: str,
        outcome: str,
        metadata: dict[str, object],
    ) -> None:
        self.session.add(
            AuditEventRecord(
                actor_id=actor_id,
                action=action,
                target_type="clinical_review_item",
                target_id=target_id,
                outcome=outcome,
                safe_metadata=metadata,
            )
        )
