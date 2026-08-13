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
