"""Resilience wrapper: retries with exponential backoff + a circuit breaker.

Every provider handed out by the registry is wrapped in ResilientProvider, so
endpoints never talk to a raw backend. Non-transient failures (unsupported
vertical, missing configuration, rejected credentials) are never retried and
do not trip the breaker.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import Vertical
from app.metrics import PROVIDER_RETRIES
from app.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfiguredError,
    SearchProvider,
    UnsupportedVerticalError,
)
from app.schemas import SearchRequest

logger = logging.getLogger(__name__)

NON_RETRYABLE = (UnsupportedVerticalError, ProviderNotConfiguredError, ProviderAuthError)


class CircuitBreaker:
    """Consecutive-failure breaker: open after N failures, half-open after a
    recovery period (one trial call decides whether it closes or reopens)."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, failure_threshold)
        self._recovery = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # recovery elapsed -> half-open: let a trial call through
        return self._clock() - self._opened_at < self._recovery

    def allow(self) -> bool:
        return not self.is_open

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class ResilientProvider(SearchProvider):
    def __init__(
        self,
        inner: SearchProvider,
        breaker: CircuitBreaker,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._breaker = breaker
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_seconds
        self._sleep = sleep
        self.name = inner.name

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        if not self._breaker.allow():
            raise ProviderError(f"{self.name.value} circuit breaker is open")

        attempt = 0
        while True:
            try:
                blocks = await self._inner.search(request, vertical)
            except NON_RETRYABLE:
                raise
            except ProviderError as exc:
                self._breaker.record_failure()
                if attempt >= self._max_retries or not self._breaker.allow():
                    raise
                delay = self._backoff * (2**attempt)
                attempt += 1
                PROVIDER_RETRIES.labels(self.name.value).inc()
                logger.warning(
                    "provider retry",
                    extra={"provider": self.name.value, "vertical": vertical.value,
                           "attempt": attempt, "delay_s": delay, "error": str(exc)},
                )
                await self._sleep(delay)
                continue
            self._breaker.record_success()
            return blocks
