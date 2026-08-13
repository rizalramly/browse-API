"""gen-api: self-hosted Gen search API.

search/images/news/videos/autocomplete are served by GenXNG (the on-prem
metasearch backend); remaining verticals answer 501 until the commercial
provider is configured.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.verticals import router as verticals_router
from app.config import get_settings
from app.db import Database
from app.logging_config import setup_logging

setup_logging(get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db = Database(settings.database_url)
    await db.connect()
    app.state.db = db
    app.state.redis = aioredis.from_url(settings.redis_url)
    yield
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


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    settings = get_settings()
    return {"service": "gen-api", "env": settings.app_env, "docs": "/docs"}
