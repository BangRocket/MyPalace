"""Deep health checks — ping each configured backend, report per-backend status.

Used by the `/health/deep` route. Each check is independent and bounded
by a per-check timeout so one slow backend doesn't hold up the whole
response. Returns aggregate `ok`/`degraded` + per-backend detail so
operators can pinpoint exactly what's wrong.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    ok: bool
    elapsed_ms: int
    detail: str
    configured: bool = True


async def _check_postgres(timeout: float = 2.0) -> HealthCheckResult:
    """Ping Postgres via the existing async engine (cheap SELECT 1)."""
    start = time.perf_counter()
    try:
        from sqlalchemy import text

        from mypalace.database import engine

        async def _ping():
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                row = result.scalar_one()
                if row != 1:
                    raise RuntimeError(f"unexpected SELECT 1 result: {row!r}")

        await asyncio.wait_for(_ping(), timeout=timeout)
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult("postgres", ok=True, elapsed_ms=elapsed, detail="ok")
    except TimeoutError:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "postgres", ok=False, elapsed_ms=elapsed,
            detail=f"timeout after {timeout}s",
        )
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "postgres", ok=False, elapsed_ms=elapsed, detail=repr(e)[:200],
        )


async def _check_qdrant(timeout: float = 2.0) -> HealthCheckResult:
    """List collections — cheapest non-trivial Qdrant call."""
    start = time.perf_counter()
    try:
        from mypalace.vector import vector_store
        await asyncio.wait_for(
            vector_store.client.get_collections(), timeout=timeout,
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult("qdrant", ok=True, elapsed_ms=elapsed, detail="ok")
    except TimeoutError:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "qdrant", ok=False, elapsed_ms=elapsed,
            detail=f"timeout after {timeout}s",
        )
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "qdrant", ok=False, elapsed_ms=elapsed, detail=repr(e)[:200],
        )


async def _check_falkordb(timeout: float = 2.0) -> HealthCheckResult:
    """Optional. Returns configured=False when PALACE_FALKORDB_URL unset."""
    start = time.perf_counter()
    from mypalace.config import settings

    if not settings.falkordb_url:
        return HealthCheckResult(
            "falkordb", ok=True, elapsed_ms=0,
            detail="not configured", configured=False,
        )

    try:
        from mypalace.graph.client import FalkorClient

        client = FalkorClient(settings.falkordb_url)

        async def _ping():
            # Run a no-op Cypher against the default tenant graph.
            await client.query("default", "RETURN 1")

        await asyncio.wait_for(_ping(), timeout=timeout)
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult("falkordb", ok=True, elapsed_ms=elapsed, detail="ok")
    except TimeoutError:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "falkordb", ok=False, elapsed_ms=elapsed,
            detail=f"timeout after {timeout}s",
        )
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "falkordb", ok=False, elapsed_ms=elapsed, detail=repr(e)[:200],
        )


async def _check_redis(timeout: float = 2.0) -> HealthCheckResult:
    """Optional. Returns configured=False when PALACE_REDIS_URL unset."""
    start = time.perf_counter()
    from mypalace.config import settings

    if not settings.redis_url:
        return HealthCheckResult(
            "redis", ok=True, elapsed_ms=0,
            detail="not configured", configured=False,
        )

    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url, decode_responses=True)
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout)
        finally:
            await client.aclose()
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult("redis", ok=True, elapsed_ms=elapsed, detail="ok")
    except TimeoutError:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "redis", ok=False, elapsed_ms=elapsed,
            detail=f"timeout after {timeout}s",
        )
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return HealthCheckResult(
            "redis", ok=False, elapsed_ms=elapsed, detail=repr(e)[:200],
        )


async def check_all_backends(
    timeout: float = 2.0,
) -> tuple[bool, list[HealthCheckResult]]:
    """Run all backend checks in parallel. Returns (overall_ok, per_backend).

    `overall_ok` is False iff any *configured* backend failed. Unconfigured
    optional backends (FalkorDB / Redis when their env vars are unset) are
    excluded from the overall verdict.
    """
    results = await asyncio.gather(
        _check_postgres(timeout=timeout),
        _check_qdrant(timeout=timeout),
        _check_falkordb(timeout=timeout),
        _check_redis(timeout=timeout),
    )
    overall_ok = all(r.ok for r in results if r.configured)
    return overall_ok, list(results)


def to_dict(result: HealthCheckResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "configured": result.configured,
        "elapsed_ms": result.elapsed_ms,
        "detail": result.detail,
    }
