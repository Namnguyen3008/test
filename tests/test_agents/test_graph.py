import pytest

from src.agents.graph import agent
from src.services.llm import GeminiResult


class FakeGemini:
    async def generate(self, prompt: str) -> GeminiResult:
        return GeminiResult(text=f"Gemini: {prompt}", model="gemini-3.1-flash-lite")


@pytest.mark.asyncio
async def test_agent_basic_flow(monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    result = await agent.ainvoke({"query": "Hello"})
    assert result["response"] == "Gemini: Hello"
    assert result["metadata"]["model"] == "gemini-3.1-flash-lite"


@pytest.mark.asyncio
async def test_agent_state_structure(monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    result = await agent.ainvoke({"query": "Test query"})
    assert isinstance(result, dict)
    assert "query" in result
