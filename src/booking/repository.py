"""Transactional SQL booking repository.

Every mutation locks the affected appointment/slot rows, stores an append-only
event and outbox row in the same transaction, and is replay-safe by actor-scoped
idempotency key.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.booking.models import (
    Appointment,
    AppointmentEvent,
    BookingOutbox,
    IdempotencyRecord,
    Slot,
    SlotHold,
)


class BookingError(RuntimeError):
    """Base error safe to translate to a structured HTTP response."""


class BookingConflictError(BookingError):
    pass


class BookingNotFoundError(BookingError):
    pass


class BookingForbiddenError(BookingError):
    pass


class BookingInvalidTransitionError(BookingError):
    pass


ACTIVE_APPOINTMENT_STATES = {
    "HELD",
    "PATIENT_CONFIRMED",
    "PENDING_STAFF_APPROVAL",
    "CONFIRMED",
    "RESCHEDULE_PROPOSED",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def appointment_payload(value: Appointment) -> dict[str, object]:
    return {
        "id": value.id,
        "slot_id": value.slot_id,
        "proposed_slot_id": value.proposed_slot_id,
        "patient_id": value.patient_id,
        "status": value.status,
        "hold_expires_at": value.hold_expires_at.isoformat() if value.hold_expires_at else None,
        "patient_confirmed_at": value.patient_confirmed_at.isoformat() if value.patient_confirmed_at else None,
        "patient_reconfirmed_at": value.patient_reconfirmed_at.isoformat() if value.patient_reconfirmed_at else None,
        "staff_approved_at": value.staff_approved_at.isoformat() if value.staff_approved_at else None,
        "version": value.version,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
    }


class BookingRepository:
    def __init__(self, session: Session, *, clock: Callable[[], datetime] = _now) -> None:
        self.session = session
        self.clock = clock

    def availability(
        self,
        *,
        starts_after: datetime,
        ends_before: datetime,
        specialty_id: str | None = None,
        facility_id: str | None = None,
    ) -> list[Slot]:
        self.expire_due()
        active = select(SlotHold.slot_id).where(SlotHold.released_at.is_(None))
        query: Select[tuple[Slot]] = select(Slot).where(
            Slot.enabled.is_(True),
            Slot.starts_at >= starts_after,
            Slot.ends_at <= ends_before,
            Slot.id.not_in(active),
        )
        if specialty_id:
            query = query.where(Slot.specialty_id == specialty_id)
        if facility_id:
            query = query.where(Slot.facility_id == facility_id)
        return list(self.session.scalars(query.order_by(Slot.starts_at, Slot.id)))

    def hold(self, *, slot_id: str, patient_id: str, key: str, ttl_seconds: int = 300) -> Appointment:
        request = {"slot_id": slot_id, "ttl_seconds": ttl_seconds}
        with self.session.begin():
            self._serialize_idempotency(patient_id, "hold", key)
            replay = self._replay(patient_id, "hold", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            self._expire_due_locked()
            slot = self.session.scalar(select(Slot).where(Slot.id == slot_id).with_for_update())
            if slot is None or not slot.enabled:
                raise BookingNotFoundError("Slot is unavailable")
            if _as_utc(slot.starts_at) <= _as_utc(self.clock()):
                raise BookingConflictError("Slot has already started")
            if self._active_hold(slot_id, lock=True):
                raise BookingConflictError("Slot is already reserved")
            now = self.clock()
            appointment = Appointment(
                id=str(uuid.uuid4()),
                slot_id=slot_id,
                patient_id=patient_id,
                status="HELD",
                hold_expires_at=now + timedelta(seconds=ttl_seconds),
                created_at=now,
                updated_at=now,
            )
            self.session.add(appointment)
            self.session.add(
                SlotHold(
                    slot_id=slot_id,
                    appointment_id=appointment.id,
                    patient_id=patient_id,
                    kind="INITIAL",
                    expires_at=appointment.hold_expires_at,
                    created_at=now,
                )
            )
            self._event(appointment, patient_id, "hold_slot", None)
            self._outbox(appointment, "appointment.held")
            self._remember(patient_id, "hold", key, request, appointment)
            return appointment

    def patient_confirm(self, *, appointment_id: str, patient_id: str, key: str) -> Appointment:
        request = {"appointment_id": appointment_id}
        with self.session.begin():
            self._serialize_idempotency(patient_id, "patient_confirm", key)
            replay = self._replay(patient_id, "patient_confirm", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            self._expire_due_locked()
            appointment = self._owned(appointment_id, patient_id, lock=True)
            before = appointment.status
            now = self.clock()
            if appointment.status == "HELD":
                if appointment.hold_expires_at is None or _as_utc(appointment.hold_expires_at) <= _as_utc(now):
                    raise BookingInvalidTransitionError("Hold has expired")
                appointment.patient_confirmed_at = now
                operation = "patient_confirm"
            elif appointment.status == "RESCHEDULE_PROPOSED":
                proposed = self._proposed_hold(appointment.id, lock=True)
                if proposed is None or proposed.expires_at is None or _as_utc(proposed.expires_at) <= _as_utc(now):
                    raise BookingInvalidTransitionError("Reschedule offer has expired")
                appointment.patient_reconfirmed_at = now
                operation = "patient_reconfirm"
            else:
                raise BookingInvalidTransitionError("Patient confirmation is not allowed in the current state")
            appointment.status = "PENDING_STAFF_APPROVAL"
            appointment.version += 1
            appointment.updated_at = now
            self._event(appointment, patient_id, operation, before)
            self._outbox(appointment, f"appointment.{operation}")
            self._remember(patient_id, "patient_confirm", key, request, appointment)
            return appointment

    def staff_decide(self, *, appointment_id: str, staff_id: str, approve: bool, key: str) -> Appointment:
        request = {"appointment_id": appointment_id, "approve": approve}
        with self.session.begin():
            self._serialize_idempotency(staff_id, "staff_decide", key)
            replay = self._replay(staff_id, "staff_decide", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            self._expire_due_locked()
            appointment = self._appointment(appointment_id, lock=True)
            if appointment.status != "PENDING_STAFF_APPROVAL":
                raise BookingInvalidTransitionError("Staff decision requires patient confirmation")
            before = appointment.status
            now = self.clock()
            if appointment.proposed_slot_id:
                proposed = self._proposed_hold(appointment.id, lock=True)
                if proposed is None:
                    raise BookingInvalidTransitionError("Reschedule reservation is missing")
                if approve:
                    self._release_holds(appointment.id, kind="INITIAL", now=now)
                    proposed.kind = "INITIAL"
                    proposed.expires_at = None
                    appointment.slot_id = appointment.proposed_slot_id
                    appointment.staff_approved_at = now
                    appointment.status = "CONFIRMED"
                else:
                    proposed.released_at = now
                    appointment.status = "CONFIRMED"
                appointment.proposed_slot_id = None
                appointment.hold_expires_at = None
                appointment.patient_reconfirmed_at = None
            elif approve:
                initial = self._initial_hold(appointment.id, lock=True)
                if initial is None:
                    raise BookingInvalidTransitionError("Slot reservation is missing")
                initial.expires_at = None
                appointment.hold_expires_at = None
                appointment.staff_approved_at = now
                appointment.status = "CONFIRMED"
            else:
                self._release_holds(appointment.id, now=now)
                appointment.status = "REJECTED"
            appointment.version += 1
            appointment.updated_at = now
            action = "staff_approve" if approve else "staff_reject"
            self._event(appointment, staff_id, action, before)
            self._outbox(appointment, f"appointment.{action}")
            self._remember(staff_id, "staff_decide", key, request, appointment)
            return appointment

    def propose_reschedule(
        self,
        *,
        appointment_id: str,
        staff_id: str,
        new_slot_id: str,
        key: str,
        ttl_seconds: int = 300,
    ) -> Appointment:
        request = {"appointment_id": appointment_id, "slot_id": new_slot_id, "ttl_seconds": ttl_seconds}
        with self.session.begin():
            self._serialize_idempotency(staff_id, "propose_reschedule", key)
            replay = self._replay(staff_id, "propose_reschedule", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            self._expire_due_locked()
            appointment = self._appointment(appointment_id, lock=True)
            if appointment.status != "CONFIRMED" or appointment.proposed_slot_id:
                raise BookingInvalidTransitionError("Only a confirmed appointment can be rescheduled")
            slot = self.session.scalar(select(Slot).where(Slot.id == new_slot_id).with_for_update())
            if slot is None or not slot.enabled:
                raise BookingNotFoundError("Replacement slot is unavailable")
            if new_slot_id == appointment.slot_id or self._active_hold(new_slot_id, lock=True):
                raise BookingConflictError("Replacement slot is already reserved")
            now = self.clock()
            expires_at = now + timedelta(seconds=ttl_seconds)
            self.session.add(
                SlotHold(
                    slot_id=new_slot_id,
                    appointment_id=appointment.id,
                    patient_id=appointment.patient_id,
                    kind="RESCHEDULE",
                    expires_at=expires_at,
                    created_at=now,
                )
            )
            before = appointment.status
            appointment.proposed_slot_id = new_slot_id
            appointment.status = "RESCHEDULE_PROPOSED"
            appointment.hold_expires_at = expires_at
            appointment.patient_reconfirmed_at = None
            appointment.version += 1
            appointment.updated_at = now
            self._event(appointment, staff_id, "propose_reschedule", before)
            self._outbox(appointment, "appointment.reschedule_proposed")
            self.session.flush()
            self._remember(staff_id, "propose_reschedule", key, request, appointment)
            return appointment

    def cancel(self, *, appointment_id: str, actor_id: str, key: str, patient_only: bool) -> Appointment:
        request = {"appointment_id": appointment_id}
        with self.session.begin():
            self._serialize_idempotency(actor_id, "cancel", key)
            replay = self._replay(actor_id, "cancel", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            appointment = self._appointment(appointment_id, lock=True)
            if patient_only and appointment.patient_id != actor_id:
                raise BookingForbiddenError("Appointment ownership mismatch")
            if appointment.status not in ACTIVE_APPOINTMENT_STATES:
                raise BookingInvalidTransitionError("Appointment is not active")
            before = appointment.status
            now = self.clock()
            self._release_holds(appointment.id, now=now)
            appointment.status = "CANCELLED"
            appointment.cancelled_at = now
            appointment.hold_expires_at = None
            appointment.proposed_slot_id = None
            appointment.version += 1
            appointment.updated_at = now
            self._event(appointment, actor_id, "cancel", before)
            self._outbox(appointment, "appointment.cancelled")
            self._remember(actor_id, "cancel", key, request, appointment)
            return appointment

    def mark_no_show(self, *, appointment_id: str, staff_id: str, key: str) -> Appointment:
        request = {"appointment_id": appointment_id}
        with self.session.begin():
            self._serialize_idempotency(staff_id, "mark_no_show", key)
            replay = self._replay(staff_id, "mark_no_show", key, request)
            if replay:
                return self._appointment(replay["id"], lock=True)
            appointment = self._appointment(appointment_id, lock=True)
            slot = self.session.scalar(select(Slot).where(Slot.id == appointment.slot_id).with_for_update())
            if appointment.status != "CONFIRMED" or slot is None or _as_utc(slot.ends_at) > _as_utc(self.clock()):
                raise BookingInvalidTransitionError("No-show can only be recorded after a confirmed slot ends")
            before = appointment.status
            appointment.status = "NO_SHOW"
            appointment.version += 1
            appointment.updated_at = self.clock()
            self._release_holds(appointment.id, now=appointment.updated_at)
            self._event(appointment, staff_id, "mark_no_show", before)
            self._outbox(appointment, "appointment.no_show")
            self._remember(staff_id, "mark_no_show", key, request, appointment)
            return appointment

    def detail(self, appointment_id: str) -> Appointment:
        self.expire_due()
        return self._appointment(appointment_id)

    def history(self, *, patient_id: str) -> list[Appointment]:
        self.expire_due()
        return list(
            self.session.scalars(
                select(Appointment)
                .where(Appointment.patient_id == patient_id)
                .order_by(Appointment.created_at.desc(), Appointment.id)
            )
        )

    def pending_queue(self) -> list[Appointment]:
        self.expire_due()
        return list(
            self.session.scalars(
                select(Appointment)
                .where(Appointment.status.in_(("PENDING_STAFF_APPROVAL", "RESCHEDULE_PROPOSED")))
                .order_by(Appointment.updated_at, Appointment.id)
            )
        )

    def expire_due(self) -> int:
        if self.session.in_transaction():
            return self._expire_due_locked()
        with self.session.begin():
            return self._expire_due_locked()

    def _expire_due_locked(self) -> int:
        now = self.clock()
        holds = list(
            self.session.scalars(
                select(SlotHold)
                .where(SlotHold.released_at.is_(None), SlotHold.expires_at.is_not(None), SlotHold.expires_at <= now)
                .with_for_update()
            )
        )
        changed = 0
        for hold in holds:
            appointment = self._appointment(hold.appointment_id, lock=True)
            hold.released_at = now
            before = appointment.status
            if hold.kind == "INITIAL" and appointment.status == "HELD":
                appointment.status = "EXPIRED"
                appointment.hold_expires_at = None
                outbox_event = "appointment.expired"
            elif hold.kind == "RESCHEDULE" and appointment.proposed_slot_id == hold.slot_id:
                appointment.status = "CONFIRMED"
                appointment.proposed_slot_id = None
                appointment.hold_expires_at = None
                appointment.patient_reconfirmed_at = None
                outbox_event = "appointment.reschedule_expired"
            else:
                continue
            appointment.version += 1
            appointment.updated_at = now
            self._event(appointment, None, "expire", before)
            self._outbox(appointment, outbox_event)
            changed += 1
        return changed

    def _appointment(self, appointment_id: object, *, lock: bool = False) -> Appointment:
        query = select(Appointment).where(Appointment.id == str(appointment_id))
        if lock:
            query = query.with_for_update()
        value = self.session.scalar(query)
        if value is None:
            raise BookingNotFoundError("Appointment was not found")
        return value

    def _owned(self, appointment_id: str, patient_id: str, *, lock: bool) -> Appointment:
        value = self._appointment(appointment_id, lock=lock)
        if value.patient_id != patient_id:
            raise BookingForbiddenError("Appointment ownership mismatch")
        return value

    def _active_hold(self, slot_id: str, *, lock: bool) -> SlotHold | None:
        query = select(SlotHold).where(SlotHold.slot_id == slot_id, SlotHold.released_at.is_(None))
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def _initial_hold(self, appointment_id: str, *, lock: bool) -> SlotHold | None:
        query = select(SlotHold).where(
            SlotHold.appointment_id == appointment_id,
            SlotHold.kind == "INITIAL",
            SlotHold.released_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def _proposed_hold(self, appointment_id: str, *, lock: bool) -> SlotHold | None:
        query = select(SlotHold).where(
            SlotHold.appointment_id == appointment_id,
            SlotHold.kind == "RESCHEDULE",
            SlotHold.released_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def _release_holds(self, appointment_id: str, *, now: datetime, kind: str | None = None) -> None:
        conditions = [SlotHold.appointment_id == appointment_id, SlotHold.released_at.is_(None)]
        if kind:
            conditions.append(SlotHold.kind == kind)
        for hold in self.session.scalars(select(SlotHold).where(and_(*conditions)).with_for_update()):
            hold.released_at = now

    def _event(self, appointment: Appointment, actor_id: str | None, action: str, from_status: str | None) -> None:
        self.session.add(
            AppointmentEvent(
                appointment_id=appointment.id,
                actor_id=actor_id,
                action=action,
                from_status=from_status,
                to_status=appointment.status,
                safe_metadata={"version": appointment.version},
            )
        )

    def _outbox(self, appointment: Appointment, event_type: str) -> None:
        self.session.add(
            BookingOutbox(
                aggregate_id=appointment.id,
                event_type=event_type,
                payload={
                    "appointment_id": appointment.id,
                    "status": appointment.status,
                    "version": appointment.version,
                },
            )
        )

    @staticmethod
    def _request_hash(request: Mapping[str, object]) -> str:
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _serialize_idempotency(self, actor_id: str, operation: str, key: str) -> None:
        """Serialize identical keys across PostgreSQL replicas before replay lookup."""
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        digest = hashlib.sha256(f"{actor_id}\0{operation}\0{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    def _replay(
        self, actor_id: str, operation: str, key: str, request: Mapping[str, object]
    ) -> dict[str, object] | None:
        record = self.session.get(IdempotencyRecord, (actor_id, operation, key))
        if record is None:
            return None
        if record.request_hash != self._request_hash(request):
            raise BookingConflictError("Idempotency key was reused with a different request")
        if record.response_json is None:
            raise BookingConflictError("Identical request is still being processed")
        return record.response_json

    def _remember(
        self,
        actor_id: str,
        operation: str,
        key: str,
        request: Mapping[str, object],
        appointment: Appointment,
    ) -> None:
        payload = appointment_payload(appointment)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.session.add(
            IdempotencyRecord(
                actor_id=actor_id,
                operation=operation,
                key=key,
                request_hash=self._request_hash(request),
                response_hash=hashlib.sha256(encoded).hexdigest(),
                response_json=payload,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise BookingConflictError("Booking request conflicts with an existing reservation or key") from exc
