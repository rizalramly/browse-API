"""Cache key construction and Redis round-trip (fakeredis, no infrastructure)."""
from fakeredis import FakeAsyncRedis

from app.cache import ResponseCache, build_cache_key
from app.config import Vertical
from app.schemas import SearchRequest


def test_cache_key_is_deterministic() -> None:
    a = build_cache_key(Vertical.SEARCH, SearchRequest(q="hello", gl="my"))
    b = build_cache_key(Vertical.SEARCH, SearchRequest(q="hello", gl="my"))
    assert a == b
    assert a.startswith("cache:search:")


def test_cache_key_varies_by_parameters() -> None:
    base = SearchRequest(q="hello")
    assert build_cache_key(Vertical.SEARCH, base) != build_cache_key(
        Vertical.SEARCH, SearchRequest(q="hello", page=2)
    )
    assert build_cache_key(Vertical.SEARCH, base) != build_cache_key(Vertical.NEWS, base)


def test_debug_flag_does_not_change_cache_key() -> None:
    assert build_cache_key(Vertical.SEARCH, SearchRequest(q="x")) == build_cache_key(
        Vertical.SEARCH, SearchRequest(q="x", debug=True)
    )


async def test_cache_round_trip_and_miss() -> None:
    cache = ResponseCache(FakeAsyncRedis())
    key = build_cache_key(Vertical.SEARCH, SearchRequest(q="x"))
    assert await cache.get(key) is None
    value = {"blocks": {"organic": [{"title": "t", "link": "https://x", "position": 1}]}}
    await cache.set(key, value, ttl=60)
    assert await cache.get(key) == value
