"""Outbound pacing (improvement plan 1.3).

A single shared egress can't afford bursts: consumer spikes must queue and
smooth into steady, jittered outbound traffic instead of translating 1:1
into an outbound spike. This pacer is GCRA-style: requests reserve evenly
spaced slots (1/qps apart), a small burst allowance absorbs short spikes,
and jitter avoids metronome-regular timing. Waiting callers queue; a caller
whose wait would exceed the cap fails fast instead of hanging.

Set OUTBOUND_QPS from the measured ceiling (scripts/ceiling_probe.py) with
headroom — e.g. 25% of the last safe rate.
"""
import asyncio
import random
import time
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.metrics import OUTBOUND_WAIT


class OutboundSaturatedError(Exception):
    """The outbound queue is deeper than the configured max wait."""


class OutboundPacer:
    def __init__(
        self,
        qps: float,
        burst: int = 5,
        jitter_seconds: float = 0.3,
        max_wait_seconds: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._enabled = qps > 0
        self._interval = 1.0 / qps if qps > 0 else 0.0
        self._burst = max(0, burst)
        self._jitter = max(0.0, jitter_seconds)
        self._max_wait = max_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._lock = asyncio.Lock()
        self._next_slot: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "OutboundPacer":
        return cls(
            qps=settings.outbound_qps,
            burst=settings.outbound_burst,
            jitter_seconds=settings.outbound_jitter_seconds,
            max_wait_seconds=settings.outbound_max_wait_seconds,
        )

    async def acquire(self) -> float:
        """Reserve the next outbound slot; returns the seconds actually waited.

        Raises OutboundSaturatedError (without consuming a slot) when the
        queue is already max_wait deep.
        """
        if not self._enabled:
            return 0.0
        async with self._lock:
            now = self._clock()
            floor = now - self._burst * self._interval
            if self._next_slot is None or self._next_slot < floor:
                self._next_slot = floor
            wait = max(0.0, self._next_slot - now)
            if wait > self._max_wait:
                raise OutboundSaturatedError(
                    f"outbound queue is {wait:.1f}s deep (max {self._max_wait}s)"
                )
            self._next_slot += self._interval
        wait += self._rng() * self._jitter
        if wait > 0:
            await self._sleep(wait)
        OUTBOUND_WAIT.observe(wait)
        return wait
