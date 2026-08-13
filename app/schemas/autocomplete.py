"""/autocomplete result blocks."""
from pydantic import BaseModel

from app.schemas.common import BaseSearchResponse


class Suggestion(BaseModel):
    value: str


class AutocompleteResponse(BaseSearchResponse):
    suggestions: list[Suggestion] = []
