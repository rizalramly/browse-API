"""Images/news/videos/autocomplete normalization against recorded fixtures."""
import json
from pathlib import Path
from typing import Any

from app.providers.searxng import (
    normalize_autocomplete,
    normalize_images,
    normalize_news,
    normalize_videos,
)
from app.schemas import AutocompleteResponse, ImagesResponse, NewsResponse, VideosResponse

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def params(vertical: str) -> dict[str, str]:
    return {"q": "test", "gl": "us", "hl": "en", "type": vertical}


def test_normalize_images_fixture() -> None:
    blocks = normalize_images(load("searxng_images.json"), num=10)
    images = blocks["images"]
    assert len(images) == 10
    assert [img["position"] for img in images] == list(range(1, 11))
    for img in images:
        assert img["imageUrl"].startswith("http")
        assert img["link"].startswith("http")
    # recorded fixture has resolutions like "1882×1264" — width/height must parse
    assert any("imageWidth" in img and img["imageWidth"] > 0 for img in images)
    response = ImagesResponse.model_validate(
        {"searchParameters": params("images"), "credits": 1, **blocks}
    )
    assert response.images[0].domain


def test_normalize_news_fixture() -> None:
    blocks = normalize_news(load("searxng_news.json"), num=10)
    news = blocks["news"]
    assert len(news) == 10
    for item in news:
        assert item["title"]
        assert item["link"].startswith("http")
    # metadata "13 hours ago | Barchart on MSN" must split into date + source
    assert any("date" in item for item in news)
    assert any("source" in item for item in news)
    NewsResponse.model_validate({"searchParameters": params("news"), "credits": 1, **blocks})


def test_normalize_videos_fixture() -> None:
    blocks = normalize_videos(load("searxng_videos.json"), num=10)
    videos = blocks["videos"]
    assert len(videos) == 10
    assert any("duration" in v for v in videos)
    assert all(v["link"].startswith("http") for v in videos)
    VideosResponse.model_validate({"searchParameters": params("videos"), "credits": 1, **blocks})


def test_normalize_autocomplete_fixture() -> None:
    blocks = normalize_autocomplete(load("searxng_autocomplete.json"), num=10)
    suggestions = blocks["suggestions"]
    assert suggestions
    assert suggestions[0]["value"] == "attention is all you need"
    AutocompleteResponse.model_validate(
        {"searchParameters": params("autocomplete"), "credits": 1, **blocks}
    )


def test_normalize_autocomplete_handles_garbage() -> None:
    assert normalize_autocomplete({}, num=10) == {"suggestions": []}
    assert normalize_autocomplete(["q"], num=10) == {"suggestions": []}
    assert normalize_autocomplete(None, num=10) == {"suggestions": []}


def test_normalize_images_skips_entries_without_image() -> None:
    raw = {
        "results": [
            {"title": "no img", "url": "https://x"},
            {"title": "ok", "url": "https://y", "img_src": "https://y/i.png"},
        ]
    }
    images = normalize_images(raw, num=10)["images"]
    assert len(images) == 1
    assert images[0]["title"] == "ok"
    assert images[0]["position"] == 1
