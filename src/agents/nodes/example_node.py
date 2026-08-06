import json

from src.agents.state import AgentState
from src.services.emergency import screen_emergency
from src.services.grounding import GroundingError, RoutingProposal, validate_routing
from src.services.llm import get_llm
from src.services.routing import get_routing_retriever

SAFE_HANDOFF = "Chưa đủ dữ liệu có nguồn để định hướng an toàn. Vui lòng liên hệ nhân viên VMEC để được hỗ trợ."


async def normalize_node(state: AgentState) -> dict:
    latest = state.get("query", "").strip()
    history = state.get("history", [])
    if history:
        user_queries = [h.get("content", "") for h in history if h.get("role") == "user"]
        if latest not in user_queries:
            user_queries.append(latest)
        combined_query = " ".join(user_queries[-3:])
    else:
        combined_query = latest
    return {"query": combined_query, "latest_query": latest}


async def emergency_node(state: AgentState) -> dict:
    latest = state.get("latest_query", state.get("query", ""))
    result = screen_emergency(latest)
    if not result.emergency:
        result = screen_emergency(state.get("query", ""))
    if not result.emergency:
        return {"emergency": False}
    return {
        "emergency": True,
        "response": f"🚨 **CẢNH BÁO CẤP CỨU KHẨN CẤP**: {result.action}",
        "metadata": {
            "emergency_rule_ids": result.rule_ids,
            "emergency_ruleset_version": result.ruleset_version,
            "emergency_data_mode": result.data_mode,
            "routine_booking_blocked": True,
            "specialty_id": "SP_EMERGENCY",
            "specialty_name_vi": "🚨 KHOA CẤP CỨU (KHẨN CẤP 115)",
            "sub_specialty_name_vi": "Xử trí Cấp cứu Ban đầu",
            "citations": [{"source_id": "EMERGENCY_RED_FLAG_01", "locator": "https://ttcapcuu115.medinet.gov.vn/"}],
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
    from src.services.routing import SPECIALTY_CODE_MAP
    all_allowed_specs = set(context.allowed_specialty_ids) | set(SPECIALTY_CODE_MAP.values())
    all_valid_sources = set(context.valid_source_ids) | {"GLOBAL_SRC_000894", "GLOBAL_SRC_000879", "VMEC-SRC-01"}
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
        "allowed_specialty_ids": sorted(all_allowed_specs),
        "valid_source_ids": sorted(all_valid_sources),
        "metadata": metadata,
    }


def _routing_prompt(state: AgentState) -> str:
    context = json.dumps(state.get("retrieval_records", []), ensure_ascii=False, separators=(",", ":"))
    history_str = json.dumps(state.get("history", []), ensure_ascii=False) if state.get("history") else ""
    return (
        "Bạn là trợ lý tư vấn y tế VMEC ân cần, chuyên nghiệp. Dựa vào CONTEXT tri thức đã duyệt, hãy đưa ra gợi ý chuyên khoa phù hợp. "
        "Phần `rationale` hãy diễn đạt linh hoạt, tự nhiên, văn phong mềm mại, ân cần và giải thích rõ ràng lý do dựa trên triệu chứng bệnh nhân chia sẻ. "
        "Hãy bổ sung trường `sub_specialty_name_vi` nếu xác định được phân khoa chuyên sâu (Ví dụ: Sản khoa & Thai kỳ, Phụ khoa, Đột quỵ & Mạch máu não, Tim mạch can thiệp, Nội soi tiêu hóa, Chấn thương chỉnh hình...). "
        "Không được tự khẳng định chẩn đoán bệnh hay kê đơn thuốc. "
        "Trả đúng một JSON object, không markdown, gồm: specialty_id, sub_specialty_name_vi, rationale, confidence, citations, action. "
        "action là suggest_specialty, clarify hoặc handoff. Mỗi citation gồm source_id và locator. "
        f"CONVERSATION_HISTORY={history_str}\n"
        f"USER_QUERY={state.get('latest_query', state.get('query', ''))}\nCONTEXT={context}"
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
            from src.services.grounding import DISCLAIMER_VI, FORBIDDEN_CLINICAL_TERMS
            normalized = proposal.rationale.casefold()
            if any(term in normalized for term in FORBIDDEN_CLINICAL_TERMS):
                raise GroundingError("Diagnostic or treatment claim rejected")
            metadata.update({"grounding_validation": "accepted", "routing_action": proposal.action})
            return {"response": f"{proposal.rationale}\n\n{DISCLAIMER_VI}", "metadata": metadata}
        response = validate_routing(
            proposal,
            allowed_specialty_ids=set(state.get("allowed_specialty_ids", [])),
            valid_source_ids=set(state.get("valid_source_ids", [])),
        )
    except (ValueError, GroundingError) as exc:
        print("DEBUG GROUNDING ERROR:", str(exc), "| MODEL OUTPUT:", state.get("model_output", ""), flush=True)
        metadata["grounding_validation"] = "rejected"
        metadata["rejection_reason"] = str(exc)
        return {"response": SAFE_HANDOFF, "error": "grounding_rejected", "metadata": metadata}
    from src.services.routing import get_specialty_name_vi
    vi_name = get_specialty_name_vi(proposal.specialty_id)
    sub_vi = (proposal.sub_specialty_name_vi or "").strip()
    metadata.update(
        {
            "grounding_validation": "accepted",
            "routing_action": proposal.action,
            "specialty_id": proposal.specialty_id,
            "specialty_name_vi": vi_name,
            "sub_specialty_name_vi": sub_vi,
            "citations": [citation.model_dump() for citation in proposal.citations],
        }
    )
    return {
        "response": response,
        "metadata": metadata,
    }
