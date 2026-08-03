"""Public booking API contracts without clinical free text or PHI."""

from datetime import datetime

from pydantic import BaseModel, Field


class SlotView(BaseModel):
    id: str
    specialty_id: str | None
    facility_id: str | None
    practitioner_id: str | None
    starts_at: datetime
    ends_at: datetime


class AppointmentView(BaseModel):
    id: str
    slot_id: str
    proposed_slot_id: str | None
    patient_id: str
    status: str
    hold_expires_at: datetime | None
    patient_confirmed_at: datetime | None
    patient_reconfirmed_at: datetime | None
    staff_approved_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class HoldRequest(BaseModel):
    slot_id: str
    ttl_seconds: int = Field(default=300, ge=30, le=900)


class StaffDecisionRequest(BaseModel):
    approve: bool


class RescheduleRequest(BaseModel):
    slot_id: str
    ttl_seconds: int = Field(default=300, ge=30, le=900)


class AppointmentHistory(BaseModel):
    items: list[AppointmentView]


class AvailabilityResponse(BaseModel):
    items: list[SlotView]
