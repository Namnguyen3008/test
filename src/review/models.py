from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.persistence.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ClinicalReviewItem(Base):
    __tablename__ = "clinical_review_items"
    __table_args__ = (
        UniqueConstraint("release_id", "origin_table", "origin_row_id", name="uq_clinical_review_origin"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    release_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    record_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    origin_table: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_row_id: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    safety_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING", index=True)
    claimed_by: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ClinicalReviewDecision(Base):
    __tablename__ = "clinical_review_decisions"
    __table_args__ = (UniqueConstraint("item_id", "reviewer_id", "item_version", name="uq_review_decision_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("clinical_review_items.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
