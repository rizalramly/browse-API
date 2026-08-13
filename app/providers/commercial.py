"""Commercial provider: adapter for an external Gen-compatible search API.

The upstream speaks the same wire format as our canonical schema, so
normalization is block extraction: keep only the blocks each vertical owns,
drop upstream bookkeeping (searchParameters, credits), and never invent data.
"""
import logging
from typing import Any

import httpx

from app.config import ProviderName, Settings, Vertical
from app.providers.base import ProviderAuthError, ProviderError, SearchProvider
from app.schemas import SearchRequest

logger = logging.getLogger(__name__)

ALLOWED_BLOCKS: dict[Vertical, tuple[str, ...]] = {
    Vertical.SEARCH: ("organic", "knowledgeGraph", "peopleAlsoAsk", "relatedSearches"),
    Vertical.IMAGES: ("images",),
    Vertical.NEWS: ("news",),
    Vertical.PLACES: ("places",),
    Vertical.VIDEOS: ("videos",),
    Vertical.SHOPPING: ("shopping",),
    Vertical.SCHOLAR: ("organic",),
    Vertical.PATENTS: ("organic",),
    Vertical.AUTOCOMPLETE: ("suggestions",),
}


class CommercialProvider(SearchProvider):
    name = ProviderName.COMMERCIAL

    def __init__(
        self,
        settings: Settings,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.commercial_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            transport=transport,
        )

    @staticmethod
    def build_payload(request: SearchRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "q": request.q,
            "gl": request.gl,
            "hl": request.hl,
            "num": request.num,
            "page": request.page,
        }
        if request.location:
            payload["location"] = request.location
        if request.tbs:
            payload["tbs"] = request.tbs
        return payload

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}/{vertical.value}", json=self.build_payload(request)
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"commercial provider request failed: {exc}") from exc
        if response.status_code in (401, 403):
            raise ProviderAuthError("commercial provider rejected the API key")
        if response.status_code != 200:
            raise ProviderError(f"commercial provider returned HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise ProviderError("commercial provider returned non-JSON payload") from exc

        return {
            block: raw[block]
            for block in ALLOWED_BLOCKS[vertical]
            if block in raw and raw[block]
        }

    async def aclose(self) -> None:
        await self._client.aclose()
