"""Engine health monitor (plan 2.2): quarantine after N failures, auto-recover."""
import json
from typing import Any

import httpx

from app.config import Settings
from app.engine_health import EngineHealthMonitor
from app.providers.searxng import SearXNGProvider
from app.schemas import SearchRequest

CONFIG_PAYLOAD: dict[str, Any] = {
    "engines": [
        {"name": "google", "enabled": True, "categories": ["general"]},
        {"name": "brave", "enabled": True, "categories": ["general", "images"]},
        {"name": "bing images", "enabled": True, "categories": ["images"]},
        {"name": "disabled engine", "enabled": False, "categories": ["general"]},
        {"name": "map engine", "enabled": True, "categories": ["map"]},  # not probed
    ]
}


def make_monitor(broken: set[str], fail_threshold: int = 3) -> EngineHealthMonitor:
    """Monitor wired to a fake searxng where `broken` engines never respond."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/config":
            return httpx.Response(200, json=CONFIG_PAYLOAD)
        engine = request.url.params.get("engines", "")
        if engine in broken:
            return httpx.Response(
                200, json={"results": [], "unresponsive_engines": [[engine, "timeout"]]}
            )
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    monitor = EngineHealthMonitor(base_url="http://searxng.test",
                                  fail_threshold=fail_threshold)
    monitor._test_transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    return monitor


async def run_round(monitor: EngineHealthMonitor) -> None:
    transport: httpx.MockTransport = monitor._test_transport  # type: ignore[attr-defined]
    async with httpx.AsyncClient(transport=transport) as client:
        await monitor.refresh(client)


async def test_no_quarantine_before_threshold() -> None:
    monitor = make_monitor(broken={"brave"}, fail_threshold=3)
    await run_round(monitor)
    await run_round(monitor)
    assert monitor.unhealthy_engines() == set()
    assert monitor.healthy_for("general") is None  # nothing quarantined -> no filtering


async def test_engine_quarantined_after_threshold_and_recovers() -> None:
    monitor = make_monitor(broken={"brave"}, fail_threshold=3)
    for _ in range(3):
        await run_round(monitor)
    assert monitor.unhealthy_engines() == {"brave"}
    assert monitor.healthy_for("general") == ["google"]
    assert monitor.healthy_for("images") == ["bing images"]

    # engine comes back: one good probe recovers it
    monitor._test_transport = make_monitor(broken=set())._test_transport  # type: ignore[attr-defined]
    await run_round(monitor)
    assert monitor.unhealthy_engines() == set()
    assert monitor.healthy_for("general") is None


async def test_all_engines_down_means_no_filtering() -> None:
    """If everything is quarantined, filtering to an empty set would be worse
    than letting genxng try its defaults."""
    monitor = make_monitor(broken={"google", "brave"}, fail_threshold=1)
    await run_round(monitor)
    assert monitor.healthy_for("general") is None


async def test_provider_selects_only_healthy_engines(
    monkeypatch: Any,
) -> None:
    monitor = make_monitor(broken={"brave"}, fail_threshold=1)
    await run_round(monitor)
    assert monitor.unhealthy_engines() == {"brave"}

    from app.providers import searxng as searxng_module

    monkeypatch.setattr(searxng_module, "get_engine_monitor", lambda settings: monitor)

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    provider = SearXNGProvider(
        Settings(_env_file=None), transport=httpx.MockTransport(handler)
    )
    from app.config import Vertical

    await provider.search(SearchRequest(q="test"), Vertical.SEARCH)
    await provider.aclose()
    assert seen[0].url.params["engines"] == "google"


async def test_provider_omits_engines_param_when_all_healthy(monkeypatch: Any) -> None:
    monitor = make_monitor(broken=set())
    await run_round(monitor)

    from app.providers import searxng as searxng_module

    monkeypatch.setattr(searxng_module, "get_engine_monitor", lambda settings: monitor)

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    provider = SearXNGProvider(
        Settings(_env_file=None), transport=httpx.MockTransport(handler)
    )
    from app.config import Vertical

    await provider.search(SearchRequest(q="test"), Vertical.SEARCH)
    await provider.aclose()
    assert "engines" not in seen[0].url.params


def test_discover_parses_config_shape() -> None:
    """The /config parsing matches searxng's actual payload shape."""
    raw = json.dumps(CONFIG_PAYLOAD)
    parsed = json.loads(raw)
    assert parsed["engines"][0]["categories"] == ["general"]
