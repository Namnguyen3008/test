"""Semantic validation boundary for model-proposed routing and tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER_VI = "Thông tin này chỉ hỗ trợ định hướng chuyên khoa, không thay thế chẩn đoán hoặc điều trị của bác sĩ."
ALLOWED_TOOL_NAMES = frozenset(
    {
        "search_slots",
        "hold_slot",
        "confirm_patient_choice",
        "cancel_appointment",
        "request_reschedule",
        "respond_to_reschedule_offer",
        "get_appointment_status",
        "handoff_to_staff",
    }
)
FORBIDDEN_CLINICAL_TERMS = ("chẩn đoán", "kê đơn", "ngừng thuốc", "tăng liều", "giảm liều")


class Citation(BaseModel):
    source_id: str = Field(min_length=1, max_length=128)
    locator: str = Field(min_length=1, max_length=500)


class RoutingProposal(BaseModel):
    specialty_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation] = Field(min_length=1, max_length=8)
    action: Literal["suggest_specialty", "clarify", "handoff"]


class ToolProposal(BaseModel):
    name: str
    arguments: dict[str, str | int | bool]


class GroundingError(ValueError):
    pass


def validate_routing(
    proposal: RoutingProposal,
    *,
    allowed_specialty_ids: set[str],
    valid_source_ids: set[str],
    minimum_confidence: float = 0.65,
) -> str:
    if proposal.specialty_id not in allowed_specialty_ids:
        raise GroundingError("Unknown specialty identifier")
    if any(citation.source_id not in valid_source_ids for citation in proposal.citations):
        raise GroundingError("Unknown or unmapped citation")
    normalized = proposal.rationale.casefold()
    if any(term in normalized for term in FORBIDDEN_CLINICAL_TERMS):
        raise GroundingError("Diagnostic or treatment claim rejected")
    if proposal.confidence < minimum_confidence:
        raise GroundingError("Confidence requires clarification or human handoff")
    return f"{proposal.rationale}\n\n{DISCLAIMER_VI}"


def validate_tool(proposal: ToolProposal) -> ToolProposal:
    if proposal.name not in ALLOWED_TOOL_NAMES:
        raise GroundingError("Tool is not allowlisted")
    if any(key.lower() in {"sql", "query", "model", "api_key"} for key in proposal.arguments):
        raise GroundingError("Tool arguments contain a forbidden control field")
    return proposal
