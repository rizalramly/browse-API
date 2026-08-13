"""Retry + circuit-breaker behavior. No real sleeping, no real clock."""
from typing import Any

import pytest

from app.config import ProviderName, Vertical
from app.providers.base import (
    ProviderAuthError,
    ProviderError,
    SearchProvider,
    UnsupportedVerticalError,
)
from app.providers.resilience import CircuitBreaker, ResilientProvider
from app.schemas import SearchRequest


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FlakyProvider(SearchProvider):
    name = ProviderName.GENXNG

    def __init__(self, failures_before_success: int,
                 error: Exception | None = None) -> None:
        self.remaining_failures = failures_before_success
        self.calls = 0
        self.error = error or ProviderError("transient")

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise self.error
        return {"organic": []}


def make_resilient(
    inner: SearchProvider,
    breaker: CircuitBreaker | None = None,
    max_retries: int = 2,
) -> tuple[ResilientProvider, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    provider = ResilientProvider(
        inner,
        breaker or CircuitBreaker(failure_threshold=100),
        max_retries=max_retries,
        backoff_seconds=0.5,
        sleep=fake_sleep,
    )
    return provider, sleeps


# --- retries ---


async def test_retries_transient_failure_with_backoff() -> None:
    inner = FlakyProvider(failures_before_success=2)
    provider, sleeps = make_resilient(inner)
    blocks = await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    assert blocks == {"organic": []}
    assert inner.calls == 3
    assert sleeps == [0.5, 1.0]  # exponential backoff


async def test_gives_up_after_max_retries() -> None:
    inner = FlakyProvider(failures_before_success=10)
    provider, sleeps = make_resilient(inner, max_retries=2)
    with pytest.raises(ProviderError):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    assert inner.calls == 3  # initial + 2 retries
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    "error",
    [UnsupportedVerticalError("nope"), ProviderAuthError("bad key")],
)
async def test_non_retryable_errors_fail_immediately(error: Exception) -> None:
    inner = FlakyProvider(failures_before_success=10, error=error)
    provider, sleeps = make_resilient(inner)
    with pytest.raises(type(error)):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    assert inner.calls == 1
    assert sleeps == []


# --- circuit breaker ---


def test_breaker_opens_after_threshold_and_recovers() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=30, clock=clock)
    assert breaker.allow()
    for _ in range(3):
        breaker.record_failure()
    assert not breaker.allow()
    clock.now = 29.9
    assert not breaker.allow()
    clock.now = 30.0  # half-open: trial allowed
    assert breaker.allow()
    breaker.record_failure()  # trial fails -> reopens for another window
    assert not breaker.allow()
    clock.now = 60.0
    assert breaker.allow()
    breaker.record_success()  # trial succeeds -> closed
    assert breaker.allow()


async def test_open_breaker_short_circuits_without_calling_provider() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=30, clock=clock)
    inner = FlakyProvider(failures_before_success=10)
    provider, _ = make_resilient(inner, breaker=breaker, max_retries=0)

    with pytest.raises(ProviderError):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    calls_after_first = inner.calls

    with pytest.raises(ProviderError, match="circuit breaker is open"):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    assert inner.calls == calls_after_first  # inner was not touched


async def test_breaker_stops_retry_loop_when_it_opens() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=30, clock=clock)
    inner = FlakyProvider(failures_before_success=10)
    provider, sleeps = make_resilient(inner, breaker=breaker, max_retries=5)
    with pytest.raises(ProviderError):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    # breaker opened after 2 failures: no point burning the remaining retries
    assert inner.calls == 2
    assert sleeps == [0.5]
