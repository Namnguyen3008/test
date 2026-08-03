from types import SimpleNamespace

import pytest
from google.genai import errors

from src.services.llm import ALLOWED_GEMINI_MODELS, GeminiRoundRobin


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
    models = FakeModels(failures=[quota_error, None])
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    result = await router.generate("hello")

    assert [model for model, _ in models.calls] == list(ALLOWED_GEMINI_MODELS)
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
async def test_both_quota_errors_are_propagated_after_one_failover():
    first = errors.APIError(429, {"error": {"message": "first quota"}})
    second = errors.APIError(429, {"error": {"message": "second quota"}})
    models = FakeModels(failures=[first, second])
    router = GeminiRoundRobin("test-key", client=FakeClient(models))

    with pytest.raises(errors.APIError):
        await router.generate("hello")

    assert len(models.calls) == 2
    assert {model for model, _ in models.calls} == set(ALLOWED_GEMINI_MODELS)


def test_missing_api_key_is_rejected():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiRoundRobin("")
