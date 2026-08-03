from src.agents.state import AgentState
from src.services.emergency import screen_emergency
from src.services.llm import get_llm

DISCLAIMER = "Thông tin này chỉ hỗ trợ định hướng chuyên khoa, không thay thế chẩn đoán hoặc điều trị của bác sĩ."


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


async def respond_node(state: AgentState) -> dict:
    result = await get_llm().generate(state.get("query", ""), purpose="routing")
    response = result.text if result.handoff else f"{result.text}\n\n{DISCLAIMER}"
    return {
        "response": response,
        "metadata": {
            "model": result.model,
            "failed_over": result.failed_over,
            "handoff": result.handoff,
            "model_call_id": result.model_call_id,
        },
    }
