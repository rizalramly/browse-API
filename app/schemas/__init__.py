"""Canonical Gen schemas. Every provider normalizes into these."""
from app.schemas.autocomplete import AutocompleteResponse, Suggestion
from app.schemas.common import BaseSearchResponse, SearchParameters, SearchRequest
from app.schemas.images import ImageResult, ImagesResponse
from app.schemas.news import NewsResponse, NewsResult
from app.schemas.patents import PatentResult, PatentsResponse
from app.schemas.places import PlaceResult, PlacesResponse
from app.schemas.scholar import ScholarResponse, ScholarResult
from app.schemas.search import (
    KnowledgeGraph,
    OrganicResult,
    PeopleAlsoAsk,
    RelatedSearch,
    SearchResponse,
    Sitelink,
)
from app.schemas.shopping import ShoppingResponse, ShoppingResult
from app.schemas.videos import VideoResult, VideosResponse

__all__ = [
    "AutocompleteResponse",
    "BaseSearchResponse",
    "ImageResult",
    "ImagesResponse",
    "KnowledgeGraph",
    "NewsResponse",
    "NewsResult",
    "OrganicResult",
    "PatentResult",
    "PatentsResponse",
    "PeopleAlsoAsk",
    "PlaceResult",
    "PlacesResponse",
    "RelatedSearch",
    "ScholarResponse",
    "ScholarResult",
    "SearchParameters",
    "SearchRequest",
    "SearchResponse",
    "ShoppingResponse",
    "ShoppingResult",
    "Sitelink",
    "Suggestion",
    "VideoResult",
    "VideosResponse",
]
