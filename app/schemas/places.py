"""/places result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class PlaceResult(BaseModel):
    title: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    ratingCount: int | None = None
    type: str | None = None
    types: list[str] | None = None
    website: str | None = None
    phoneNumber: str | None = None
    cid: str | None = None
    placeId: str | None = None
    position: int


class PlacesResponse(BaseSearchResponse):
    places: list[PlaceResult] = []
