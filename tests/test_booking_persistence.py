from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.auth_routes import AuthContext, authenticated_context, csrf_protected
from src.booking.api import router
from src.booking.models import AppointmentEvent, BookingOutbox, Slot, SlotHold
from src.booking.repository import (
    BookingConflictError,
    BookingForbiddenError,
    BookingInvalidTransitionError,
    BookingRepository,
)
from src.persistence.database import Base, get_db_session
from src.persistence.identity_models import UserRecord
from src.security.auth import Principal, Role
from src.workers.booking import BookingMaintenance


@pytest.fixture
def booking_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'booking.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                UserRecord(
                    id="10000000-0000-0000-0000-000000000001",
                    email="patient@example.test",
                    role=Role.PATIENT,
                    password_hash="not-used-in-booking-test",
                ),
                UserRecord(
                    id="20000000-0000-0000-0000-000000000002",
                    email="patient2@example.test",
                    role=Role.PATIENT,
                    password_hash="not-used-in-booking-test",
                ),
                UserRecord(
                    id="30000000-0000-0000-0000-000000000003",
                    email="staff@example.test",
                    role=Role.STAFF,
                    password_hash="not-used-in-booking-test",
                ),
            ]
        )
        start = datetime.now(UTC) + timedelta(days=1)
        session.add_all(
            [
                Slot(
                    id="40000000-0000-0000-0000-000000000004",
                    specialty_id="cardiology",
                    facility_id="main",
                    starts_at=start,
                    ends_at=start + timedelta(minutes=30),
                ),
                Slot(
                    id="50000000-0000-0000-0000-000000000005",
                    specialty_id="cardiology",
                    facility_id="main",
                    starts_at=start + timedelta(hours=1),
                    ends_at=start + timedelta(hours=1, minutes=30),
                ),
            ]
        )
    return factory


PATIENT = "10000000-0000-0000-0000-000000000001"
PATIENT_2 = "20000000-0000-0000-0000-000000000002"
STAFF = "30000000-0000-0000-0000-000000000003"
SLOT_1 = "40000000-0000-0000-0000-000000000004"
SLOT_2 = "50000000-0000-0000-0000-000000000005"


def _call(factory: sessionmaker[Session], method: str, **kwargs):
    with factory() as session:
        return getattr(BookingRepository(session), method)(**kwargs)


def test_booking_lifecycle_is_persistent_idempotent_and_audited(booking_factory: sessionmaker[Session]) -> None:
    held = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="hold-key-1")
    replay = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="hold-key-1")
    assert replay.id == held.id
    with pytest.raises(BookingConflictError):
        _call(booking_factory, "hold", slot_id=SLOT_2, patient_id=PATIENT, key="hold-key-1")

    pending = _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key="confirm-key-1",
    )
    assert pending.status == "PENDING_STAFF_APPROVAL"
    confirmed = _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=True,
        key="approve-key-1",
    )
    assert confirmed.status == "CONFIRMED"
    assert confirmed.patient_confirmed_at is not None
    assert confirmed.staff_approved_at is not None

    history = _call(booking_factory, "history", patient_id=PATIENT)
    assert [item.id for item in history] == [held.id]
    with booking_factory() as session:
        actions = list(session.scalars(select(AppointmentEvent.action).order_by(AppointmentEvent.id)))
        assert actions == ["hold_slot", "patient_confirm", "staff_approve"]
        assert session.scalar(select(BookingOutbox).where(BookingOutbox.aggregate_id == held.id)) is not None


def test_confirmation_requires_owner_and_staff_cannot_skip_patient(
    booking_factory: sessionmaker[Session],
) -> None:
    held = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="hold-key-2")
    with pytest.raises(BookingForbiddenError):
        _call(
            booking_factory,
            "patient_confirm",
            appointment_id=held.id,
            patient_id=PATIENT_2,
            key="cross-patient",
        )
    with pytest.raises(BookingInvalidTransitionError):
        _call(
            booking_factory,
            "staff_decide",
            appointment_id=held.id,
            staff_id=STAFF,
            approve=True,
            key="premature-approval",
        )


def test_reschedule_keeps_original_reserved_until_reconfirm_and_staff_approval(
    booking_factory: sessionmaker[Session],
) -> None:
    held = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="hold-key-3")
    _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key="confirm-key-3",
    )
    _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=True,
        key="approve-key-3",
    )
    proposed = _call(
        booking_factory,
        "propose_reschedule",
        appointment_id=held.id,
        staff_id=STAFF,
        new_slot_id=SLOT_2,
        key="reschedule-key-3",
    )
    assert proposed.status == "RESCHEDULE_PROPOSED"
    assert proposed.slot_id == SLOT_1
    assert proposed.proposed_slot_id == SLOT_2
    with pytest.raises(BookingConflictError):
        _call(booking_factory, "hold", slot_id=SLOT_2, patient_id=PATIENT_2, key="blocked-new-slot")

    reconfirmed = _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key="reconfirm-key-3",
    )
    assert reconfirmed.status == "PENDING_STAFF_APPROVAL"
    moved = _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=True,
        key="approve-move-key-3",
    )
    assert moved.status == "CONFIRMED"
    assert moved.slot_id == SLOT_2
    assert moved.proposed_slot_id is None
    replacement = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT_2, key="old-slot-free")
    assert replacement.status == "HELD"


def test_expired_hold_is_released_and_cannot_be_confirmed(booking_factory: sessionmaker[Session]) -> None:
    current = [datetime.now(UTC)]
    with booking_factory() as session:
        held = BookingRepository(session, clock=lambda: current[0]).hold(
            slot_id=SLOT_1, patient_id=PATIENT, key="expiring-hold", ttl_seconds=30
        )
    current[0] += timedelta(seconds=31)
    with booking_factory() as session:
        assert BookingRepository(session, clock=lambda: current[0]).expire_due() == 1
    with pytest.raises(BookingInvalidTransitionError):
        with booking_factory() as session:
            BookingRepository(session, clock=lambda: current[0]).patient_confirm(
                appointment_id=held.id, patient_id=PATIENT, key="late-confirm"
            )
    replacement = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT_2, key="after-expiry")
    assert replacement.patient_id == PATIENT_2


def _confirmed_appointment(booking_factory: sessionmaker[Session], *, suffix: str):
    held = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key=f"hold-{suffix}")
    _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key=f"confirm-{suffix}",
    )
    return _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=True,
        key=f"approve-{suffix}",
    )


def test_no_show_is_post_slot_staff_event_and_idempotent(booking_factory: sessionmaker[Session]) -> None:
    confirmed = _confirmed_appointment(booking_factory, suffix="no-show")
    with booking_factory() as session:
        slot = session.get(Slot, confirmed.slot_id)
        assert slot is not None
        after_slot = slot.ends_at.replace(tzinfo=UTC) + timedelta(minutes=1)
    with booking_factory() as session:
        repository = BookingRepository(session, clock=lambda: after_slot)
        no_show = repository.mark_no_show(appointment_id=confirmed.id, staff_id=STAFF, key="no-show-key")
    assert no_show.status == "NO_SHOW"
    with booking_factory() as session:
        replay = BookingRepository(session, clock=lambda: after_slot).mark_no_show(
            appointment_id=confirmed.id, staff_id=STAFF, key="no-show-key"
        )
    assert replay.status == "NO_SHOW"
    with booking_factory() as session:
        assert session.scalar(
            select(AppointmentEvent).where(
                AppointmentEvent.appointment_id == confirmed.id,
                AppointmentEvent.action == "mark_no_show",
            )
        )


def test_worker_schedules_and_delivers_idempotently_without_phi_analytics(
    booking_factory: sessionmaker[Session],
) -> None:
    confirmed = _confirmed_appointment(booking_factory, suffix="worker")
    with booking_factory() as session:
        slot = session.get(Slot, confirmed.slot_id)
        assert slot is not None
        current = [slot.starts_at.replace(tzinfo=UTC) - timedelta(hours=23)]
    worker = BookingMaintenance(booking_factory, clock=lambda: current[0])
    assert worker.schedule_reminders() == 1
    assert worker.schedule_reminders() == 0

    class RecordingSink:
        def __init__(self) -> None:
            self.keys: set[str] = set()

        def deliver(self, delivery_key: str, event_type: str, payload: dict[str, object]) -> None:
            assert delivery_key not in self.keys
            self.keys.add(delivery_key)

    sink = RecordingSink()
    reminder_result = worker.dispatch_reminders(sink)
    outbox_result = worker.dispatch_outbox(sink)
    assert reminder_result["delivered"] == 1
    assert outbox_result["delivered"] == 3
    assert worker.dispatch_reminders(sink)["claimed"] == 0
    assert worker.dispatch_outbox(sink)["claimed"] == 0
    analytics = worker.analytics_snapshot()
    serialized = json.dumps(analytics)
    assert "staff_approve" in serialized
    assert PATIENT not in serialized
    assert confirmed.id not in serialized


def test_worker_retries_then_dead_letters_with_safe_error_code(
    booking_factory: sessionmaker[Session],
) -> None:
    current = [datetime.now(UTC)]
    with booking_factory.begin() as session:
        session.add(
            BookingOutbox(
                aggregate_id="90000000-0000-0000-0000-000000000009",
                event_type="appointment.test",
                payload={"status": "TEST", "version": 1},
                available_at=current[0],
            )
        )

    class FailingSink:
        def deliver(self, delivery_key: str, event_type: str, payload: dict[str, object]) -> None:
            raise ConnectionError("sensitive provider response must not be stored")

    worker = BookingMaintenance(booking_factory, clock=lambda: current[0], max_attempts=2)
    assert worker.dispatch_outbox(FailingSink())["retried"] == 1
    current[0] += timedelta(minutes=2)
    assert worker.dispatch_outbox(FailingSink())["dead_lettered"] == 1
    with booking_factory() as session:
        row = session.scalar(select(BookingOutbox).where(BookingOutbox.event_type == "appointment.test"))
        assert row is not None
        assert row.last_error_code == "ConnectionError"
        assert row.dead_lettered_at is not None
        assert "sensitive" not in (row.last_error_code or "")


def test_cancel_releases_slot_and_reschedule_rejection_keeps_original(
    booking_factory: sessionmaker[Session],
) -> None:
    held = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="hold-cancel-flow")
    _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key="confirm-cancel-flow",
    )
    _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=True,
        key="approve-cancel-flow",
    )
    _call(
        booking_factory,
        "propose_reschedule",
        appointment_id=held.id,
        staff_id=STAFF,
        new_slot_id=SLOT_2,
        key="offer-cancel-flow",
    )
    _call(
        booking_factory,
        "patient_confirm",
        appointment_id=held.id,
        patient_id=PATIENT,
        key="reconfirm-cancel-flow",
    )
    rejected_move = _call(
        booking_factory,
        "staff_decide",
        appointment_id=held.id,
        staff_id=STAFF,
        approve=False,
        key="reject-move-flow",
    )
    assert rejected_move.status == "CONFIRMED"
    assert rejected_move.slot_id == SLOT_1
    assert rejected_move.proposed_slot_id is None
    second_patient = _call(booking_factory, "hold", slot_id=SLOT_2, patient_id=PATIENT_2, key="released-proposed-slot")
    assert second_patient.status == "HELD"

    cancelled = _call(
        booking_factory,
        "cancel",
        appointment_id=held.id,
        actor_id=PATIENT,
        key="cancel-confirmed-flow",
        patient_only=True,
    )
    assert cancelled.status == "CANCELLED"
    replacement = _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT_2, key="released-old-slot")
    assert replacement.status == "HELD"


def test_availability_excludes_active_holds(booking_factory: sessionmaker[Session]) -> None:
    start = datetime.now(UTC)
    end = start + timedelta(days=3)
    with booking_factory() as session:
        initial = BookingRepository(session).availability(starts_after=start, ends_before=end)
    assert {slot.id for slot in initial} == {SLOT_1, SLOT_2}
    _call(booking_factory, "hold", slot_id=SLOT_1, patient_id=PATIENT, key="availability-hold")
    with booking_factory() as session:
        remaining = BookingRepository(session).availability(starts_after=start, ends_before=end)
    assert [slot.id for slot in remaining] == [SLOT_2]


def test_concurrent_holds_have_exactly_one_winner(booking_factory: sessionmaker[Session]) -> None:
    barrier = threading.Barrier(4)

    def attempt(index: int) -> str:
        barrier.wait()
        try:
            _call(
                booking_factory,
                "hold",
                slot_id=SLOT_1,
                patient_id=PATIENT if index == 0 else PATIENT_2,
                key=f"concurrent-{index}",
            )
            return "won"
        except BookingConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    assert outcomes.count("won") == 1
    assert outcomes.count("conflict") == 3
    with booking_factory() as session:
        assert session.scalar(select(SlotHold).where(SlotHold.released_at.is_(None))) is not None


def test_booking_api_enforces_role_and_uses_authenticated_identity(
    booking_factory: sessionmaker[Session],
) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def db_override():
        with booking_factory() as session:
            yield session

    patient_context = AuthContext(Principal(PATIENT, Role.PATIENT), "session-token-not-returned")
    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[authenticated_context] = lambda: patient_context
    app.dependency_overrides[csrf_protected] = lambda: patient_context

    client = TestClient(app)
    created = client.post(
        "/api/v1/booking/holds",
        json={"slot_id": SLOT_1, "ttl_seconds": 300},
        headers={"Idempotency-Key": "api-hold-key"},
    )
    assert created.status_code == 201
    assert created.json()["patient_id"] == PATIENT
    assert client.get("/api/v1/booking/staff/queue").status_code == 403
    assert (
        client.post(
            f"/api/v1/booking/staff/appointments/{created.json()['id']}/no-show",
            headers={"Idempotency-Key": "patient-no-show-forbidden"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/booking/appointments").json()["items"][0]["id"] == created.json()["id"]
