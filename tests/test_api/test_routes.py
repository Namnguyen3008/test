import pytest

from src.services.llm import GeminiResult


class FakeGemini:
    async def generate(self, prompt: str, *, purpose: str = "response") -> GeminiResult:
        return GeminiResult(text="Hello from Gemini", model="gemini-3.5-flash-lite")


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "env" not in data


@pytest.mark.asyncio
async def test_readiness_and_security_headers(client):
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_chat_uses_gemini(client, monkeypatch):
    monkeypatch.setattr("src.agents.nodes.example_node.get_llm", lambda: FakeGemini())
    response = await client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["response"].startswith("Hello from Gemini")
    assert "analysis" not in response.json()


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
