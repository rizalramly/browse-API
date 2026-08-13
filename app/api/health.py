"""Liveness and dependency health checks."""
import asyncio
from typing import Literal
from urllib.parse import urlparse

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])

DepStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DepsResponse(BaseModel):
    status: Literal["ok", "degraded"]
    redis: DepStatus
    postgres: DepStatus
    genxng: DepStatus


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness probe: the process is up and serving."""
    return HealthResponse(status="ok")


async def _check_redis(url: str) -> DepStatus:
    client: aioredis.Redis = aioredis.from_url(url, socket_connect_timeout=3)
    try:
        await client.ping()
        return "ok"
    except Exception:
        return "error"
    finally:
        await client.aclose()


async def _check_tcp(host: str, port: int) -> DepStatus:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
        writer.close()
        await writer.wait_closed()
        return "ok"
    except Exception:
        return "error"


async def _check_searxng(base_url: str) -> DepStatus:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{base_url.rstrip('/')}/healthz")
        return "ok" if response.status_code == 200 else "error"
    except Exception:
        return "error"


@router.get("/health/deps", response_model=DepsResponse)
async def health_deps() -> DepsResponse:
    """Readiness probe: checks redis, postgres and genxng reachability."""
    settings = get_settings()
    pg = urlparse(settings.database_url)
    redis_status, postgres_status, genxng_status = await asyncio.gather(
        _check_redis(settings.redis_url),
        _check_tcp(pg.hostname or "postgres", pg.port or 5432),
        _check_searxng(settings.searxng_url),
    )
    statuses = (redis_status, postgres_status, genxng_status)
    return DepsResponse(
        status="ok" if all(s == "ok" for s in statuses) else "degraded",
        redis=redis_status,
        postgres=postgres_status,
        genxng=genxng_status,
    )
