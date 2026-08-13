"""Provider abstraction. Every acquisition backend implements this interface."""
from abc import ABC, abstractmethod
from typing import Any

from app.config import ProviderName, Vertical
from app.schemas import SearchRequest


class ProviderError(Exception):
    """Upstream provider failed (network, HTTP error, bad payload)."""


class UnsupportedVerticalError(ProviderError):
    """This provider cannot serve the requested vertical."""


class ProviderNotConfiguredError(ProviderError):
    """The configured provider has no implementation (yet)."""


class ProviderAuthError(ProviderError):
    """The upstream rejected our credentials — retrying cannot help."""


class SearchProvider(ABC):
    """A search acquisition backend.

    Implementations fetch raw results and normalize them into canonical Gen
    result blocks (e.g. {"organic": [...], "relatedSearches": [...]}). Blocks a
    provider cannot fill are omitted, never faked.
    """

    name: ProviderName

    @abstractmethod
    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        """Return normalized result blocks for the vertical.

        Raises UnsupportedVerticalError if the vertical isn't supported and
        ProviderError on upstream failure.
        """
