"""/news result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class NewsResult(BaseModel):
    title: str
    link: str
    snippet: str | None = None
    date: str | None = None
    source: str | None = None
    imageUrl: str | None = None
    position: int


class NewsResponse(BaseSearchResponse):
    news: list[NewsResult] = []
