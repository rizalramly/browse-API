"""SearXNG normalization against a recorded fixture — no live network."""
import json
from pathlib import Path
from typing import Any

import pytest

from app.config import Vertical
from app.providers.searxng import normalize_search
from app.schemas import SearchResponse

FIXTURE = Path(__file__).parent / "fixtures" / "searxng_search.json"
PARAMS = {"q": "attention is all you need", "gl": "us", "hl": "en", "type": "search"}


def load_fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


def test_normalize_recorded_fixture() -> None:
    raw = load_fixture()
    blocks = normalize_search(raw, num=10)

    organic = blocks["organic"]
    assert len(organic) == 10
    assert [entry["position"] for entry in organic] == list(range(1, 11))
    for entry in organic:
        assert entry["title"]
        assert entry["link"].startswith("http")

    # empty optional blocks must be omitted, not present as empty lists
    assert "relatedSearches" not in blocks
    assert "knowledgeGraph" not in blocks


def test_normalized_blocks_validate_into_response_schema() -> None:
    blocks = normalize_search(load_fixture(), num=10)
    response = SearchResponse.model_validate(
        {"searchParameters": PARAMS, "credits": 1, **blocks}
    )
    assert response.organic[0].link.startswith("http")


def test_normalize_num_slices_results() -> None:
    blocks = normalize_search(load_fixture(), num=3)
    assert len(blocks["organic"]) == 3


def test_normalize_suggestions_and_infobox() -> None:
    raw = {
        "results": [{"title": "t", "url": "https://x", "content": "c"}],
        "suggestions": ["transformer architecture", "self attention"],
        "infoboxes": [
            {
                "infobox": "Transformer",
                "content": "A deep learning architecture.",
                "img_src": "https://img/x.png",
                "urls": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/T"}],
                "attributes": [{"label": "Field", "value": "Machine learning"}],
            }
        ],
    }
    blocks = normalize_search(raw, num=10)
    assert blocks["relatedSearches"] == [
        {"query": "transformer architecture"},
        {"query": "self attention"},
    ]
    kg = blocks["knowledgeGraph"]
    assert kg["title"] == "Transformer"
    assert kg["website"] == "https://en.wikipedia.org/wiki/T"
    assert kg["attributes"] == {"Field": "Machine learning"}
    assert blocks["organic"][0]["snippet"] == "c"


@pytest.mark.parametrize("vertical", [Vertical.PLACES, Vertical.SHOPPING, Vertical.SCHOLAR])
async def test_unsupported_vertical_raises(vertical: Vertical) -> None:
    from app.config import Settings
    from app.providers.base import UnsupportedVerticalError
    from app.providers.searxng import SearXNGProvider
    from app.schemas import SearchRequest

    provider = SearXNGProvider(Settings(_env_file=None))
    try:
        with pytest.raises(UnsupportedVerticalError):
            await provider.search(SearchRequest(q="x"), vertical)
    finally:
        await provider.aclose()
