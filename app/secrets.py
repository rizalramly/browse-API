"""Secret resolution: Vault first, environment variable fallback.

Provider keys and proxy credentials must come through here — never hardcoded.
"""
import logging
import os

from app.config import get_settings

logger = logging.getLogger(__name__)

_vault_cache: dict[str, str] | None = None


def _read_vault() -> dict[str, str]:
    """Read the whole KV-v2 secret once and cache it for the process lifetime."""
    global _vault_cache
    if _vault_cache is not None:
        return _vault_cache

    settings = get_settings()
    if not settings.vault_addr or not settings.vault_token:
        _vault_cache = {}
        return _vault_cache

    try:
        import hvac

        client = hvac.Client(url=settings.vault_addr, token=settings.vault_token)
        response = client.secrets.kv.v2.read_secret_version(
            path=settings.vault_path, mount_point=settings.vault_mount
        )
        _vault_cache = dict(response["data"]["data"])
        logger.info("Loaded %d secrets from Vault", len(_vault_cache))
    except Exception:
        logger.exception("Vault read failed; falling back to environment variables")
        _vault_cache = {}
    return _vault_cache


def get_secret(key: str, default: str | None = None) -> str | None:
    """Resolve a secret by name: Vault KV entry, then env var, then default."""
    vault_value = _read_vault().get(key)
    if vault_value is not None:
        return vault_value
    return os.environ.get(key, default)
