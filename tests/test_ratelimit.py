"""Token-bucket rate limiter against fakeredis (Lua path included)."""
from fakeredis import FakeAsyncRedis

from app.ratelimit import RateLimiter


async def test_bucket_allows_burst_then_denies() -> None:
    limiter = RateLimiter(FakeAsyncRedis(), qps=1.0, burst=2)
    now = 1_000_000_000_000
    first, _ = await limiter.check(1, now_ms=now)
    second, _ = await limiter.check(1, now_ms=now)
    third, retry = await limiter.check(1, now_ms=now)
    assert first and second
    assert not third
    assert retry >= 1


async def test_bucket_refills_over_time() -> None:
    limiter = RateLimiter(FakeAsyncRedis(), qps=1.0, burst=1)
    now = 1_000_000_000_000
    allowed, _ = await limiter.check(1, now_ms=now)
    assert allowed
    denied, _ = await limiter.check(1, now_ms=now)
    assert not denied
    refilled, _ = await limiter.check(1, now_ms=now + 1_000)
    assert refilled


async def test_buckets_are_per_key() -> None:
    limiter = RateLimiter(FakeAsyncRedis(), qps=1.0, burst=1)
    now = 1_000_000_000_000
    assert (await limiter.check(1, now_ms=now))[0]
    assert not (await limiter.check(1, now_ms=now))[0]
    assert (await limiter.check(2, now_ms=now))[0]


async def test_qps_zero_disables_limiting() -> None:
    limiter = RateLimiter(FakeAsyncRedis(), qps=0, burst=1)
    for _ in range(20):
        allowed, retry = await limiter.check(1)
        assert allowed
        assert retry == 0
