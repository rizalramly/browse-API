"""/images result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class ImageResult(BaseModel):
    title: str
    imageUrl: str
    thumbnailUrl: str | None = None
    source: str | None = None
    domain: str | None = None
    link: str
    imageWidth: int | None = None
    imageHeight: int | None = None
    position: int


class ImagesResponse(BaseSearchResponse):
    images: list[ImageResult] = []
