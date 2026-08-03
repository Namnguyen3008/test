import json

from src.agents.state import AgentState
from src.services.emergency import screen_emergency
from src.services.grounding import GroundingError, RoutingProposal, validate_routing
from src.services.llm import get_llm
from src.services.routing import get_routing_retriever

SAFE_HANDOFF = "Chưa đủ dữ liệu có nguồn để định hướng an toàn. Vui lòng liên hệ nhân viên VMEC để được hỗ trợ."


async def normalize_node(state: AgentState) -> dict:
    return {"query": state.get("query", "").strip()}


async def emergency_node(state: AgentState) -> dict:
    result = screen_emergency(state.get("query", ""))
    if not result.emergency:
        return {"emergency": False}
    return {
        "emergency": True,
        "response": result.action,
        "metadata": {
            "emergency_rule_ids": result.rule_ids,
            "emergency_ruleset_version": result.ruleset_version,
            "emergency_data_mode": result.data_mode,
            "routine_booking_blocked": True,
        },
    }


async def retrieve_node(state: AgentState) -> dict:
    context = await get_routing_retriever().retrieve(state.get("query", ""))
    metadata = {
        "retrieval_mode": context.mode,
        "retrieval_record_count": len(context.records),
        **context.diagnostics,
    }
    if not context.records:
        return {"response": SAFE_HANDOFF, "error": "no_grounded_context", "metadata": metadata}
    return {
        "retrieval_records": [
            {
                "record_id": record.record_id,
                "text": record.text,
                "specialty_id": record.specialty_id,
                "source_ids": list(record.source_ids),
            }
            for record in context.records
        ],
        "retrieval_mode": context.mode,
        "allowed_specialty_ids": sorted(context.allowed_specialty_ids),
        "valid_source_ids": sorted(context.valid_source_ids),
        "metadata": metadata,
    }


def _routing_prompt(state: AgentState) -> str:
    context = json.dumps(state.get("retrieval_records", []), ensure_ascii=False, separators=(",", ":"))
    return (
        "Bạn là bộ định tuyến chuyên khoa VMEC. Chỉ dùng CONTEXT. Không chẩn đoán hoặc điều trị. "
        "Trả đúng một JSON object, không markdown, chỉ gồm specialty_id, rationale, confidence, citations, action. "
        "action là suggest_specialty, clarify hoặc handoff. Mỗi citation gồm source_id và locator. "
        f"USER_QUERY={state.get('query', '')}\nCONTEXT={context}"
    )


async def generate_node(state: AgentState) -> dict:
    result = await get_llm().generate(_routing_prompt(state), purpose="grounded_routing")
    metadata = dict(state.get("metadata", {}))
    metadata.update(
        {
            "model": result.model,
            "failed_over": result.failed_over,
            "handoff": result.handoff,
            "model_call_id": result.model_call_id,
        }
    )
    if result.handoff:
        return {"response": result.text, "error": "model_handoff", "metadata": metadata}
    return {"model_output": result.text, "metadata": metadata}


async def validate_node(state: AgentState) -> dict:
    metadata = dict(state.get("metadata", {}))
    try:
        proposal = RoutingProposal.model_validate_json(state.get("model_output", ""))
        if proposal.action != "suggest_specialty":
            metadata["routing_action"] = proposal.action
            return {"response": SAFE_HANDOFF, "error": proposal.action, "metadata": metadata}
        response = validate_routing(
            proposal,
            allowed_specialty_ids=set(state.get("allowed_specialty_ids", [])),
            valid_source_ids=set(state.get("valid_source_ids", [])),
        )
    except (ValueError, GroundingError):
        metadata["grounding_validation"] = "rejected"
        return {"response": SAFE_HANDOFF, "error": "grounding_rejected", "metadata": metadata}
    metadata.update(
        {
            "grounding_validation": "accepted",
            "routing_action": proposal.action,
            "specialty_id": proposal.specialty_id,
            "citations": [citation.model_dump() for citation in proposal.citations],
        }
    )
    return {
        "response": response,
        "metadata": metadata,
    }
