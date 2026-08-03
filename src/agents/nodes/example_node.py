from src.agents.state import AgentState
from src.services.llm import get_llm


async def analyze_node(state: AgentState) -> dict:
    """Prepare lightweight context before generating the answer."""
    query = state.get("query", "")
    return {"analysis": f"User request: {query}"}


async def respond_node(state: AgentState) -> dict:
    """Generate a response through the restricted Gemini router."""
    error = state.get("error")
    if error:
        return {"response": f"Error: {error}"}

    query = state.get("query", "")
    result = await get_llm().generate(query)
    return {
        "response": result.text,
        "metadata": {
            "model": result.model,
            "quota_failover": result.failed_over,
        },
    }
