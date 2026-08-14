"""gen-api: self-hosted Gen search API.

search/images/news/videos/autocomplete are served by GenXNG (the on-prem
metasearch backend); remaining verticals answer 501 until the commercial
provider is configured.
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.verticals import router as verticals_router
from app.config import get_settings
from app.db import Database
from app.engine_health import get_engine_monitor, probe_loop
from app.logging_config import setup_logging
from app.policy import PolicyBlockedError

setup_logging(get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db = Database(settings.database_url)
    await db.connect()
    app.state.db = db
    app.state.redis = aioredis.from_url(settings.redis_url)
    probe_task: asyncio.Task[None] | None = None
    if settings.engine_probe_interval > 0:
        probe_task = asyncio.create_task(
            probe_loop(get_engine_monitor(settings), settings.engine_probe_interval)
        )
    yield
    if probe_task is not None:
        probe_task.cancel()
        with suppress(asyncio.CancelledError):
            await probe_task
    await app.state.redis.aclose()
    await db.close()


app = FastAPI(
    title="gen-api",
    version="0.1.0",
    description=(
        "Self-hosted Gen web-search API with a pluggable acquisition "
        "layer (GenXNG / commercial search API / direct scrape)."
    ),
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(verticals_router)


@app.exception_handler(PolicyBlockedError)
async def policy_blocked_handler(request: Request, exc: PolicyBlockedError) -> JSONResponse:
    """Sensitive queries fail closed: 403 with a machine-readable reason code."""
    return JSONResponse(
        status_code=403,
        content={
            "detail": "query blocked by policy",
            "policyBlocked": True,
            "category": exc.category,
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    settings = get_settings()
    return {"service": "gen-api", "env": settings.app_env, "docs": "/docs"}
