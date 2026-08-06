import time

from fastapi import APIRouter, HTTPException

from src.agents.graph import agent
from src.models.schemas import ChatRequest, ChatResponse
from src.observability import deep_telemetry

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent."""
    start_time = time.monotonic()
    try:
        history_list = [m.model_dump() for m in request.history]
        result = await agent.ainvoke({"query": request.message, "history": history_list})
        duration_ms = (time.monotonic() - start_time) * 1000
        
        resp_text = str(result.get("response", ""))
        emergency = bool(result.get("emergency", False))
        metadata = dict(result.get("metadata", {}))

        try:
            deep_telemetry.record_chat(
                user_msg=request.message,
                history_len=len(history_list),
                response_text=resp_text,
                emergency=emergency,
                metadata=metadata,
                duration_ms=duration_ms,
            )
        except Exception:
            pass

        return ChatResponse(
            response=resp_text,
            emergency=emergency,
            metadata=metadata,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="AI service is temporarily unavailable",
        ) from exc


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}
