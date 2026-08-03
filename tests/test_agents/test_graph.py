import json

import pytest

from src.agents.graph import agent
from src.services.llm import GeminiResult
from src.services.routing import RoutingContext, RoutingRecord


class FakeRetriever:
    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        return RoutingContext(
            (
                RoutingRecord(
                    "route-1",
                    f"Routing evidence for {query}",
                    "CARDIOLOGY",
                    ("GLOBAL-SOURCE-1",),
                ),
            ),
            "lexical-only",
            frozenset({"CARDIOLOGY"}),
        )


class EmptyRetriever:
    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        return RoutingContext((), "lexical-only", frozenset())


class FakeGemini:
    async def generate(self, prompt: str, *, purpose: str = "response") -> GeminiResult:
        payload = {
            "specialty_id": "CARDIOLOGY",
            "rationale": "Các dấu hiệu phù hợp để được đánh giá tại chuyên khoa tim mạch.",
            "confidence": 0.8,
            "citations": [{"source_id": "GLOBAL-SOURCE-1", "locator": "route-1"}],
            "action": "suggest_specialty",
        }
        return GeminiResult(text=json.dumps(payload), model="gemini-3.1-flash-lite")


@pytest.fixture
def grounded_runtime(monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_routing_retriever", lambda: FakeRetriever())
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())


@pytest.mark.asyncio
async def test_agent_grounded_flow(grounded_runtime):
    result = await agent.ainvoke({"query": "Đau ngực khi vận động"})
    assert "chuyên khoa tim mạch" in result["response"]
    assert result["metadata"]["model"] == "gemini-3.1-flash-lite"
    assert result["metadata"]["grounding_validation"] == "accepted"
    assert result["metadata"]["citations"][0]["source_id"] == "GLOBAL-SOURCE-1"
    assert "analysis" not in result


@pytest.mark.asyncio
async def test_agent_state_structure(grounded_runtime):
    result = await agent.ainvoke({"query": "Test query"})
    assert isinstance(result, dict)
    assert result["query"] == "Test query"
    assert result["retrieval_mode"] == "lexical-only"


@pytest.mark.asyncio
async def test_no_grounded_context_hands_off_without_gemini(monkeypatch):
    class ForbiddenGemini:
        async def generate(self, prompt: str, *, purpose: str = "response"):
            raise AssertionError("Gemini must not run without grounded context")

    monkeypatch.setattr("src.agents.nodes.example_node.get_routing_retriever", lambda: EmptyRetriever())
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: ForbiddenGemini())
    result = await agent.ainvoke({"query": "Nội dung không có trong corpus"})
    assert result["error"] == "no_grounded_context"
    assert "nhân viên VMEC" in result["response"]


@pytest.mark.asyncio
async def test_invalid_citation_is_rejected(monkeypatch):
    class InvalidCitationGemini:
        async def generate(self, prompt: str, *, purpose: str = "response") -> GeminiResult:
            return GeminiResult(
                text=json.dumps(
                    {
                        "specialty_id": "CARDIOLOGY",
                        "rationale": "Đi khám tim mạch.",
                        "confidence": 0.9,
                        "citations": [{"source_id": "INVENTED", "locator": "x"}],
                        "action": "suggest_specialty",
                    }
                ),
                model="gemini-3.5-flash-lite",
            )

    monkeypatch.setattr("src.agents.nodes.example_node.get_routing_retriever", lambda: FakeRetriever())
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: InvalidCitationGemini())
    result = await agent.ainvoke({"query": "Đau ngực"})
    assert result["error"] == "grounding_rejected"
    assert result["metadata"]["grounding_validation"] == "rejected"


@pytest.mark.asyncio
async def test_emergency_short_circuits_retrieval_and_gemini(monkeypatch):
    class ForbiddenDependency:
        async def generate(self, prompt: str, *, purpose: str = "response"):
            raise AssertionError("Gemini must not run for emergencies")

        async def retrieve(self, query: str, *, limit: int = 6):
            raise AssertionError("Retrieval must not run for emergencies")

    forbidden = ForbiddenDependency()
    monkeypatch.setattr("src.agents.nodes.example_node.get_routing_retriever", lambda: forbidden)
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: forbidden)
    result = await agent.ainvoke({"query": "Tôi đang đau ngực dữ dội và khó thở dữ dội"})
    assert result["emergency"] is True
    assert "115" in result["response"]
    assert result["metadata"]["routine_booking_blocked"] is True
    assert result["metadata"]["emergency_ruleset_version"] == "seed-v1"
