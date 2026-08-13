"""/videos result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class VideoResult(BaseModel):
    title: str
    link: str
    snippet: str | None = None
    imageUrl: str | None = None
    duration: str | None = None
    channel: str | None = None
    source: str | None = None
    date: str | None = None
    position: int


class VideosResponse(BaseSearchResponse):
    videos: list[VideoResult] = []
