"""/search result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class Sitelink(BaseModel):
    title: str
    link: str


class OrganicResult(BaseModel):
    title: str
    link: str
    snippet: str | None = None
    date: str | None = None
    sitelinks: list[Sitelink] | None = None
    attributes: dict[str, str] | None = None
    position: int


class KnowledgeGraph(BaseModel):
    title: str
    type: str | None = None
    website: str | None = None
    imageUrl: str | None = None
    description: str | None = None
    descriptionSource: str | None = None
    descriptionLink: str | None = None
    attributes: dict[str, str] | None = None


class PeopleAlsoAsk(BaseModel):
    question: str
    snippet: str | None = None
    title: str | None = None
    link: str | None = None


class RelatedSearch(BaseModel):
    query: str


class SearchResponse(BaseSearchResponse):
    organic: list[OrganicResult] = []
    knowledgeGraph: KnowledgeGraph | None = None
    peopleAlsoAsk: list[PeopleAlsoAsk] | None = None
    relatedSearches: list[RelatedSearch] | None = None
