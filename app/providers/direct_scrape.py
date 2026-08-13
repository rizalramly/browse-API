"""DirectScrapeProvider — documented stub, disabled behind a feature flag.

The eventual design (Phase 4 of the original plan, deliberately deferred):

* Playwright (chromium) drives a real browser against the search engine's
  public results pages, one vertical at a time (start with /search).
* Rotating residential proxies; per-proxy request budgets and cooldowns.
* Fully isolated failure domain: its block-rate, captchas and bans must never
  affect SearXNG or commercial serving — the registry wraps it in its own
  circuit breaker like every other provider.
* Enabled only via DIRECT_SCRAPE_ENABLED=true after ToS / compliance sign-off.

Until implemented, activating the flag yields a provider that reports itself
unavailable rather than pretending to work.
"""
from typing import Any

from app.config import ProviderName, Vertical
from app.providers.base import ProviderError, SearchProvider
from app.schemas import SearchRequest


class DirectScrapeProvider(SearchProvider):
    name = ProviderName.DIRECT_SCRAPE

    async def search(self, request: SearchRequest, vertical: Vertical) -> dict[str, Any]:
        raise ProviderError(
            "direct-scrape provider is a stub: implementation requires Playwright, "
            "proxy budget and compliance sign-off (see module docstring)"
        )
