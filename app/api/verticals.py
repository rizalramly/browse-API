"""All search verticals: one POST endpoint per vertical, one shared pipeline.

Pipeline: auth -> rate limit -> quota check -> cache -> provider -> deduct
credits (success only) -> usage log. Verticals whose configured provider isn't
implemented return 501 with a clear message instead of failing opaquely.
"""
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import ProviderFactory, get_db, get_provider_factory, get_redis
from app.auth import require_api_key
from app.cache import ResponseCache, build_cache_key
from app.config import ProviderName, Vertical, get_settings
from app.db import ApiKey, Database
from app.metrics import (
    CACHE_REQUESTS,
    PROVIDER_LATENCY,
    PROVIDER_REQUESTS,
    REQUEST_LATENCY,
    REQUESTS,
)
from app.providers.base import (
    ProviderError,
    ProviderNotConfiguredError,
    SearchProvider,
    UnsupportedVerticalError,
)
from app.ratelimit import RateLimiter
from app.schemas import (
    AutocompleteResponse,
    BaseSearchResponse,
    ImagesResponse,
    NewsResponse,
    PatentsResponse,
    PlacesResponse,
    ScholarResponse,
    SearchParameters,
    SearchRequest,
    SearchResponse,
    ShoppingResponse,
    VideosResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

RESPONSE_MODELS: dict[Vertical, type[BaseSearchResponse]] = {
    Vertical.SEARCH: SearchResponse,
    Vertical.IMAGES: ImagesResponse,
    Vertical.NEWS: NewsResponse,
    Vertical.PLACES: PlacesResponse,
    Vertical.VIDEOS: VideosResponse,
    Vertical.SHOPPING: ShoppingResponse,
    Vertical.SCHOLAR: ScholarResponse,
    Vertical.PATENTS: PatentsResponse,
    Vertical.AUTOCOMPLETE: AutocompleteResponse,
}

# Blocks grafted onto /search from the commercial provider when enrichment is on.
ENRICHMENT_BLOCKS = ("knowledgeGraph", "peopleAlsoAsk")


async def _timed_provider_search(
    provider: SearchProvider, body: SearchRequest, vertical: Vertical
) -> dict[str, Any]:
    labels = (provider.name.value, vertical.value)
    start = time.perf_counter()
    try:
        blocks = await provider.search(body, vertical)
    except UnsupportedVerticalError:
        PROVIDER_REQUESTS.labels(*labels, "unsupported").inc()
        raise
    except ProviderError:
        PROVIDER_REQUESTS.labels(*labels, "error").inc()
        raise
    finally:
        PROVIDER_LATENCY.labels(*labels).observe(time.perf_counter() - start)
    PROVIDER_REQUESTS.labels(*labels, "success").inc()
    return blocks


async def _enrich_search(
    blocks: dict[str, Any],
    provenance: dict[str, str],
    body: SearchRequest,
    provider_factory: ProviderFactory,
) -> None:
    """Fill missing high-fidelity blocks from the commercial provider.

    Enrichment is best-effort: any failure is logged and the primary
    provider's response is returned untouched.
    """
    try:
        commercial = provider_factory(ProviderName.COMMERCIAL)
        extra = await _timed_provider_search(commercial, body, Vertical.SEARCH)
    except ProviderError as exc:
        logger.warning("search enrichment skipped: %s", exc)
        return
    for block in ENRICHMENT_BLOCKS:
        if block in extra and block not in blocks:
            blocks[block] = extra[block]
            provenance[block] = ProviderName.COMMERCIAL.value


async def handle_vertical(
    vertical: Vertical,
    body: SearchRequest,
    api_key: ApiKey,
    db: Database,
    redis_client: aioredis.Redis,
    provider_factory: ProviderFactory,
) -> BaseSearchResponse:
    settings = get_settings()
    start = time.perf_counter()
    status = "error"
    try:
        limiter = RateLimiter(redis_client, settings.rate_limit_qps, settings.rate_limit_burst)
        allowed, retry_after = await limiter.check(api_key.id)
        if not allowed:
            status = "rate_limited"
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        cost = settings.credits_for(vertical)
        if api_key.credits < cost:
            status = "quota_exceeded"
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credits: balance {api_key.credits}, cost {cost}",
            )

        cache = ResponseCache(redis_client)
        cache_key = build_cache_key(vertical, body)
        cached = await cache.get(cache_key)
        served_from_cache = cached is not None
        CACHE_REQUESTS.labels(vertical.value, "hit" if served_from_cache else "miss").inc()

        if cached is not None:
            blocks: dict[str, Any] = cached["blocks"]
            source_provider: str = cached.get("provider", "unknown")
            provenance: dict[str, str] = dict.fromkeys(blocks, "cache")
        else:
            provider_name = settings.provider_for(vertical)
            try:
                provider = provider_factory(provider_name)
            except ProviderNotConfiguredError as exc:
                status = "not_configured"
                raise HTTPException(
                    status_code=501,
                    detail=(
                        f"'{vertical.value}' is served by provider '{provider_name.value}', "
                        "which is not configured yet"
                    ),
                ) from exc
            try:
                blocks = await _timed_provider_search(provider, body, vertical)
            except UnsupportedVerticalError as exc:
                status = "unsupported"
                raise HTTPException(status_code=501, detail=str(exc)) from exc
            except ProviderError as exc:
                status = "provider_error"
                logger.error(
                    "provider failed",
                    extra={"provider": provider.name.value, "vertical": vertical.value,
                           "error": str(exc)},
                )
                raise HTTPException(
                    status_code=502, detail="Upstream search provider failed"
                ) from exc
            source_provider = provider.name.value
            provenance = dict.fromkeys(blocks, source_provider)
            if (
                vertical is Vertical.SEARCH
                and settings.search_enrichment
                and provider.name is not ProviderName.COMMERCIAL
            ):
                await _enrich_search(blocks, provenance, body, provider_factory)
            await cache.set(
                cache_key,
                {"blocks": blocks, "provider": source_provider},
                ttl=settings.ttl_for(vertical),
            )

        # Success is certain from here: charge, then account.
        latency_ms = int((time.perf_counter() - start) * 1000)
        if not await db.deduct_credits(api_key.id, cost):
            logger.warning(
                "credit deduction failed",
                extra={"api_key": api_key.name, "vertical": vertical.value, "cost": cost},
            )
        try:
            await db.log_usage(
                api_key.id, vertical.value, cost, source_provider, served_from_cache, latency_ms
            )
        except Exception:
            logger.exception("usage log insert failed")

        response = RESPONSE_MODELS[vertical].model_validate(
            {
                "searchParameters": SearchParameters(
                    q=body.q,
                    gl=body.gl,
                    hl=body.hl,
                    location=body.location,
                    num=body.num,
                    page=body.page,
                    tbs=body.tbs,
                    type=vertical.value,
                ),
                "credits": cost,
                **blocks,
            }
        )
        if body.debug:
            response.providersUsed = provenance
        status = "success"
        logger.info(
            "request served",
            extra={
                "api_key": api_key.name,
                "vertical": vertical.value,
                "provider": source_provider,
                "cached": served_from_cache,
                "latency_ms": latency_ms,
                "credits": cost,
            },
        )
        return response
    finally:
        REQUESTS.labels(vertical.value, status).inc()
        REQUEST_LATENCY.labels(vertical.value).observe(time.perf_counter() - start)


Endpoint = Callable[..., Coroutine[Any, Any, BaseSearchResponse]]


def _make_endpoint(vertical: Vertical) -> Endpoint:
    async def endpoint(
        body: SearchRequest,
        api_key: Annotated[ApiKey, Depends(require_api_key)],
        db: Annotated[Database, Depends(get_db)],
        redis_client: Annotated[aioredis.Redis, Depends(get_redis)],
        provider_factory: Annotated[ProviderFactory, Depends(get_provider_factory)],
    ) -> BaseSearchResponse:
        return await handle_vertical(vertical, body, api_key, db, redis_client, provider_factory)

    endpoint.__name__ = vertical.value
    return endpoint


for _vertical, _model in RESPONSE_MODELS.items():
    router.add_api_route(
        f"/{_vertical.value}",
        _make_endpoint(_vertical),
        methods=["POST"],
        response_model=_model,
        response_model_exclude_none=True,
        summary=f"{_vertical.value} search",
    )
