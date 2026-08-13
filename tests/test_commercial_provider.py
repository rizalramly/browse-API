"""CommercialProvider against a mocked transport — no live network, no real key.

The fixture is synthetic but Gen-wire-shaped; a recorded response replaces it
once a real commercial key exists.
"""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import ProviderName, Settings, Vertical
from app.providers import ProviderNotConfiguredError, get_provider
from app.providers.base import ProviderError
from app.providers.commercial import CommercialProvider
from app.schemas import PlacesResponse, ScholarResponse, SearchRequest, SearchResponse

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "commercial_search.json").read_text(encoding="utf-8")
)

SETTINGS = Settings(_env_file=None, commercial_base_url="https://commercial.test")


def make_provider(
    handler: Any, api_key: str = "unit-test-key"
) -> tuple[CommercialProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record_and_handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response: httpx.Response = handler(request)
        return response

    provider = CommercialProvider(
        SETTINGS, api_key, transport=httpx.MockTransport(record_and_handle)
    )
    return provider, seen


async def test_search_extracts_allowed_blocks_only() -> None:
    provider, seen = make_provider(lambda request: httpx.Response(200, json=FIXTURE))
    blocks = await provider.search(SearchRequest(q="attention is all you need"), Vertical.SEARCH)

    assert set(blocks) == {"organic", "knowledgeGraph", "peopleAlsoAsk", "relatedSearches"}
    # upstream bookkeeping must not leak through
    assert "searchParameters" not in blocks
    assert "credits" not in blocks

    response = SearchResponse.model_validate(
        {"searchParameters": {"q": "x", "type": "search"}, "credits": 1, **blocks}
    )
    assert response.knowledgeGraph is not None
    assert response.knowledgeGraph.attributes == {"Published": "2017", "Authors": "Vaswani et al."}
    assert response.organic[0].sitelinks is not None

    request = seen[0]
    assert request.url == "https://commercial.test/search"
    assert request.headers["X-API-KEY"] == "unit-test-key"


async def test_payload_includes_optional_fields() -> None:
    provider, seen = make_provider(lambda request: httpx.Response(200, json={"organic": []}))
    await provider.search(
        SearchRequest(q="nasi lemak", gl="my", hl="ms", location="Kuala Lumpur, Malaysia",
                      num=20, page=2, tbs="qdr:w"),
        Vertical.SEARCH,
    )
    payload = json.loads(seen[0].content)
    assert payload == {
        "q": "nasi lemak",
        "gl": "my",
        "hl": "ms",
        "num": 20,
        "page": 2,
        "location": "Kuala Lumpur, Malaysia",
        "tbs": "qdr:w",
    }


async def test_places_and_scholar_block_extraction() -> None:
    places_raw = {
        "places": [
            {"title": "Restoran ABC", "address": "KL", "latitude": 3.1, "longitude": 101.7,
             "rating": 4.5, "ratingCount": 10, "placeId": "ChIJx", "position": 1}
        ],
        "credits": 2,
    }
    provider, _ = make_provider(lambda request: httpx.Response(200, json=places_raw))
    blocks = await provider.search(SearchRequest(q="restoran"), Vertical.PLACES)
    assert set(blocks) == {"places"}
    PlacesResponse.model_validate(
        {"searchParameters": {"q": "x", "type": "places"}, "credits": 2, **blocks}
    )

    scholar_raw = {
        "organic": [
            {"title": "Attention Is All You Need", "link": "https://arxiv.org/abs/1706.03762",
             "publicationInfo": "A Vaswani - NeurIPS 2017", "year": 2017, "citedBy": 100000}
        ]
    }
    provider, seen = make_provider(lambda request: httpx.Response(200, json=scholar_raw))
    blocks = await provider.search(SearchRequest(q="attention"), Vertical.SCHOLAR)
    assert seen[0].url.path == "/scholar"
    ScholarResponse.model_validate(
        {"searchParameters": {"q": "x", "type": "scholar"}, "credits": 2, **blocks}
    )


async def test_empty_blocks_are_omitted() -> None:
    provider, _ = make_provider(
        lambda request: httpx.Response(200, json={"organic": [], "peopleAlsoAsk": []})
    )
    blocks = await provider.search(SearchRequest(q="x"), Vertical.SEARCH)
    assert blocks == {}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors_raise_provider_error(status: int) -> None:
    provider, _ = make_provider(lambda request: httpx.Response(status, json={}))
    with pytest.raises(ProviderError):
        await provider.search(SearchRequest(q="x"), Vertical.SEARCH)


def test_registry_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMMERCIAL_API_KEY", raising=False)
    get_provider.cache_clear()
    with pytest.raises(ProviderNotConfiguredError):
        get_provider(ProviderName.COMMERCIAL)
    get_provider.cache_clear()
