"""Postgres-backed job queue using SELECT ... FOR UPDATE SKIP LOCKED.

The claim query atomically picks one pending job whose lease has expired
(or is unleased), takes a lease for ``lease_seconds``, increments
``attempts``, and returns the row. Two workers calling claim_next
concurrently will get different rows (or one gets None) thanks to
SKIP LOCKED.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from palace.config import settings
from palace.database import async_session
from palace.models import DEFAULT_TENANT_ID, ReflectionJob, utcnow
from palace.observability.metrics import job_total

logger = logging.getLogger(__name__)


async def enqueue(
    kind: str,
    user_id: str,
    payload: dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
) -> ReflectionJob:
    """Insert a pending job that the worker will pick up. Returns the row."""
    async with async_session() as db:
        job = ReflectionJob(
            tenant_id=tenant_id,
            kind=kind,
            user_id=user_id,
            status="pending",
            payload_json=payload,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
    job_total.labels(kind=kind, outcome="enqueued").inc()
    return job


async def claim_next(
    lease_seconds: int | None = None,
) -> ReflectionJob | None:
    """Atomically claim the oldest unleased pending job (across tenants).

    Workers call this in a poll loop. Returns ``None`` if the queue is
    empty or every pending row is currently leased to another worker.
    """
    lease_seconds = lease_seconds or settings.worker_lease_seconds
    new_lease_expires = utcnow() + timedelta(seconds=lease_seconds)

    # Single round-trip with FOR UPDATE SKIP LOCKED. We RETURNING the row's
    # columns so the worker doesn't need a follow-up SELECT.
    sql = text("""
        WITH claimed AS (
            SELECT id
            FROM reflection_jobs
            WHERE status = 'pending'
              AND (leased_until IS NULL OR leased_until < :now)
              AND attempts < :max_attempts
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE reflection_jobs
        SET leased_until = :lease, attempts = attempts + 1
        FROM claimed
        WHERE reflection_jobs.id = claimed.id
        RETURNING reflection_jobs.id
    """)
    async with async_session() as db:
        result = await db.execute(sql, {
            "now": utcnow(),
            "max_attempts": settings.worker_max_attempts,
            "lease": new_lease_expires,
        })
        row = result.first()
        await db.commit()
        if row is None:
            return None
        # Re-load to get the full ORM model with the new attempts/lease values.
        from sqlalchemy import select
        result = await db.execute(
            select(ReflectionJob).where(ReflectionJob.id == row[0]),
        )
        return result.scalar_one()


async def extend_lease(job_id: str, additional_seconds: int) -> bool:
    """Push leased_until forward — for long-running handlers."""
    new_lease = utcnow() + timedelta(seconds=additional_seconds)
    async with async_session() as db:
        result = await db.execute(
            text("UPDATE reflection_jobs SET leased_until = :lease "
                 "WHERE id = :id AND status = 'pending'"),
            {"lease": new_lease, "id": job_id},
        )
        await db.commit()
        return result.rowcount > 0


async def complete_job(
    job_id: str,
    result: Any,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> None:
    from palace.job_service import _serialize_result
    serializable = _serialize_result(result)
    async with async_session() as db:
        await db.execute(
            text(
                "UPDATE reflection_jobs SET status='completed', "
                "result_json = CAST(:r AS JSONB), completed_at = :now, "
                "leased_until = NULL "
                "WHERE id = :id AND tenant_id = :tenant",
            ),
            {
                "r": _json_dumps(serializable),
                "now": utcnow(),
                "id": job_id,
                "tenant": tenant_id,
            },
        )
        await db.commit()


async def fail_job(
    job_id: str,
    error: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    permanent: bool = False,
) -> None:
    """Record a failure. ``permanent=True`` (e.g. attempts exhausted) marks
    status='failed'; otherwise releases the lease so the next worker can
    try again, leaving status='pending'."""
    if permanent:
        async with async_session() as db:
            await db.execute(
                text(
                    "UPDATE reflection_jobs SET status='failed', "
                    "error = :err, completed_at = :now, leased_until = NULL "
                    "WHERE id = :id AND tenant_id = :tenant",
                ),
                {"err": error, "now": utcnow(), "id": job_id, "tenant": tenant_id},
            )
            await db.commit()
    else:
        async with async_session() as db:
            await db.execute(
                text(
                    "UPDATE reflection_jobs SET error = :err, "
                    "leased_until = NULL "
                    "WHERE id = :id AND tenant_id = :tenant",
                ),
                {"err": error, "id": job_id, "tenant": tenant_id},
            )
            await db.commit()


def _json_dumps(value: Any) -> str:
    """Serialize a result value to a JSON string for inline parameter binding.
    Using a CAST so asyncpg/Postgres parses it into JSONB instead of treating
    the string as a literal."""
    import json as _json
    return _json.dumps(value, default=str)
