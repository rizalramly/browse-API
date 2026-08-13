"""/scholar result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class ScholarResult(BaseModel):
    title: str
    link: str
    publicationInfo: str | None = None
    snippet: str | None = None
    year: int | None = None
    citedBy: int | None = None


class ScholarResponse(BaseSearchResponse):
    organic: list[ScholarResult] = []
