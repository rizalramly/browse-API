"""Application settings.

A single pydantic-settings module. Every vertical is mapped to a provider here;
Phase 1+ providers read this mapping and nothing else decides routing.
"""
from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Vertical(StrEnum):
    SEARCH = "search"
    IMAGES = "images"
    NEWS = "news"
    PLACES = "places"
    VIDEOS = "videos"
    SHOPPING = "shopping"
    SCHOLAR = "scholar"
    PATENTS = "patents"
    AUTOCOMPLETE = "autocomplete"


class ProviderName(StrEnum):
    # "genxng" is the user-facing name of the on-prem metasearch backend
    # (implemented by SearXNG under the hood; infra names keep SEARXNG_*).
    GENXNG = "genxng"
    COMMERCIAL = "commercial"
    DIRECT_SCRAPE = "direct_scrape"


DEFAULT_PROVIDER_MAP: dict[Vertical, ProviderName] = {
    Vertical.SEARCH: ProviderName.GENXNG,
    Vertical.IMAGES: ProviderName.GENXNG,
    Vertical.NEWS: ProviderName.GENXNG,
    Vertical.VIDEOS: ProviderName.GENXNG,
    Vertical.AUTOCOMPLETE: ProviderName.GENXNG,
    # High-fidelity verticals need a commercial search API (Phase 3)
    Vertical.PLACES: ProviderName.COMMERCIAL,
    Vertical.SHOPPING: ProviderName.COMMERCIAL,
    Vertical.SCHOLAR: ProviderName.COMMERCIAL,
    Vertical.PATENTS: ProviderName.COMMERCIAL,
}

# Cache TTL per vertical, in seconds. RAG tolerates long TTLs; news/prices do not.
DEFAULT_CACHE_TTL: dict[Vertical, int] = {
    Vertical.SEARCH: 6 * 3600,
    Vertical.IMAGES: 6 * 3600,
    Vertical.NEWS: 300,
    Vertical.PLACES: 24 * 3600,
    Vertical.VIDEOS: 6 * 3600,
    Vertical.SHOPPING: 300,
    Vertical.SCHOLAR: 24 * 3600,
    Vertical.PATENTS: 24 * 3600,
    Vertical.AUTOCOMPLETE: 3600,
}

# Credits deducted per successful query.
DEFAULT_CREDIT_COST: dict[Vertical, int] = {
    **{v: 1 for v in Vertical},
    Vertical.PLACES: 2,
    Vertical.SCHOLAR: 2,
    Vertical.PATENTS: 2,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    http_timeout: float = 10.0

    # Per-key token bucket; qps <= 0 disables rate limiting.
    rate_limit_qps: float = 5.0
    rate_limit_burst: int = 10

    # Provider resilience: retries with exponential backoff + circuit breaker.
    provider_max_retries: int = 2
    provider_backoff_seconds: float = 0.5
    breaker_failure_threshold: int = 5
    breaker_recovery_seconds: float = 30.0

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://gen:gen@postgres:5432/gen"
    searxng_url: str = "http://searxng:8080"

    # Commercial Gen-compatible search API (Phase 3). The key comes from
    # secrets (COMMERCIAL_API_KEY via Vault or env), never from here.
    commercial_base_url: str = ""
    # When true, /search responses served by a non-commercial provider are
    # enriched with knowledgeGraph/peopleAlsoAsk from the commercial provider.
    search_enrichment: bool = False

    # Vault is optional; app/secrets.py falls back to env vars when unset.
    vault_addr: str | None = None
    vault_token: str | None = None
    vault_mount: str = "secret"
    vault_path: str = "gen-api"

    # Override per-vertical routing via env, e.g.
    # PROVIDER_MAP='{"search": "commercial"}' merges over the defaults.
    provider_map: dict[Vertical, ProviderName] = {}
    cache_ttl: dict[Vertical, int] = {}
    credit_cost: dict[Vertical, int] = {}

    direct_scrape_enabled: bool = False

    def provider_for(self, vertical: Vertical) -> ProviderName:
        return self.provider_map.get(vertical, DEFAULT_PROVIDER_MAP[vertical])

    def ttl_for(self, vertical: Vertical) -> int:
        return self.cache_ttl.get(vertical, DEFAULT_CACHE_TTL[vertical])

    def credits_for(self, vertical: Vertical) -> int:
        return self.credit_cost.get(vertical, DEFAULT_CREDIT_COST[vertical])


@lru_cache
def get_settings() -> Settings:
    return Settings()
