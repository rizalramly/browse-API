"""Outbound pacer (plan 1.3): smoothing, burst, jitter, saturation."""
import pytest

from app.pacing import OutboundPacer, OutboundSaturatedError


class Harness:
    """Pacer with fake clock/sleep/rng; sleeping advances the clock."""

    def __init__(self, qps: float, burst: int = 0, jitter: float = 0.0,
                 max_wait: float = 20.0, rng: float = 1.0) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            self.sleeps.append(round(seconds, 6))
            self.now += seconds

        self.pacer = OutboundPacer(
            qps=qps, burst=burst, jitter_seconds=jitter, max_wait_seconds=max_wait,
            clock=lambda: self.now, sleep=fake_sleep, rng=lambda: rng,
        )


async def test_requests_are_spaced_at_qps() -> None:
    h = Harness(qps=2.0)  # interval 0.5s, no burst, no jitter
    waits = [await h.pacer.acquire() for _ in range(4)]
    assert waits[0] == 0.0  # first slot is immediate
    assert waits[1:] == [0.5, 0.5, 0.5]  # then evenly spaced


async def test_burst_allows_initial_spike_then_smooths() -> None:
    h = Harness(qps=1.0, burst=3)
    waits = [round(await h.pacer.acquire(), 3) for _ in range(5)]
    # 3 burst tokens + the current slot go through immediately, then pacing
    assert waits[:4] == [0.0, 0.0, 0.0, 0.0]
    assert waits[4] == 1.0


async def test_idle_time_refills_burst() -> None:
    h = Harness(qps=1.0, burst=2)
    for _ in range(3):
        await h.pacer.acquire()
    h.now += 60  # long idle: bucket refills (but never beyond burst)
    assert await h.pacer.acquire() == 0.0
    assert await h.pacer.acquire() == 0.0
    assert await h.pacer.acquire() == 0.0  # burst + current slot
    assert await h.pacer.acquire() == 1.0  # smoothed again


async def test_jitter_is_added_to_waits() -> None:
    h = Harness(qps=2.0, jitter=0.2, rng=0.5)  # adds exactly 0.1s
    first = await h.pacer.acquire()
    second = await h.pacer.acquire()
    assert first == pytest.approx(0.1)
    assert second == pytest.approx(0.5 + 0.1 - 0.1)  # slot lag absorbs prior jitter


async def test_saturation_raises_without_consuming_a_slot() -> None:
    h = Harness(qps=1.0, max_wait=2.0)
    for _ in range(3):
        await h.pacer.acquire()  # queue is now 2s deep...
    h.now -= 2.0  # rewind: pretend the sleeps did not advance time (deep queue)
    with pytest.raises(OutboundSaturatedError):
        await h.pacer.acquire()


async def test_qps_zero_disables_pacing() -> None:
    h = Harness(qps=0)
    for _ in range(10):
        assert await h.pacer.acquire() == 0.0
    assert h.sleeps == []
