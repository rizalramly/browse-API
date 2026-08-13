"""Settings routing defaults and overrides."""
from app.config import ProviderName, Settings, Vertical


def test_default_provider_routing() -> None:
    settings = Settings(_env_file=None)
    assert settings.provider_for(Vertical.SEARCH) is ProviderName.GENXNG
    assert settings.provider_for(Vertical.NEWS) is ProviderName.GENXNG
    assert settings.provider_for(Vertical.SCHOLAR) is ProviderName.COMMERCIAL
    assert settings.provider_for(Vertical.PATENTS) is ProviderName.COMMERCIAL
    assert settings.direct_scrape_enabled is False


def test_provider_map_override_merges_over_defaults() -> None:
    settings = Settings(_env_file=None, provider_map={Vertical.SEARCH: ProviderName.COMMERCIAL})
    assert settings.provider_for(Vertical.SEARCH) is ProviderName.COMMERCIAL
    # untouched verticals keep their defaults
    assert settings.provider_for(Vertical.IMAGES) is ProviderName.GENXNG


def test_credit_costs() -> None:
    settings = Settings(_env_file=None)
    assert settings.credits_for(Vertical.SEARCH) == 1
    assert settings.credits_for(Vertical.PLACES) == 2
    assert settings.credits_for(Vertical.SCHOLAR) == 2
    assert settings.credits_for(Vertical.PATENTS) == 2


def test_cache_ttls_are_per_vertical() -> None:
    settings = Settings(_env_file=None)
    assert settings.ttl_for(Vertical.NEWS) < settings.ttl_for(Vertical.SEARCH)
