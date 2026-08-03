"""Persistent booking maintenance with retryable, idempotency-keyed delivery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.booking.models import (
    Appointment,
    AppointmentEvent,
    AppointmentReminder,
    BookingOutbox,
    Slot,
)
from src.booking.repository import BookingRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DeliverySink(Protocol):
    """The delivery key must be honored idempotently by the external adapter."""

    def deliver(self, delivery_key: str, event_type: str, payload: dict[str, object]) -> None: ...


class UnavailableDeliverySink:
    """Fail closed until an authenticated external notification adapter is configured."""

    def deliver(self, delivery_key: str, event_type: str, payload: dict[str, object]) -> None:
        raise RuntimeError("notification_provider_unavailable")


class BookingMaintenance:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _now,
        max_attempts: int = 5,
    ) -> None:
        self.factory = factory
        self.clock = clock
        self.max_attempts = max_attempts

    def expire_holds(self) -> int:
        with self.factory() as session:
            return BookingRepository(session, clock=self.clock).expire_due()

    def schedule_reminders(self, *, channel: str = "sms", hours_before: int = 24) -> int:
        now = self.clock()
        created = 0
        with self.factory.begin() as session:
            rows = session.execute(
                select(Appointment.id, Slot.starts_at)
                .join(Slot, Slot.id == Appointment.slot_id)
                .where(Appointment.status == "CONFIRMED", Slot.starts_at > now)
                .with_for_update(skip_locked=True)
            )
            for appointment_id, starts_at in rows:
                scheduled_for = _as_utc(starts_at) - timedelta(hours=hours_before)
                exists = session.scalar(
                    select(AppointmentReminder.id).where(
                        AppointmentReminder.appointment_id == appointment_id,
                        AppointmentReminder.channel == channel,
                        AppointmentReminder.template_id == "visit-24h",
                        AppointmentReminder.scheduled_for == scheduled_for,
                    )
                )
                if exists is not None:
                    continue
                try:
                    with session.begin_nested():
                        session.add(
                            AppointmentReminder(
                                appointment_id=appointment_id,
                                channel=channel,
                                template_id="visit-24h",
                                scheduled_for=scheduled_for,
                                available_at=max(now, scheduled_for),
                            )
                        )
                        session.flush()
                    created += 1
                except IntegrityError:
                    pass
        return created

    def dispatch_outbox(self, sink: DeliverySink, *, limit: int = 100) -> dict[str, int]:
        now = self.clock()
        claimed: list[int] = []
        with self.factory.begin() as session:
            rows = list(
                session.scalars(
                    select(BookingOutbox)
                    .where(
                        BookingOutbox.delivered_at.is_(None),
                        BookingOutbox.dead_lettered_at.is_(None),
                        BookingOutbox.available_at <= now,
                        or_(BookingOutbox.locked_at.is_(None), BookingOutbox.locked_at < now - timedelta(minutes=5)),
                    )
                    .order_by(BookingOutbox.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.locked_at = now
                claimed.append(row.id)
        return self._deliver_outbox(claimed, sink)

    def _deliver_outbox(self, claimed: list[int], sink: DeliverySink) -> dict[str, int]:
        result = Counter(claimed=len(claimed), delivered=0, retried=0, dead_lettered=0)
        for row_id in claimed:
            with self.factory() as session:
                row = session.get(BookingOutbox, row_id)
                if row is None or row.delivered_at or row.dead_lettered_at:
                    continue
                try:
                    sink.deliver(f"booking-outbox:{row.id}", row.event_type, dict(row.payload))
                except Exception as exc:
                    self._record_failure(row, type(exc).__name__)
                    result["dead_lettered" if row.dead_lettered_at else "retried"] += 1
                else:
                    row.delivered_at = self.clock()
                    row.locked_at = None
                    row.last_error_code = None
                    result["delivered"] += 1
                session.commit()
        return dict(result)

    def dispatch_reminders(self, sink: DeliverySink, *, limit: int = 100) -> dict[str, int]:
        now = self.clock()
        claimed: list[int] = []
        with self.factory.begin() as session:
            rows = list(
                session.scalars(
                    select(AppointmentReminder)
                    .where(
                        AppointmentReminder.status == "PENDING",
                        AppointmentReminder.dead_lettered_at.is_(None),
                        AppointmentReminder.scheduled_for <= now,
                        AppointmentReminder.available_at <= now,
                        or_(
                            AppointmentReminder.locked_at.is_(None),
                            AppointmentReminder.locked_at < now - timedelta(minutes=5),
                        ),
                    )
                    .order_by(AppointmentReminder.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.locked_at = now
                claimed.append(row.id)
        result = Counter(claimed=len(claimed), delivered=0, retried=0, dead_lettered=0)
        for row_id in claimed:
            with self.factory() as session:
                reminder = session.get(AppointmentReminder, row_id)
                if reminder is None or reminder.delivered_at or reminder.dead_lettered_at:
                    continue
                payload: dict[str, object] = {
                    "appointment_id": reminder.appointment_id,
                    "channel": reminder.channel,
                    "template_id": reminder.template_id,
                    "scheduled_for": _as_utc(reminder.scheduled_for).isoformat(),
                }
                try:
                    sink.deliver(f"appointment-reminder:{reminder.id}", "appointment.reminder", payload)
                except Exception as exc:
                    self._record_failure(reminder, type(exc).__name__)
                    result["dead_lettered" if reminder.dead_lettered_at else "retried"] += 1
                else:
                    reminder.status = "DELIVERED"
                    reminder.delivered_at = self.clock()
                    reminder.locked_at = None
                    reminder.last_error_code = None
                    result["delivered"] += 1
                session.commit()
        return dict(result)

    def _record_failure(self, row: BookingOutbox | AppointmentReminder, error_code: str) -> None:
        row.attempt_count += 1
        row.locked_at = None
        row.last_error_code = error_code[:100]
        if row.attempt_count >= self.max_attempts:
            row.dead_lettered_at = self.clock()
        else:
            row.available_at = self.clock() + timedelta(minutes=2 ** (row.attempt_count - 1))

    def analytics_snapshot(self) -> dict[str, dict[str, int]]:
        """Return aggregate counts only: no patient, appointment, prompt or message data."""
        with self.factory() as session:
            actions = Counter(str(value) for value in session.scalars(select(AppointmentEvent.action)))
            statuses = Counter(str(value) for value in session.scalars(select(AppointmentEvent.to_status)))
        return {"actions": dict(sorted(actions.items())), "statuses": dict(sorted(statuses.items()))}
