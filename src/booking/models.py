"""SQLAlchemy mappings for persistent scheduling and booking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from src.persistence import identity_models  # noqa: F401
from src.persistence.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    practitioner_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    specialty_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    facility_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    slot_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("slots.id"), nullable=False, index=True)
    proposed_slot_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("slots.id"), nullable=True, index=True
    )
    patient_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    patient_reconfirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    staff_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class SlotHold(Base):
    __tablename__ = "slot_holds"
    __table_args__ = (
        Index(
            "uq_slot_holds_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    slot_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("slots.id"), nullable=False, index=True)
    appointment_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("appointments.id"), nullable=False, index=True
    )
    patient_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AppointmentEvent(Base):
    __tablename__ = "appointment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("appointments.id"), nullable=False, index=True
    )
    actor_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    actor_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BookingOutbox(Base):
    __tablename__ = "booking_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aggregate_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
