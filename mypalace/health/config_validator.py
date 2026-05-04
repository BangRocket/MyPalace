"""Boot-time config validation.

Catches malformed env-var values before the service starts answering
requests. Prefer crashing on lifespan startup with a clear message over
crashing on the first request with a confusing traceback.
"""

from __future__ import annotations


class ConfigError(RuntimeError):
    """Raised when a setting fails validation. Lifespan converts this
    into a clean fatal error."""


def validate_config() -> list[str]:
    """Run all config validators. Returns a list of warnings (non-fatal).

    Raises ConfigError on any fatal misconfiguration so the service
    refuses to start.
    """
    from mypalace.auth.tenant import is_valid_tenant_id
    from mypalace.config import settings

    warnings: list[str] = []

    # default_tenant_id must satisfy the tenant_id regex.
    if not is_valid_tenant_id(settings.default_tenant_id):
        raise ConfigError(
            f"PALACE_DEFAULT_TENANT_ID={settings.default_tenant_id!r} is "
            "invalid; must match [a-z0-9_]{1,32}",
        )

    # bootstrap admin key (if present) must look right.
    if settings.bootstrap_admin_key is not None:
        from mypalace.auth.key_service import _split
        if _split(settings.bootstrap_admin_key) is None:
            raise ConfigError(
                "PALACE_BOOTSTRAP_ADMIN_KEY is malformed; must match "
                "pk_live_<32 alphanumeric chars>",
            )

    # database_url should be asyncpg, not psycopg.
    if settings.database_url.startswith("postgresql://") and "asyncpg" not in settings.database_url:
        raise ConfigError(
            "PALACE_DATABASE_URL must use the asyncpg driver "
            "(postgresql+asyncpg://…); got a bare postgresql:// URL",
        )

    # rate-limit needs Redis.
    if settings.rate_limit_enabled and not settings.redis_url:
        raise ConfigError(
            "PALACE_RATE_LIMIT_ENABLED=true requires PALACE_REDIS_URL to be set",
        )

    # Worker queue is opt-in but warn if enabled without Redis (cache
    # invalidation across processes won't work properly).
    if settings.worker_queue_enabled and not settings.redis_url:
        warnings.append(
            "PALACE_WORKER_QUEUE_ENABLED=true without PALACE_REDIS_URL: "
            "the cache and event broker will fall back to in-process mode, "
            "which doesn't share state across web + worker processes.",
        )

    # log_format must be one of the supported values.
    if settings.log_format not in ("pretty", "json"):
        raise ConfigError(
            f"PALACE_LOG_FORMAT={settings.log_format!r} invalid; "
            "must be 'pretty' or 'json'",
        )

    # Cache TTLs must be positive.
    if settings.cache_ttl_search_seconds <= 0:
        raise ConfigError(
            f"PALACE_CACHE_TTL_SEARCH must be positive; got "
            f"{settings.cache_ttl_search_seconds}",
        )

    return warnings
