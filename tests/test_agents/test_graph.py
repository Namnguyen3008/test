import pytest

from src.agents.graph import agent
from src.services.llm import GeminiResult


class FakeGemini:
    async def generate(self, prompt: str, *, purpose: str = "response") -> GeminiResult:
        return GeminiResult(text=f"Gemini: {prompt}", model="gemini-3.1-flash-lite")


@pytest.mark.asyncio
async def test_agent_basic_flow(monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    result = await agent.ainvoke({"query": "Hello"})
    assert result["response"].startswith("Gemini: Hello")
    assert result["metadata"]["model"] == "gemini-3.1-flash-lite"


@pytest.mark.asyncio
async def test_agent_state_structure(monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    result = await agent.ainvoke({"query": "Test query"})
    assert isinstance(result, dict)
    assert "query" in result


@pytest.mark.asyncio
async def test_emergency_short_circuits_gemini(monkeypatch):
    class ForbiddenGemini:
        async def generate(self, prompt: str, *, purpose: str = "response"):
            raise AssertionError("Gemini must not run for emergencies")

    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: ForbiddenGemini())
    result = await agent.ainvoke({"query": "Tôi đang đau ngực dữ dội và khó thở dữ dội"})
    assert result["emergency"] is True
    assert "115" in result["response"]
    assert result["metadata"]["routine_booking_blocked"] is True
