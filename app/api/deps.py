"""FastAPI dependencies. Tests override these to run without infrastructure."""
from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import Request

from app.config import ProviderName
from app.db import Database
from app.providers import SearchProvider, get_provider

ProviderFactory = Callable[[ProviderName], SearchProvider]


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_redis(request: Request) -> aioredis.Redis:
    client: aioredis.Redis = request.app.state.redis
    return client


def get_provider_factory() -> ProviderFactory:
    return get_provider
