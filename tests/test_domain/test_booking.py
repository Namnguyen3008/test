import asyncio

import pytest

from src.domain.booking import (
    AppointmentStatus,
    BookingConflictError,
    BookingService,
    InvalidTransitionError,
)


@pytest.mark.asyncio
async def test_full_booking_requires_patient_then_staff():
    service = BookingService()
    appointment = await service.hold_slot("slot-1", "patient-1", "hold-1")
    assert appointment.status == AppointmentStatus.HELD
    with pytest.raises(InvalidTransitionError):
        await service.staff_decide(appointment.id, "staff-1", True, "early")
    pending = await service.patient_confirm(appointment.id, "patient-1", "confirm-1")
    assert pending.status == AppointmentStatus.PENDING_STAFF_APPROVAL
    confirmed = await service.staff_decide(appointment.id, "staff-1", True, "approve-1")
    assert confirmed.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_concurrent_holds_never_double_book():
    service = BookingService()

    async def hold(patient: str):
        try:
            return await service.hold_slot("same-slot", patient, patient)
        except BookingConflictError:
            return None

    results = await asyncio.gather(hold("p1"), hold("p2"), hold("p3"))
    assert sum(result is not None for result in results) == 1


@pytest.mark.asyncio
async def test_idempotency_and_reschedule_reconfirmation():
    service = BookingService()
    held = await service.hold_slot("s1", "p1", "same-key")
    assert held == await service.hold_slot("s1", "p1", "same-key")
    await service.patient_confirm(held.id, "p1", "c1")
    await service.staff_decide(held.id, "staff", True, "a1")
    proposed = await service.propose_reschedule(held.id, "staff", "s2", "r1")
    assert proposed.status == AppointmentStatus.RESCHEDULE_PROPOSED
    reconfirmed = await service.patient_confirm(held.id, "p1", "c2")
    assert reconfirmed.status == AppointmentStatus.PENDING_STAFF_APPROVAL


@pytest.mark.asyncio
async def test_expired_hold_releases_slot():
    now = [10.0]
    service = BookingService(clock=lambda: now[0])
    held = await service.hold_slot("slot", "p1", "h1", ttl_seconds=1)
    now[0] = 12.0
    replacement = await service.hold_slot("slot", "p2", "h2")
    assert replacement.patient_id == "p2"
    assert any(event.appointment_id == held.id and event.to_status == "EXPIRED" for event in service.events)
