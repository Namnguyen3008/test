"""Authenticated persistent booking HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.auth_routes import AuthContext, authenticated_context, csrf_protected
from src.booking.models import Appointment, Slot
from src.booking.repository import (
    BookingConflictError,
    BookingForbiddenError,
    BookingInvalidTransitionError,
    BookingNotFoundError,
    BookingRepository,
)
from src.booking.schemas import (
    AppointmentHistory,
    AppointmentView,
    AvailabilityResponse,
    HoldRequest,
    RescheduleRequest,
    SlotView,
    StaffDecisionRequest,
)
from src.persistence.database import get_db_session
from src.security.auth import Principal, Role, require_role

router = APIRouter(prefix="/booking", tags=["booking"])


SessionDependency = Annotated[Session, Depends(get_db_session)]
AuthDependency = Annotated[AuthContext, Depends(authenticated_context)]
MutationAuthDependency = Annotated[AuthContext, Depends(csrf_protected)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


def _allow(principal: Principal, *roles: Role) -> None:
    try:
        require_role(principal, *roles)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc


def _appointment_view(value: Appointment, *, expose_patient_id: bool = True) -> AppointmentView:
    return AppointmentView(
        id=value.id,
        slot_id=value.slot_id,
        proposed_slot_id=value.proposed_slot_id,
        patient_id=value.patient_id if expose_patient_id else "masked",
        status=value.status,
        hold_expires_at=value.hold_expires_at,
        patient_confirmed_at=value.patient_confirmed_at,
        patient_reconfirmed_at=value.patient_reconfirmed_at,
        staff_approved_at=value.staff_approved_at,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _slot_view(value: Slot) -> SlotView:
    return SlotView(
        id=value.id,
        specialty_id=value.specialty_id,
        facility_id=value.facility_id,
        practitioner_id=value.practitioner_id,
        starts_at=value.starts_at,
        ends_at=value.ends_at,
    )


def _translate_error(exc: Exception) -> None:
    if isinstance(exc, BookingNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, BookingForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, (BookingConflictError, BookingInvalidTransitionError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/availability", response_model=AvailabilityResponse)
def availability(
    session: SessionDependency,
    context: AuthDependency,
    starts_after: Annotated[datetime, Query()],
    ends_before: Annotated[datetime, Query()],
    specialty_id: str | None = None,
    facility_id: str | None = None,
) -> AvailabilityResponse:
    _allow(context.principal, Role.PATIENT, Role.STAFF, Role.CLINICAL_REVIEWER, Role.ADMIN)
    if ends_before <= starts_after:
        raise HTTPException(status_code=422, detail="Invalid availability window")
    values = BookingRepository(session).availability(
        starts_after=starts_after,
        ends_before=ends_before,
        specialty_id=specialty_id,
        facility_id=facility_id,
    )
    return AvailabilityResponse(items=[_slot_view(value) for value in values])


@router.post("/holds", response_model=AppointmentView, status_code=201)
def hold_slot(
    body: HoldRequest,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.PATIENT)
    try:
        value = BookingRepository(session).hold(
            slot_id=body.slot_id,
            patient_id=principal.user_id,
            key=idempotency_key,
            ttl_seconds=body.ttl_seconds,
        )
        return _appointment_view(value)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentView)
@router.post("/appointments/{appointment_id}/reconfirm", response_model=AppointmentView)
def patient_confirm(
    appointment_id: str,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.PATIENT)
    try:
        value = BookingRepository(session).patient_confirm(
            appointment_id=appointment_id, patient_id=principal.user_id, key=idempotency_key
        )
        return _appointment_view(value)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/staff/appointments/{appointment_id}/decision", response_model=AppointmentView)
def staff_decide(
    appointment_id: str,
    body: StaffDecisionRequest,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.STAFF, Role.ADMIN)
    try:
        value = BookingRepository(session).staff_decide(
            appointment_id=appointment_id,
            staff_id=principal.user_id,
            approve=body.approve,
            key=idempotency_key,
        )
        return _appointment_view(value, expose_patient_id=False)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/staff/appointments/{appointment_id}/reschedule", response_model=AppointmentView)
def propose_reschedule(
    appointment_id: str,
    body: RescheduleRequest,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.STAFF, Role.ADMIN)
    try:
        value = BookingRepository(session).propose_reschedule(
            appointment_id=appointment_id,
            staff_id=principal.user_id,
            new_slot_id=body.slot_id,
            ttl_seconds=body.ttl_seconds,
            key=idempotency_key,
        )
        return _appointment_view(value, expose_patient_id=False)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/staff/appointments/{appointment_id}/no-show", response_model=AppointmentView)
def mark_no_show(
    appointment_id: str,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.STAFF, Role.ADMIN)
    try:
        value = BookingRepository(session).mark_no_show(
            appointment_id=appointment_id,
            staff_id=principal.user_id,
            key=idempotency_key,
        )
        return _appointment_view(value, expose_patient_id=False)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentView)
def cancel(
    appointment_id: str,
    session: SessionDependency,
    context: MutationAuthDependency,
    idempotency_key: IdempotencyKey,
) -> AppointmentView:
    principal = context.principal
    _allow(principal, Role.PATIENT, Role.STAFF, Role.ADMIN)
    try:
        value = BookingRepository(session).cancel(
            appointment_id=appointment_id,
            actor_id=principal.user_id,
            key=idempotency_key,
            patient_only=principal.role == Role.PATIENT,
        )
        return _appointment_view(value, expose_patient_id=principal.role == Role.PATIENT)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/appointments", response_model=AppointmentHistory)
def history(session: SessionDependency, context: AuthDependency) -> AppointmentHistory:
    principal = context.principal
    _allow(principal, Role.PATIENT)
    values = BookingRepository(session).history(patient_id=principal.user_id)
    return AppointmentHistory(items=[_appointment_view(value) for value in values])


@router.get("/appointments/{appointment_id}", response_model=AppointmentView)
def detail(appointment_id: str, session: SessionDependency, context: AuthDependency) -> AppointmentView:
    try:
        principal = context.principal
        value = BookingRepository(session).detail(appointment_id)
        if principal.role == Role.PATIENT and value.patient_id != principal.user_id:
            raise BookingForbiddenError("Appointment ownership mismatch")
        _allow(principal, Role.PATIENT, Role.STAFF, Role.ADMIN)
        return _appointment_view(value, expose_patient_id=principal.role == Role.PATIENT)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/staff/queue", response_model=AppointmentHistory)
def staff_queue(session: SessionDependency, context: AuthDependency) -> AppointmentHistory:
    _allow(context.principal, Role.STAFF, Role.ADMIN)
    values = BookingRepository(session).pending_queue()
    return AppointmentHistory(items=[_appointment_view(value, expose_patient_id=False) for value in values])
