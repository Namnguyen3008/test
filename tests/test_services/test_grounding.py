import pytest

from src.services.grounding import (
    DISCLAIMER_VI,
    Citation,
    GroundingError,
    RoutingProposal,
    ToolProposal,
    validate_routing,
    validate_tool,
)


def proposal(**changes):
    values = {
        "specialty_id": "cardiology",
        "rationale": "Các dấu hiệu phù hợp để được đánh giá tại chuyên khoa tim mạch.",
        "confidence": 0.8,
        "citations": [Citation(source_id="SRC-1", locator="section 2")],
        "action": "suggest_specialty",
    }
    values.update(changes)
    return RoutingProposal(**values)


def test_grounded_routing_requires_allowlisted_specialty_source_and_disclaimer():
    response = validate_routing(proposal(), allowed_specialty_ids={"cardiology"}, valid_source_ids={"SRC-1"})
    assert DISCLAIMER_VI in response


@pytest.mark.parametrize(
    "candidate",
    [
        proposal(specialty_id="invented"),
        proposal(citations=[Citation(source_id="fake", locator="x")]),
        proposal(confidence=0.1),
        proposal(rationale="Chẩn đoán bệnh và kê đơn ngay"),
    ],
)
def test_invalid_or_unsafe_routing_is_rejected(candidate):
    with pytest.raises(GroundingError):
        validate_routing(candidate, allowed_specialty_ids={"cardiology"}, valid_source_ids={"SRC-1"})


def test_tool_allowlist_and_control_fields():
    assert validate_tool(ToolProposal(name="search_slots", arguments={"specialty_id": "cardiology"}))
    with pytest.raises(GroundingError):
        validate_tool(ToolProposal(name="execute_sql", arguments={"sql": "DROP TABLE"}))


def test_structured_contract_forbids_chain_of_thought_or_extra_fields():
    with pytest.raises(ValueError):
        RoutingProposal.model_validate(
            {
                **proposal().model_dump(),
                "analysis": "private reasoning must never cross the boundary",
            }
        )


def test_clarify_can_omit_specialty_and_citations_but_cannot_pass_as_route():
    candidate = RoutingProposal(
        specialty_id=None,
        rationale="Cần thêm thông tin về thời điểm xuất hiện triệu chứng.",
        confidence=0.3,
        citations=[],
        action="clarify",
    )
    with pytest.raises(GroundingError):
        validate_routing(candidate, allowed_specialty_ids={"cardiology"}, valid_source_ids={"SRC-1"})
