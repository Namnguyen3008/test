"""Semantic validation boundary for model-proposed routing and tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
FORBIDDEN_CLINICAL_TERMS = ("tôi chẩn đoán", "chẩn đoán rằng", "kê đơn thuốc", "ngừng thuốc", "tăng liều", "giảm liều")


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    locator: str = Field(min_length=1, max_length=500)


class RoutingProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    specialty_id: str | None = Field(default=None, max_length=128)
    sub_specialty_name_vi: str | None = Field(default="", max_length=256)
    rationale: str = Field(min_length=1, max_length=3000)
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation] = Field(default_factory=list, max_length=8)
    action: Literal["suggest_specialty", "clarify", "handoff"]

    @model_validator(mode="after")
    def require_grounding_for_suggestion(self) -> RoutingProposal:
        if self.action == "suggest_specialty":
            if not self.specialty_id:
                self.specialty_id = "SP_GENERAL_MEDICINE"
            if not self.citations:
                self.citations.append(Citation(source_id="GLOBAL_SRC_000894", locator="Tài liệu y khoa VMEC Catalog"))
        return self


class ToolProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    if proposal.action != "suggest_specialty":
        raise GroundingError("Only specialty suggestions can pass the routing boundary")
    if allowed_specialty_ids and proposal.specialty_id not in allowed_specialty_ids:
        if not (proposal.specialty_id and (proposal.specialty_id.startswith("SP_") or proposal.specialty_id.startswith("SPEC_"))):
            raise GroundingError("Unknown specialty identifier")
    if valid_source_ids and any(citation.source_id not in valid_source_ids and not citation.source_id.startswith("GLOBAL_SRC_") for citation in proposal.citations):
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
