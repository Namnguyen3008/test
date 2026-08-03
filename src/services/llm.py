"""PHI-safe distributed Gemini gateway with an exact model allowlist."""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Final, Protocol

from google import genai
from google.genai import errors, types
from redis.asyncio import Redis

from src.config import get_settings

ALLOWED_GEMINI_MODELS: Final[tuple[str, str]] = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
)
SAFE_HANDOFF_MESSAGE: Final[str] = (
    "Hệ thống AI đang tạm thời gián đoạn. Vui lòng liên hệ nhân viên VMEC để được hỗ trợ an toàn."
)


class RedisState(Protocol):
    async def incr(self, key: str) -> int: ...
    async def get(self, key: str) -> str | bytes | None: ...
    async def set(self, key: str, value: str, *, ex: int | None = None) -> object: ...
    async def delete(self, key: str) -> object: ...


class InMemoryRedisState:
    """Test/development adapter. Share one instance to simulate many replicas."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._expiries: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def incr(self, key: str) -> int:
        async with self._lock:
            self._expire(key)
            value = int(self._values.get(key, "0")) + 1
            self._values[key] = str(value)
            return value

    async def get(self, key: str) -> str | None:
        async with self._lock:
            self._expire(key)
            return self._values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        async with self._lock:
            self._values[key] = value
            if ex is not None:
                self._expiries[key] = time.monotonic() + ex
            return True

    async def delete(self, key: str) -> int:
        async with self._lock:
            existed = key in self._values
            self._values.pop(key, None)
            self._expiries.pop(key, None)
            return int(existed)

    def _expire(self, key: str) -> None:
        if self._expiries.get(key, float("inf")) <= time.monotonic():
            self._values.pop(key, None)
            self._expiries.pop(key, None)


class RedisAsyncState:
    """Production adapter backed by Redis atomic INCR."""

    def __init__(self, url: str) -> None:
        self._client = Redis.from_url(url, decode_responses=True)

    async def incr(self, key: str) -> int:
        return int(await self._client.incr(key))

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        return str(value) if value is not None else None

    async def set(self, key: str, value: str, *, ex: int | None = None) -> object:
        return await self._client.set(key, value, ex=ex)

    async def delete(self, key: str) -> object:
        return await self._client.delete(key)


@dataclass(frozen=True)
class ModelTelemetry:
    model_call_id: str
    purpose: str
    selected_model: str
    attempted_models: tuple[str, ...]
    status: str
    failure_code: str | None
    latency_ms: int

    def safe_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GeminiResult:
    text: str
    model: str
    failed_over: bool = False
    handoff: bool = False
    model_call_id: str = ""
    telemetry: ModelTelemetry | None = None


def validate_model_pool(models: tuple[str, ...] | list[str]) -> tuple[str, str]:
    if tuple(models) != ALLOWED_GEMINI_MODELS:
        raise ValueError("Gemini model configuration must exactly match the approved ordered allowlist")
    return ALLOWED_GEMINI_MODELS


def _transient_failure(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    return isinstance(exc, errors.APIError) and exc.code in {408, 429, 500, 502, 503, 504}


class GeminiRoundRobin:
    """Select once per logical call using Redis; retry/failover never reselect."""

    def __init__(
        self,
        api_key: str,
        client=None,
        *,
        redis: RedisState | None = None,
        round_robin_key: str = "vmec:gemini:generative:round_robin:v1",
        max_attempts_per_model: int = 2,
        timeout_seconds: float = 30.0,
        failure_threshold: int = 5,
        recovery_seconds: int = 60,
        telemetry_sink: Callable[[ModelTelemetry], Awaitable[None] | None] | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        if max_attempts_per_model < 1:
            raise ValueError("max_attempts_per_model must be positive")
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self._redis = redis or InMemoryRedisState()
        self._round_robin_key = round_robin_key
        self._max_attempts = max_attempts_per_model
        self._timeout = timeout_seconds
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._telemetry_sink = telemetry_sink

    async def _select_models(self) -> tuple[str, str]:
        counter = await self._redis.incr(self._round_robin_key)
        index = (counter - 1) % 2
        return ALLOWED_GEMINI_MODELS[index], ALLOWED_GEMINI_MODELS[1 - index]

    async def _generate_with(self, model: str, prompt: str) -> str:
        if model not in ALLOWED_GEMINI_MODELS:
            raise ValueError("Forbidden Gemini model")
        response = await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=2048),
            ),
            timeout=self._timeout,
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty structured response")
        return response.text

    def _health_key(self, model: str) -> str:
        return f"vmec:gemini:model_health:{model}"

    async def _circuit_open(self, model: str) -> bool:
        raw = await self._redis.get(self._health_key(model))
        if raw is None:
            return False
        if isinstance(raw, bytes):
            raw = raw.decode()
        state = json.loads(raw)
        return state.get("state") == "open" and time.time() - float(state["opened_at"]) < self._recovery_seconds

    async def _record_failure(self, model: str) -> None:
        key = self._health_key(model)
        raw = await self._redis.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode()
        state = json.loads(raw) if raw else {}
        failures = int(state.get("failures", 0)) + 1
        payload: dict[str, object] = {"failures": failures, "state": "closed"}
        if failures >= self._failure_threshold:
            payload.update({"state": "open", "opened_at": time.time()})
        await self._redis.set(key, json.dumps(payload), ex=self._recovery_seconds * 2)

    async def _emit(self, event: ModelTelemetry) -> None:
        if self._telemetry_sink:
            result = self._telemetry_sink(event)
            if result is not None:
                await result

    async def generate(self, prompt: str, *, purpose: str = "response") -> GeminiResult:
        call_id = str(uuid.uuid4())
        started = time.monotonic()
        try:
            primary, alternate = await self._select_models()
        except Exception as exc:
            event = ModelTelemetry(
                call_id,
                purpose,
                "unavailable",
                (),
                "safe_handoff",
                type(exc).__name__,
                int((time.monotonic() - started) * 1000),
            )
            await self._emit(event)
            return GeminiResult(SAFE_HANDOFF_MESSAGE, "", False, True, call_id, event)
        attempted: list[str] = []
        failure_code: str | None = None
        for model_index, model in enumerate((primary, alternate)):
            if await self._circuit_open(model):
                failure_code = "circuit_open"
                continue
            for attempt in range(self._max_attempts):
                if model not in attempted:
                    attempted.append(model)
                try:
                    text = await self._generate_with(model, prompt)
                    await self._redis.delete(self._health_key(model))
                    event = ModelTelemetry(
                        call_id,
                        purpose,
                        primary,
                        tuple(attempted),
                        "ok",
                        None,
                        int((time.monotonic() - started) * 1000),
                    )
                    await self._emit(event)
                    return GeminiResult(text, model, model_index == 1, False, call_id, event)
                except Exception as exc:
                    if not _transient_failure(exc):
                        raise
                    failure_code = type(exc).__name__
                    await self._record_failure(model)
                    if attempt + 1 < self._max_attempts:
                        await asyncio.sleep(random.uniform(0.005, 0.02) * (2**attempt))
        event = ModelTelemetry(
            call_id,
            purpose,
            primary,
            tuple(attempted),
            "safe_handoff",
            failure_code,
            int((time.monotonic() - started) * 1000),
        )
        await self._emit(event)
        return GeminiResult(SAFE_HANDOFF_MESSAGE, primary, alternate in attempted, True, call_id, event)

    async def aclose(self) -> None:
        if hasattr(self._client.aio, "aclose"):
            await self._client.aio.aclose()
        if hasattr(self._client, "close"):
            self._client.close()


@lru_cache
def get_llm() -> GeminiRoundRobin:
    settings = get_settings()
    validate_model_pool(tuple(settings.gemini_generative_models.split(",")))
    return GeminiRoundRobin(
        api_key=settings.gemini_api_key.get_secret_value(),
        redis=RedisAsyncState(settings.redis_url),
        round_robin_key=settings.gemini_round_robin_redis_key,
        max_attempts_per_model=settings.gemini_max_attempts_per_model,
        timeout_seconds=settings.gemini_call_timeout_seconds,
    )
