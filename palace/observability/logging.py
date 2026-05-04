"""structlog configuration.

Two output formats:
  - "pretty"  → colored console output (dev default)
  - "json"    → newline-delimited JSON (production)

Every log call gets the bound context (request_id, tenant_id, key_id) for
free, since loggers are bind-aware. Use ``log.bind(**ctx).info("...")``
inside request handlers.
"""

from __future__ import annotations

import logging
import sys

import structlog

from palace.config import settings


def configure_logging() -> None:
    """Idempotent global configuration. Safe to call from lifespan startup
    and from test setup."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Quiet down noisy upstream loggers in JSON mode.
    if settings.log_format == "json":
        for noisy in ("uvicorn.access", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None):
    """Convenience wrapper: structlog.get_logger() with auto-configure."""
    return structlog.get_logger(name)


def bind_request_context(**kwargs) -> None:
    """Bind context vars that propagate to every log call in this request."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
