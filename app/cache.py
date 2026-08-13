"""Redis response cache. Key = hash of the canonical request parameters."""
import hashlib
import json
from typing import Any

import redis.asyncio as aioredis

from app.config import Vertical
from app.schemas import SearchRequest


def build_cache_key(vertical: Vertical, request: SearchRequest) -> str:
    canonical = json.dumps(
        {
            "vertical": vertical.value,
            "q": request.q,
            "gl": request.gl,
            "hl": request.hl,
            "location": request.location,
            "num": request.num,
            "page": request.page,
            "tbs": request.tbs,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"cache:{vertical.value}:{digest}"


class ResponseCache:
    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def get(self, key: str) -> dict[str, Any] | None:
        payload = await self._client.get(key)
        if payload is None:
            return None
        loaded: dict[str, Any] = json.loads(payload)
        return loaded

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        await self._client.set(key, json.dumps(value), ex=ttl)
