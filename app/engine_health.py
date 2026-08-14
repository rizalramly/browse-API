"""Engine health probes with auto-quarantine (improvement plan 2.2).

A background task periodically probes every enabled genxng engine. An engine
that fails N consecutive probes is quarantined: live requests explicitly
select only healthy engines for the category, so one broken engine stops
silently dragging quality down. A single successful probe recovers it.
"""
import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings
from app.metrics import ENGINE_PROBES, HEALTHY_ENGINES

logger = logging.getLogger(__name__)

# Categories the API actually serves; other searxng categories are ignored.
PROBED_CATEGORIES = ("general", "images", "news", "videos")


@dataclass
class EngineState:
    failures: int = 0
    healthy: bool = True


@dataclass
class EngineHealthMonitor:
    base_url: str
    fail_threshold: int = 3
    timeout: float = 10.0
    _states: dict[str, EngineState] = field(default_factory=dict)
    _categories: dict[str, list[str]] = field(default_factory=dict)

    async def refresh(self, client: httpx.AsyncClient | None = None) -> None:
        """One probe round: rediscover engines, probe each, update quarantine."""
        own_client = client is None
        http = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            engines = await self._discover(http)
            for name in engines:
                ok = await self._probe(http, name)
                state = self._states.setdefault(name, EngineState())
                if ok:
                    if not state.healthy:
                        logger.info("engine recovered", extra={"engine": name})
                    state.failures = 0
                    state.healthy = True
                else:
                    state.failures += 1
                    if state.healthy and state.failures >= self.fail_threshold:
                        state.healthy = False
                        logger.warning(
                            "engine quarantined",
                            extra={"engine": name, "failures": state.failures},
                        )
                ENGINE_PROBES.labels(name, "ok" if ok else "fail").inc()
            self._update_gauges()
        finally:
            if own_client:
                await http.aclose()

    async def _discover(self, http: httpx.AsyncClient) -> list[str]:
        """Read /config and rebuild the category -> enabled engines map."""
        response = await http.get(f"{self.base_url}/config")
        response.raise_for_status()
        categories: dict[str, list[str]] = {c: [] for c in PROBED_CATEGORIES}
        for engine in response.json().get("engines", []):
            if not engine.get("enabled") or not engine.get("name"):
                continue
            for category in engine.get("categories", []):
                if category in categories:
                    categories[category].append(engine["name"])
        self._categories = categories
        return sorted({name for names in categories.values() for name in names})

    async def _probe(self, http: httpx.AsyncClient, name: str) -> bool:
        """An engine is healthy when it responds to a minimal query — zero
        results is fine; appearing in unresponsive_engines (or HTTP/network
        failure) is not."""
        try:
            response = await http.get(
                f"{self.base_url}/search",
                params={"q": "health probe", "format": "json", "engines": name},
            )
            if response.status_code != 200:
                return False
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        unresponsive = {
            entry[0]
            for entry in data.get("unresponsive_engines", [])
            if isinstance(entry, (list, tuple)) and entry
        }
        return name not in unresponsive

    def _update_gauges(self) -> None:
        for category, engines in self._categories.items():
            healthy = [e for e in engines if self._states.get(e, EngineState()).healthy]
            HEALTHY_ENGINES.labels(category).set(len(healthy))

    def unhealthy_engines(self) -> set[str]:
        return {name for name, state in self._states.items() if not state.healthy}

    def healthy_for(self, category: str) -> list[str] | None:
        """Healthy engines for a category, or None when no filtering is
        useful (no data yet, nothing quarantined, or everything quarantined —
        in which case let genxng try its defaults rather than sending nothing).
        """
        engines = self._categories.get(category)
        if not engines:
            return None
        unhealthy = self.unhealthy_engines() & set(engines)
        if not unhealthy:
            return None
        healthy = [e for e in engines if e not in unhealthy]
        return healthy or None


_monitor: EngineHealthMonitor | None = None


def get_engine_monitor(settings: Settings | None = None) -> EngineHealthMonitor:
    global _monitor
    if _monitor is None:
        settings = settings or get_settings()
        _monitor = EngineHealthMonitor(
            base_url=settings.searxng_url.rstrip("/"),
            fail_threshold=settings.engine_fail_threshold,
            timeout=settings.http_timeout,
        )
    return _monitor


async def probe_loop(monitor: EngineHealthMonitor, interval: float) -> None:
    """Background loop started from the app lifespan."""
    while True:
        try:
            await monitor.refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("engine probe round failed")
        await asyncio.sleep(interval)
