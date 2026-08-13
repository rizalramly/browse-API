"""/patents result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class PatentResult(BaseModel):
    title: str
    snippet: str | None = None
    link: str
    assignee: str | None = None
    inventor: str | None = None
    priorityDate: str | None = None
    filingDate: str | None = None
    grantDate: str | None = None
    publicationNumber: str | None = None
    figures: list[str] | None = None


class PatentsResponse(BaseSearchResponse):
    organic: list[PatentResult] = []
