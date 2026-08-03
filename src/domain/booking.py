"""Concurrency-safe booking state machine with idempotent mutations."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BookingConflictError(RuntimeError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


class AppointmentStatus(StrEnum):
    HELD = "HELD"
    PATIENT_CONFIRMED = "PATIENT_CONFIRMED"
    PENDING_STAFF_APPROVAL = "PENDING_STAFF_APPROVAL"
    CONFIRMED = "CONFIRMED"
    RESCHEDULE_PROPOSED = "RESCHEDULE_PROPOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


ACTIVE_STATUSES = {
    AppointmentStatus.HELD,
    AppointmentStatus.PATIENT_CONFIRMED,
    AppointmentStatus.PENDING_STAFF_APPROVAL,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.RESCHEDULE_PROPOSED,
}


@dataclass(frozen=True)
class Appointment:
    id: str
    slot_id: str
    patient_id: str
    status: AppointmentStatus
    hold_expires_at: float | None
    version: int = 1


@dataclass(frozen=True)
class AppointmentEvent:
    appointment_id: str
    action: str
    actor_id: str
    occurred_at: datetime
    from_status: AppointmentStatus | None
    to_status: AppointmentStatus


class BookingService:
    """Offline/reference adapter; production persistence uses the same transition rules in a DB transaction."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._appointments: dict[str, Appointment] = {}
        self._slot_active: dict[str, str] = {}
        self._idempotency: dict[tuple[str, str], Any] = {}
        self._events: list[AppointmentEvent] = []
        self._lock = asyncio.Lock()

    @property
    def events(self) -> tuple[AppointmentEvent, ...]:
        return tuple(self._events)

    async def hold_slot(
        self, slot_id: str, patient_id: str, idempotency_key: str, *, ttl_seconds: int = 300
    ) -> Appointment:
        async with self._lock:
            cached = self._cached("hold_slot", idempotency_key)
            if cached:
                return cached
            self._expire_locked()
            if slot_id in self._slot_active:
                raise BookingConflictError("Slot is already reserved")
            appointment = Appointment(
                str(uuid.uuid4()),
                slot_id,
                patient_id,
                AppointmentStatus.HELD,
                self._clock() + ttl_seconds,
            )
            self._appointments[appointment.id] = appointment
            self._slot_active[slot_id] = appointment.id
            self._record(appointment, "hold_slot", patient_id, None)
            return self._remember("hold_slot", idempotency_key, appointment)

    async def patient_confirm(self, appointment_id: str, patient_id: str, idempotency_key: str) -> Appointment:
        async with self._lock:
            cached = self._cached("patient_confirm", idempotency_key)
            if cached:
                return cached
            self._expire_locked()
            current = self._owned(appointment_id, patient_id)
            expected = {AppointmentStatus.HELD, AppointmentStatus.RESCHEDULE_PROPOSED}
            if current.status not in expected:
                raise InvalidTransitionError("Patient confirmation requires an active hold or reschedule offer")
            updated = self._transition(current, AppointmentStatus.PATIENT_CONFIRMED, "patient_confirm", patient_id)
            updated = self._transition(
                updated, AppointmentStatus.PENDING_STAFF_APPROVAL, "request_staff_approval", patient_id
            )
            return self._remember("patient_confirm", idempotency_key, updated)

    async def staff_decide(
        self, appointment_id: str, staff_id: str, approve: bool, idempotency_key: str
    ) -> Appointment:
        async with self._lock:
            cached = self._cached("staff_decide", idempotency_key)
            if cached:
                return cached
            current = self._appointments[appointment_id]
            if current.status != AppointmentStatus.PENDING_STAFF_APPROVAL:
                raise InvalidTransitionError("Staff may decide only after patient confirmation")
            target = AppointmentStatus.CONFIRMED if approve else AppointmentStatus.REJECTED
            updated = self._transition(current, target, "staff_approve" if approve else "staff_reject", staff_id)
            if not approve:
                self._slot_active.pop(updated.slot_id, None)
            return self._remember("staff_decide", idempotency_key, updated)

    async def propose_reschedule(
        self, appointment_id: str, staff_id: str, new_slot_id: str, idempotency_key: str
    ) -> Appointment:
        async with self._lock:
            cached = self._cached("propose_reschedule", idempotency_key)
            if cached:
                return cached
            current = self._appointments[appointment_id]
            if current.status != AppointmentStatus.CONFIRMED:
                raise InvalidTransitionError("Only confirmed appointments can be rescheduled")
            if new_slot_id in self._slot_active:
                raise BookingConflictError("Replacement slot is unavailable")
            self._slot_active.pop(current.slot_id, None)
            self._slot_active[new_slot_id] = current.id
            moved = replace(current, slot_id=new_slot_id, hold_expires_at=self._clock() + 300)
            self._appointments[current.id] = moved
            updated = self._transition(moved, AppointmentStatus.RESCHEDULE_PROPOSED, "propose_reschedule", staff_id)
            return self._remember("propose_reschedule", idempotency_key, updated)

    async def cancel(self, appointment_id: str, actor_id: str, idempotency_key: str) -> Appointment:
        async with self._lock:
            cached = self._cached("cancel", idempotency_key)
            if cached:
                return cached
            current = self._appointments[appointment_id]
            if current.status not in ACTIVE_STATUSES:
                raise InvalidTransitionError("Appointment is not active")
            updated = self._transition(current, AppointmentStatus.CANCELLED, "cancel", actor_id)
            self._slot_active.pop(updated.slot_id, None)
            return self._remember("cancel", idempotency_key, updated)

    def _expire_locked(self) -> None:
        for current in tuple(self._appointments.values()):
            if (
                current.status in {AppointmentStatus.HELD, AppointmentStatus.RESCHEDULE_PROPOSED}
                and current.hold_expires_at is not None
                and current.hold_expires_at <= self._clock()
            ):
                self._transition(current, AppointmentStatus.EXPIRED, "expire", "system")
                self._slot_active.pop(current.slot_id, None)

    def _owned(self, appointment_id: str, patient_id: str) -> Appointment:
        current = self._appointments[appointment_id]
        if current.patient_id != patient_id:
            raise PermissionError("Appointment ownership mismatch")
        return current

    def _transition(self, current: Appointment, target: AppointmentStatus, action: str, actor_id: str) -> Appointment:
        updated = replace(current, status=target, version=current.version + 1)
        self._appointments[current.id] = updated
        self._record(updated, action, actor_id, current.status)
        return updated

    def _record(
        self,
        appointment: Appointment,
        action: str,
        actor_id: str,
        previous: AppointmentStatus | None,
    ) -> None:
        self._events.append(
            AppointmentEvent(
                appointment.id,
                action,
                actor_id,
                datetime.now(UTC),
                previous,
                appointment.status,
            )
        )

    def _cached(self, operation: str, key: str):
        return self._idempotency.get((operation, key))

    def _remember(self, operation: str, key: str, value: Appointment) -> Appointment:
        self._idempotency[(operation, key)] = value
        return value
