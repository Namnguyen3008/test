from types import SimpleNamespace

import pytest
from google.genai import errors

from src.services.llm import (
    ALLOWED_GEMINI_MODELS,
    SAFE_HANDOFF_MESSAGE,
    GeminiRoundRobin,
    InMemoryRedisState,
    validate_model_pool,
)


class FakeModels:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = list(failures or [])

    async def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents))
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return SimpleNamespace(text=f"reply from {model}")


class FakeClient:
    def __init__(self, models):
        self.aio = SimpleNamespace(models=models)


class UnavailableRedis:
    async def incr(self, key):
        raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_round_robin_uses_only_approved_models():
    models = FakeModels()
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    results = [await router.generate("hello") for _ in range(4)]

    assert [result.model for result in results] == [
        ALLOWED_GEMINI_MODELS[0],
        ALLOWED_GEMINI_MODELS[1],
        ALLOWED_GEMINI_MODELS[0],
        ALLOWED_GEMINI_MODELS[1],
    ]
    assert {model for model, _ in models.calls} == set(ALLOWED_GEMINI_MODELS)


@pytest.mark.asyncio
async def test_quota_error_fails_over_once_to_other_approved_model():
    quota_error = errors.APIError(429, {"error": {"message": "quota"}})
    models = FakeModels(failures=[quota_error, quota_error, None])
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    result = await router.generate("hello")

    assert [model for model, _ in models.calls] == [
        ALLOWED_GEMINI_MODELS[0],
        ALLOWED_GEMINI_MODELS[0],
        ALLOWED_GEMINI_MODELS[1],
    ]
    assert result.model == ALLOWED_GEMINI_MODELS[1]
    assert result.failed_over is True


@pytest.mark.asyncio
async def test_non_quota_error_does_not_fail_over():
    auth_error = errors.APIError(401, {"error": {"message": "invalid key"}})
    models = FakeModels(failures=[auth_error])
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    with pytest.raises(errors.APIError):
        await router.generate("hello")

    assert len(models.calls) == 1


@pytest.mark.asyncio
async def test_both_quota_errors_return_safe_handoff():
    first = errors.APIError(429, {"error": {"message": "first quota"}})
    second = errors.APIError(429, {"error": {"message": "second quota"}})
    models = FakeModels(failures=[first, first, second, second])
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    result = await router.generate("hello")
    assert result.handoff is True
    assert result.text == SAFE_HANDOFF_MESSAGE
    assert len(models.calls) == 4
    assert {model for model, _ in models.calls} == set(ALLOWED_GEMINI_MODELS)


def test_missing_api_key_is_rejected():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiRoundRobin("")


@pytest.mark.asyncio
async def test_shared_redis_alternates_across_replicas_and_retry_increments_once():
    redis = InMemoryRedisState()
    quota = errors.APIError(429, {"error": {"message": "quota"}})
    first_models = FakeModels(failures=[quota, None])
    second_models = FakeModels()
    first = GeminiRoundRobin("test-key", client=FakeClient(first_models), redis=redis, max_attempts_per_model=2)
    second = GeminiRoundRobin("test-key", client=FakeClient(second_models), redis=redis)

    await first.generate("sensitive symptom")
    await second.generate("another symptom")

    assert first_models.calls[0][0] == ALLOWED_GEMINI_MODELS[0]
    assert second_models.calls[0][0] == ALLOWED_GEMINI_MODELS[1]
    assert await redis.get("vmec:gemini:generative:round_robin:v1") == "2"


def test_forbidden_model_configuration_is_rejected():
    with pytest.raises(ValueError, match="approved"):
        validate_model_pool(["gemini-flash-latest", ALLOWED_GEMINI_MODELS[1]])


@pytest.mark.asyncio
async def test_telemetry_is_allowlisted_and_contains_no_prompt():
    events = []
    router = GeminiRoundRobin("test-key", client=FakeClient(FakeModels()), telemetry_sink=events.append)
    prompt = "Patient Nguyen Van A phone 0900000000 has chest pain"
    result = await router.generate(prompt, purpose="routing")

    serialized = str(result.telemetry.safe_dict())
    assert prompt not in serialized
    assert "0900000000" not in serialized


@pytest.mark.asyncio
async def test_redis_outage_fails_closed_without_calling_a_model_or_leaking_prompt():
    models = FakeModels()
    events = []
    router = GeminiRoundRobin(
        "test-key",
        client=FakeClient(models),
        redis=UnavailableRedis(),
        telemetry_sink=events.append,
    )
    prompt = "sensitive patient symptom"

    result = await router.generate(prompt, purpose="routing")

    assert result.handoff
    assert result.text == SAFE_HANDOFF_MESSAGE
    assert models.calls == []
    assert events[0].selected_model == "unavailable"
    assert prompt not in str(events[0].safe_dict())
