import pytest

from src.services.llm import GeminiResult


class FakeGemini:
    async def generate(self, prompt: str) -> GeminiResult:
        return GeminiResult(text="Hello from Gemini", model="gemini-3.5-flash-lite")


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_chat_uses_gemini(client, monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    response = await client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["response"] == "Hello from Gemini"


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
