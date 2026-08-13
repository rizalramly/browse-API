"""/shopping result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class ShoppingResult(BaseModel):
    title: str
    source: str | None = None
    link: str
    price: str | None = None
    delivery: str | None = None
    imageUrl: str | None = None
    rating: float | None = None
    ratingCount: int | None = None
    productId: str | None = None
    position: int


class ShoppingResponse(BaseSearchResponse):
    shopping: list[ShoppingResult] = []
