"""Action-aware Redis rate limiting with a bounded local safety fallback."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from typing import Protocol


class RateLimitBackend(Protocol):
    async def hit(self, key: str, window_seconds: int) -> int: ...


class InMemoryWindowBackend:
    """Per-process fallback used in tests and when development Redis is absent."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, window_seconds: int) -> int:
        async with self._lock:
            count, expires_at = self._windows.get(key, (0, 0.0))
            now = self._clock()
            if expires_at <= now:
                count, expires_at = 0, now + window_seconds
            count += 1
            self._windows[key] = (count, expires_at)
            return count


class RateLimitUnavailableError(RuntimeError):
    pass


class DistributedRateLimiter:
    """Enforce a local ceiling plus a cross-replica Redis ceiling."""

    def __init__(
        self,
        distributed: RateLimitBackend,
        *,
        local: RateLimitBackend | None = None,
        require_distributed: bool = False,
    ) -> None:
        self._distributed = distributed
        self._local = local or InMemoryWindowBackend()
        self._require_distributed = require_distributed

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("Rate limit and window must be positive")
        if await self._local.hit(key, window_seconds) > limit:
            return False
        try:
            return await self._distributed.hit(key, window_seconds) <= limit
        except Exception as exc:
            if self._require_distributed:
                raise RateLimitUnavailableError("Distributed rate limiter unavailable") from exc
            return True

    async def aclose(self) -> None:
        closer = getattr(self._distributed, "aclose", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result
