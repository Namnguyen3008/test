import pytest

from src.security.rate_limit import (
    DistributedRateLimiter,
    InMemoryWindowBackend,
    RateLimitUnavailableError,
)


class FailingBackend:
    async def hit(self, key: str, window_seconds: int) -> int:
        raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_distributed_rate_limit_enforces_action_window() -> None:
    limiter = DistributedRateLimiter(InMemoryWindowBackend())

    assert await limiter.allow("login:subject", limit=2, window_seconds=60)
    assert await limiter.allow("login:subject", limit=2, window_seconds=60)
    assert not await limiter.allow("login:subject", limit=2, window_seconds=60)
    assert await limiter.allow("register:subject", limit=2, window_seconds=60)


@pytest.mark.asyncio
async def test_development_can_use_bounded_local_fallback() -> None:
    limiter = DistributedRateLimiter(FailingBackend(), require_distributed=False)

    assert await limiter.allow("login:subject", limit=1, window_seconds=60)
    assert not await limiter.allow("login:subject", limit=1, window_seconds=60)


@pytest.mark.asyncio
async def test_production_fails_closed_when_redis_rate_limit_is_unavailable() -> None:
    limiter = DistributedRateLimiter(FailingBackend(), require_distributed=True)

    with pytest.raises(RateLimitUnavailableError):
        await limiter.allow("login:subject", limit=10, window_seconds=60)
