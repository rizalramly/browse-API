"""Schema contract tests: Gen-shaped payloads must validate unchanged."""
import pytest
from pydantic import ValidationError

from app.schemas import (
    AutocompleteResponse,
    ImagesResponse,
    NewsResponse,
    PatentsResponse,
    PlacesResponse,
    ScholarResponse,
    SearchRequest,
    SearchResponse,
    ShoppingResponse,
    VideosResponse,
)

PARAMS = {"q": "attention is all you need", "gl": "my", "hl": "en", "type": "search"}


def test_request_defaults() -> None:
    req = SearchRequest(q="hello")
    assert req.gl == "us"
    assert req.hl == "en"
    assert req.num == 10
    assert req.page == 1
    assert req.debug is False


def test_request_rejects_missing_q() -> None:
    with pytest.raises(ValidationError):
        SearchRequest()  # type: ignore[call-arg]


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(q="x", engine="google")  # type: ignore[call-arg]


def test_search_response() -> None:
    payload = {
        "searchParameters": PARAMS,
        "credits": 1,
        "organic": [
            {
                "title": "Attention Is All You Need",
                "link": "https://arxiv.org/abs/1706.03762",
                "snippet": "The dominant sequence transduction models...",
                "position": 1,
                "sitelinks": [{"title": "PDF", "link": "https://arxiv.org/pdf/1706.03762"}],
            }
        ],
        "knowledgeGraph": {
            "title": "Transformer",
            "type": "Model architecture",
            "attributes": {"Authors": "Vaswani et al."},
        },
        "peopleAlsoAsk": [
            {
                "question": "What is attention?",
                "snippet": "...",
                "title": "t",
                "link": "https://x",
            }
        ],
        "relatedSearches": [{"query": "transformer architecture"}],
    }
    resp = SearchResponse.model_validate(payload)
    assert resp.organic[0].position == 1
    assert resp.knowledgeGraph is not None
    # Optional blocks omitted must serialize away, not appear as null
    dumped = resp.model_dump(exclude_none=True)
    assert "providersUsed" not in dumped


def test_optional_blocks_can_be_omitted() -> None:
    resp = SearchResponse.model_validate({"searchParameters": PARAMS, "credits": 1})
    assert resp.organic == []
    assert resp.knowledgeGraph is None


def test_images_response() -> None:
    resp = ImagesResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "images"},
            "credits": 1,
            "images": [
                {
                    "title": "diagram",
                    "imageUrl": "https://x/img.png",
                    "thumbnailUrl": "https://x/t.png",
                    "source": "x.com",
                    "domain": "x.com",
                    "link": "https://x/page",
                    "imageWidth": 800,
                    "imageHeight": 600,
                    "position": 1,
                }
            ],
        }
    )
    assert resp.images[0].imageWidth == 800


def test_news_response() -> None:
    resp = NewsResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "news"},
            "credits": 1,
            "news": [
                {
                    "title": "headline",
                    "link": "https://n/1",
                    "snippet": "s",
                    "date": "2 hours ago",
                    "source": "Reuters",
                    "position": 1,
                }
            ],
        }
    )
    assert resp.news[0].source == "Reuters"


def test_places_response() -> None:
    resp = PlacesResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "places"},
            "credits": 2,
            "places": [
                {
                    "title": "Restoran ABC",
                    "address": "Kuala Lumpur",
                    "latitude": 3.139,
                    "longitude": 101.6869,
                    "rating": 4.5,
                    "ratingCount": 120,
                    "types": ["restaurant"],
                    "placeId": "ChIJx",
                    "position": 1,
                }
            ],
        }
    )
    assert resp.places[0].latitude == pytest.approx(3.139)


def test_videos_response() -> None:
    resp = VideosResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "videos"},
            "credits": 1,
            "videos": [
                {
                    "title": "v",
                    "link": "https://youtube.com/watch?v=1",
                    "duration": "10:31",
                    "channel": "c",
                    "position": 1,
                }
            ],
        }
    )
    assert resp.videos[0].duration == "10:31"


def test_shopping_response() -> None:
    resp = ShoppingResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "shopping"},
            "credits": 1,
            "shopping": [
                {
                    "title": "p",
                    "source": "Shopee",
                    "link": "https://s/1",
                    "price": "RM 99.00",
                    "productId": "123",
                    "position": 1,
                }
            ],
        }
    )
    assert resp.shopping[0].price == "RM 99.00"


def test_scholar_response() -> None:
    resp = ScholarResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "scholar"},
            "credits": 2,
            "organic": [
                {
                    "title": "Attention Is All You Need",
                    "link": "https://arxiv.org/abs/1706.03762",
                    "publicationInfo": "A Vaswani... - NeurIPS, 2017",
                    "year": 2017,
                    "citedBy": 100000,
                }
            ],
        }
    )
    assert resp.organic[0].citedBy == 100000


def test_patents_response() -> None:
    resp = PatentsResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "patents"},
            "credits": 2,
            "organic": [
                {
                    "title": "Neural machine translation",
                    "link": "https://patents.google.com/patent/US1",
                    "assignee": "Google LLC",
                    "publicationNumber": "US1",
                    "figures": ["https://p/fig1.png"],
                }
            ],
        }
    )
    assert resp.organic[0].assignee == "Google LLC"


def test_autocomplete_response() -> None:
    resp = AutocompleteResponse.model_validate(
        {
            "searchParameters": {**PARAMS, "type": "autocomplete"},
            "credits": 1,
            "suggestions": [{"value": "attention is all you need paper"}],
        }
    )
    assert resp.suggestions[0].value.startswith("attention")
