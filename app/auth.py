"""API-key authentication via the X-API-KEY header, validated against Postgres."""
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.api.deps import get_db
from app.db import ApiKey, Database


async def require_api_key(
    db: Annotated[Database, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-KEY")] = None,
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-KEY header")
    api_key = await db.fetch_api_key(x_api_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return api_key
