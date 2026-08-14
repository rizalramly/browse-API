"""Vertical endpoints with faked infrastructure: auth, cache, quota, debug, 501s."""
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_provider_factory, get_redis
from app.config import ProviderName, Vertical
from app.db import ApiKey
from app.main import app
from app.providers.base import ProviderError, ProviderNotConfiguredError, SearchProvider
from app.schemas import SearchRequest

VALID_KEY = "test-key"

FAKE_BLOCKS: dict[Vertical, dict[str, Any]] = {
    Vertical.SEARCH: {
        "organic": [
            {"title": "Attention Is All You Need", "link": "https://arxiv.org/abs/1706.03762",
             "snippet": "s", "position": 1}
        ],
        "relatedSearches": [{"query": "transformer"}],
    },
    Vertical.IMAGES: {
        "images": [
            {"title": "diagram", "imageUrl": "https://x/i.png", "link": "https://x", "position": 1}
        ],
    },
    Vertical.NEWS: {
        "news": [{"title": "headline", "link": "https://n/1", "position": 1}],
    },
    Vertical.VIDEOS: {
        "videos": [{"title": "v", "link": "https://y/watch?v=1", "position": 1}],
    },
    Vertical.AUTOCOMPLETE: {
        "suggestions": [{"value": "attention is all you need"}],
    },
}


class FakeDB:
    def __init__(self, credits: int = 10000) -> None:
        self.credits = credits
        self.deductions: list[int] = []
        self.usage: list[dict[str, Any]] = []

    async def fetch_api_key(self, key: str) -> ApiKey | None:
        if key == VALID_KEY:
            return ApiKey(id=1, name="test", credits=self.credits)
        return None

    async def deduct_credits(self, key_id: int, cost: int) -> bool:
        self.deductions.append(cost)
        self.credits -= cost
        return True

    async def log_usage(self, key_id: int, vertical: str, credits: int, provider: str,
                        cached: bool, latency_ms: int) -> None:
        self.usage.append({"vertical": vertical, "provider": provider, "cached": cached,
                           "credits": credits})


class FakeProvider(SearchProvider):
    name = ProviderName.GENXNG

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        self.calls += 1
        return dict(FAKE_BLOCKS[vertical])


@dataclass
class Env:
    provider: FakeProvider = field(default_factory=FakeProvider)
    db: FakeDB = field(default_factory=FakeDB)
    redis: FakeAsyncRedis = field(default_factory=FakeAsyncRedis)

    def install(self) -> None:
        def factory(name: ProviderName) -> SearchProvider:
            if name is ProviderName.GENXNG:
                return self.provider
            raise ProviderNotConfiguredError(f"provider '{name}' is not implemented yet")

        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_redis] = lambda: self.redis
        app.dependency_overrides[get_provider_factory] = lambda: factory


@pytest.fixture
def env() -> Iterator[Env]:
    environment = Env()
    environment.install()
    yield environment
    app.dependency_overrides.clear()


client = TestClient(app)


def test_search_requires_api_key(env: Env) -> None:
    response = client.post("/search", json={"q": "hello"})
    assert response.status_code == 401


def test_search_rejects_invalid_key(env: Env) -> None:
    response = client.post("/search", json={"q": "hello"}, headers={"X-API-KEY": "nope"})
    assert response.status_code == 401


def test_search_success(env: Env) -> None:
    response = client.post("/search", json={"q": "hello"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["searchParameters"]["q"] == "hello"
    assert body["searchParameters"]["type"] == "search"
    assert body["credits"] == 1
    assert body["organic"][0]["position"] == 1
    # debug off: no providersUsed, and omitted optionals are absent, not null
    assert "providersUsed" not in body
    assert "knowledgeGraph" not in body


@pytest.mark.parametrize(
    ("path", "block", "vertical"),
    [
        ("/images", "images", Vertical.IMAGES),
        ("/news", "news", Vertical.NEWS),
        ("/videos", "videos", Vertical.VIDEOS),
        ("/autocomplete", "suggestions", Vertical.AUTOCOMPLETE),
    ],
)
def test_searxng_verticals_success(env: Env, path: str, block: str, vertical: Vertical) -> None:
    response = client.post(path, json={"q": "hello"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["searchParameters"]["type"] == vertical.value
    assert body[block] == FAKE_BLOCKS[vertical][block]


@pytest.mark.parametrize("path", ["/places", "/shopping", "/scholar", "/patents"])
def test_unconfigured_provider_returns_501(env: Env, path: str) -> None:
    response = client.post(path, json={"q": "hello"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 501
    assert "commercial" in response.json()["detail"]
    # a 501 is not a success: nothing may be charged or logged
    assert env.db.deductions == []
    assert env.db.usage == []


def test_search_serves_second_call_from_cache(env: Env) -> None:
    headers = {"X-API-KEY": VALID_KEY}
    first = client.post("/search", json={"q": "cached", "debug": True}, headers=headers)
    second = client.post("/search", json={"q": "cached", "debug": True}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert env.provider.calls == 1
    assert first.json()["providersUsed"]["organic"] == "genxng"
    assert second.json()["providersUsed"]["organic"] == "cache"
    # payload identical apart from provenance
    assert first.json()["organic"] == second.json()["organic"]


def test_verticals_cache_independently(env: Env) -> None:
    headers = {"X-API-KEY": VALID_KEY}
    assert client.post("/search", json={"q": "same"}, headers=headers).status_code == 200
    assert client.post("/images", json={"q": "same"}, headers=headers).status_code == 200
    assert env.provider.calls == 2


def test_search_validates_body(env: Env) -> None:
    response = client.post(
        "/search", json={"q": "x", "bogus": 1}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 422


# --- Phase 4: quota / credit accounting ---


def test_search_deducts_credits_on_success(env: Env) -> None:
    headers = {"X-API-KEY": VALID_KEY}
    client.post("/search", json={"q": "a"}, headers=headers)
    client.post("/search", json={"q": "a"}, headers=headers)  # cache hit still charges
    assert env.db.deductions == [1, 1]
    assert env.db.usage[0]["cached"] is False
    assert env.db.usage[1]["cached"] is True
    assert env.db.usage[1]["provider"] == "genxng"


def test_zero_balance_returns_402(env: Env) -> None:
    env.db.credits = 0
    response = client.post("/search", json={"q": "x"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 402
    assert "Insufficient credits" in response.json()["detail"]
    assert env.db.deductions == []


def test_no_charge_on_provider_error(env: Env) -> None:
    class BrokenProvider(SearchProvider):
        name = ProviderName.GENXNG

        async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
            raise ProviderError("boom")

    broken = BrokenProvider()
    app.dependency_overrides[get_provider_factory] = lambda: (lambda name: broken)
    response = client.post("/search", json={"q": "x"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 502
    assert env.db.deductions == []
    assert env.db.usage == []


# --- Phase 4: rate limiting ---


def limited_settings(monkeypatch: pytest.MonkeyPatch, qps: float, burst: int) -> None:
    from app import api
    from app.config import Settings

    settings = Settings(_env_file=None, rate_limit_qps=qps, rate_limit_burst=burst)
    monkeypatch.setattr(api.verticals, "get_settings", lambda: settings)


def test_rate_limit_returns_429_with_retry_after(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    limited_settings(monkeypatch, qps=0.5, burst=2)
    headers = {"X-API-KEY": VALID_KEY}
    assert client.post("/search", json={"q": "1"}, headers=headers).status_code == 200
    assert client.post("/search", json={"q": "2"}, headers=headers).status_code == 200
    third = client.post("/search", json={"q": "3"}, headers=headers)
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) >= 1
    # rate-limited requests are never charged
    assert env.db.deductions == [1, 1]


# --- Phase 3: enrichment (settings-driven) ---


COMMERCIAL_BLOCKS: dict[str, Any] = {
    "organic": [{"title": "commercial", "link": "https://c/1", "position": 1}],
    "knowledgeGraph": {"title": "Transformer", "type": "Architecture"},
    "peopleAlsoAsk": [{"question": "What is attention?"}],
}


class FakeCommercialProvider(SearchProvider):
    name = ProviderName.COMMERCIAL

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        return dict(COMMERCIAL_BLOCKS)


def enable_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import api
    from app.config import Settings

    settings = Settings(_env_file=None, search_enrichment=True)
    monkeypatch.setattr(api.verticals, "get_settings", lambda: settings)


def test_search_enrichment_grafts_commercial_blocks(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_enrichment(monkeypatch)
    commercial = FakeCommercialProvider()

    def factory(name: ProviderName) -> SearchProvider:
        return env.provider if name is ProviderName.GENXNG else commercial

    app.dependency_overrides[get_provider_factory] = lambda: factory
    response = client.post(
        "/search", json={"q": "enriched", "debug": True}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    body = response.json()
    # organic stays with the primary provider; only missing blocks are grafted
    assert body["organic"] == FAKE_BLOCKS[Vertical.SEARCH]["organic"]
    assert body["knowledgeGraph"]["title"] == "Transformer"
    assert body["peopleAlsoAsk"][0]["question"] == "What is attention?"
    assert body["providersUsed"]["organic"] == "genxng"
    assert body["providersUsed"]["knowledgeGraph"] == "commercial"
    assert body["providersUsed"]["peopleAlsoAsk"] == "commercial"


def test_search_enrichment_fails_soft(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    enable_enrichment(monkeypatch)
    response = client.post(
        "/search", json={"q": "no commercial", "debug": True}, headers={"X-API-KEY": VALID_KEY}
    )
    # default fake factory raises ProviderNotConfiguredError for commercial:
    # the searxng response must come back untouched
    assert response.status_code == 200
    body = response.json()
    assert "knowledgeGraph" not in body
    assert body["providersUsed"]["organic"] == "genxng"


# --- improvement plan 2.1: searchMeta quality signal ---


DEGRADED_META: dict[str, Any] = {
    "enginesQueried": 8,
    "enginesResponded": 2,
    "engineCoverage": 0.25,
    "resultCount": 2,
    "duplicateRate": 0.0,
    "qualityScore": 0.225,
    "cached": False,
    "degraded": True,
}


class DegradedProvider(SearchProvider):
    name = ProviderName.GENXNG

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        return {**FAKE_BLOCKS[Vertical.SEARCH], "searchMeta": dict(DEGRADED_META)}


def test_degraded_200_carries_search_meta(env: Env) -> None:
    """Plan 2.1 acceptance: a degraded-but-200 response says so, machine-readably."""
    provider = DegradedProvider()
    app.dependency_overrides[get_provider_factory] = lambda: (lambda name: provider)
    response = client.post(
        "/search", json={"q": "thin", "debug": True}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    meta = response.json()["searchMeta"]
    assert meta["degraded"] is True
    assert meta["qualityScore"] == 0.225
    assert meta["cached"] is False
    # searchMeta is metadata, not a content block: no provenance entry
    assert "searchMeta" not in response.json()["providersUsed"]


def test_cache_hit_sets_search_meta_cached_flag(env: Env) -> None:
    provider = DegradedProvider()
    app.dependency_overrides[get_provider_factory] = lambda: (lambda name: provider)
    headers = {"X-API-KEY": VALID_KEY}
    first = client.post("/search", json={"q": "meta-cache"}, headers=headers)
    second = client.post("/search", json={"q": "meta-cache"}, headers=headers)
    assert first.json()["searchMeta"]["cached"] is False
    assert second.json()["searchMeta"]["cached"] is True
    # quality data survives the cache round-trip
    assert second.json()["searchMeta"]["qualityScore"] == 0.225


def test_response_without_search_meta_omits_it(env: Env) -> None:
    response = client.post("/search", json={"q": "plain"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 200
    assert "searchMeta" not in response.json()


# --- improvement plan 3.3: log hygiene ---


def test_request_log_hashes_query_by_default(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="app.api.verticals"):
        client.post("/search", json={"q": "secret plant name"}, headers={"X-API-KEY": VALID_KEY})
    served = [r for r in caplog.records if r.getMessage() == "request served"]
    assert served, "request served log line missing"
    record = served[-1]
    assert len(record.query_hash) == 16  # type: ignore[attr-defined]
    assert not hasattr(record, "query")  # raw text absent unless LOG_QUERIES=true
    assert "secret plant name" not in record.query_hash  # type: ignore[attr-defined]


def test_http_client_loggers_are_quieted() -> None:
    import logging

    from app.logging_config import setup_logging

    setup_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


# --- improvement plan 2.3: in-API quality fall-through ---


COMMERCIAL_ORGANIC: dict[str, Any] = {
    "organic": [{"title": "commercial result", "link": "https://c/1", "position": 1}],
}


class CountingCommercial(SearchProvider):
    name = ProviderName.COMMERCIAL

    def __init__(self, blocks: dict[str, Any] | None = None,
                 error: Exception | None = None) -> None:
        self.calls = 0
        self.blocks = COMMERCIAL_ORGANIC if blocks is None else blocks
        self.error = error

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.blocks)


def install_fallthrough(env: Env, commercial: CountingCommercial) -> None:
    def factory(name: ProviderName) -> SearchProvider:
        if name is ProviderName.COMMERCIAL:
            return commercial
        return DegradedProvider()

    app.dependency_overrides[get_provider_factory] = lambda: factory


def test_degraded_response_falls_through_to_commercial(env: Env) -> None:
    commercial = CountingCommercial()
    install_fallthrough(env, commercial)
    response = client.post(
        "/search", json={"q": "thin results", "debug": True}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    body = response.json()
    assert commercial.calls == 1
    # the commercial result replaced the degraded genxng one
    assert body["organic"][0]["title"] == "commercial result"
    assert body["providersUsed"]["organic"] == "commercial"
    # commercial responses carry no engine meta
    assert "searchMeta" not in body
    # usage log attributes the serve to commercial
    assert env.db.usage[0]["provider"] == "commercial"


def test_fallthrough_failure_keeps_degraded_primary(env: Env) -> None:
    commercial = CountingCommercial(error=ProviderError("commercial down"))
    install_fallthrough(env, commercial)
    response = client.post(
        "/search", json={"q": "thin results", "debug": True}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    body = response.json()
    assert commercial.calls == 1
    assert body["searchMeta"]["degraded"] is True  # original degraded result served
    assert body["providersUsed"]["organic"] == "genxng"


def test_fallthrough_with_empty_commercial_keeps_primary(env: Env) -> None:
    commercial = CountingCommercial(blocks={})
    install_fallthrough(env, commercial)
    response = client.post(
        "/search", json={"q": "thin results"}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    assert response.json()["searchMeta"]["degraded"] is True


def test_fallthrough_disabled_by_flag(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import api
    from app.config import Settings

    settings = Settings(_env_file=None, quality_fallthrough=False)
    monkeypatch.setattr(api.verticals, "get_settings", lambda: settings)
    commercial = CountingCommercial()
    install_fallthrough(env, commercial)
    response = client.post(
        "/search", json={"q": "thin results"}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    assert commercial.calls == 0
    assert response.json()["searchMeta"]["degraded"] is True


def test_healthy_response_does_not_fall_through(env: Env) -> None:
    commercial = CountingCommercial()

    def factory(name: ProviderName) -> SearchProvider:
        return commercial if name is ProviderName.COMMERCIAL else env.provider

    app.dependency_overrides[get_provider_factory] = lambda: factory
    response = client.post("/search", json={"q": "fine"}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 200
    assert commercial.calls == 0  # no searchMeta / not degraded -> no fall-through


def test_fallthrough_result_is_cached(env: Env) -> None:
    commercial = CountingCommercial()
    install_fallthrough(env, commercial)
    headers = {"X-API-KEY": VALID_KEY}
    client.post("/search", json={"q": "cache me", "debug": True}, headers=headers)
    second = client.post("/search", json={"q": "cache me", "debug": True}, headers=headers)
    assert commercial.calls == 1  # second serve came from cache
    assert second.json()["providersUsed"]["organic"] == "cache"
    assert second.json()["organic"][0]["title"] == "commercial result"


# --- improvement plan 3.2: classification gate, fail closed ---


BLOCKED_QUERY = "scada network diagram"  # matches grid-operations in policy/sensitive.yml


@pytest.mark.parametrize("path", ["/search", "/news", "/images", "/autocomplete"])
def test_sensitive_query_fails_closed_on_every_vertical(env: Env, path: str) -> None:
    response = client.post(path, json={"q": BLOCKED_QUERY}, headers={"X-API-KEY": VALID_KEY})
    assert response.status_code == 403
    body = response.json()
    assert body["policyBlocked"] is True
    assert body["category"] == "grid-operations"
    assert body["detail"] == "query blocked by policy"
    # fail closed means: no provider call, no charge, no usage row
    assert env.provider.calls == 0
    assert env.db.deductions == []
    assert env.db.usage == []


def test_sensitive_query_never_reaches_fallback_path(env: Env) -> None:
    """Even with every provider available, a blocked query touches none of them."""
    factory_calls: list[ProviderName] = []

    def spying_factory(name: ProviderName) -> SearchProvider:
        factory_calls.append(name)
        return env.provider

    app.dependency_overrides[get_provider_factory] = lambda: spying_factory
    response = client.post(
        "/search", json={"q": BLOCKED_QUERY}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 403
    assert factory_calls == []  # no provider was even constructed


def test_sensitive_query_is_never_cached(env: Env) -> None:
    import asyncio

    async def cache_keys() -> list[bytes | str]:
        result: list[bytes | str] = await env.redis.keys("cache:*")
        return result

    client.post("/search", json={"q": BLOCKED_QUERY}, headers={"X-API-KEY": VALID_KEY})
    assert asyncio.run(cache_keys()) == []


def test_blocked_still_requires_auth(env: Env) -> None:
    """Auth runs before the gate: no unauthenticated policy oracle."""
    response = client.post("/search", json={"q": BLOCKED_QUERY})
    assert response.status_code == 401


def test_benign_query_passes_gate(env: Env) -> None:
    response = client.post(
        "/search", json={"q": "malaysia electricity tariff"}, headers={"X-API-KEY": VALID_KEY}
    )
    assert response.status_code == 200
    assert env.provider.calls == 1


# --- Phase 4: metrics exposition ---


def test_metrics_endpoint_exposes_counters(env: Env) -> None:
    client.post("/search", json={"q": "metrics"}, headers={"X-API-KEY": VALID_KEY})
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "gen_api_requests_total" in text
    assert "gen_api_provider_requests_total" in text
    assert "gen_api_cache_requests_total" in text
    assert "gen_api_request_latency_seconds" in text
