"""Live test: SKIP LOCKED claim semantics + handler dispatch against real Postgres."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_enqueue_and_claim_round_trip(palace_app):
    from palace.workers.queue import claim_next, complete_job, enqueue

    job = await enqueue(
        kind="test_kind",
        user_id="u1",
        payload={"hello": "world"},
        tenant_id="test",
    )
    assert job.id is not None

    # Claim — should be the row we just inserted.
    claimed = await claim_next()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.attempts == 1
    assert claimed.leased_until is not None
    assert claimed.payload_json == {"hello": "world"}

    # No more pending jobs (the only one is leased).
    second = await claim_next()
    assert second is None

    # Complete: the row moves to status=completed; subsequent claims still empty.
    await complete_job(job.id, {"answer": 42}, tenant_id="test")

    third = await claim_next()
    assert third is None

    # Verify result_json persisted.
    from sqlalchemy import select

    from palace.database import async_session
    from palace.models import ReflectionJob
    async with async_session() as db:
        result = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job.id))
        final = result.scalar_one()
    assert final.status == "completed"
    assert final.result_json == {"answer": 42}


async def test_two_claims_dont_collide(palace_app):
    """Insert one job; two claim_next calls in parallel — only one wins."""
    import asyncio

    from palace.workers.queue import claim_next, enqueue

    await enqueue(
        kind="test_kind", user_id="u1", payload={}, tenant_id="test",
    )

    a, b = await asyncio.gather(claim_next(), claim_next())
    # Exactly one of a/b is the claimed row; the other is None.
    claimed = [j for j in (a, b) if j is not None]
    none_count = sum(1 for j in (a, b) if j is None)
    assert len(claimed) == 1
    assert none_count == 1


async def test_failed_job_with_attempts_below_max_can_be_retried(palace_app):
    from palace.config import settings
    from palace.workers.queue import claim_next, enqueue, fail_job

    job = await enqueue(
        kind="test_kind", user_id="u1", payload={}, tenant_id="test",
    )
    claimed = await claim_next()
    assert claimed.id == job.id

    # Non-permanent failure: lease released, status stays pending.
    await fail_job(job.id, "transient", tenant_id="test", permanent=False)

    # Should be claimable again.
    again = await claim_next()
    assert again is not None
    assert again.id == job.id
    assert again.attempts == 2

    # Push to permanent failure on this attempt.
    await fail_job(job.id, "still bad", tenant_id="test", permanent=True)

    # Now max_attempts gate also blocks (attempts >= max).
    once_more = await claim_next()
    assert once_more is None or once_more.id != job.id
    _ = settings  # avoid unused import warning if path skipped
