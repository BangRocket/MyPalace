"""Live FSRS dynamics tests against real postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_promote_creates_dynamics_then_score_returns_breakdown_live(http_client):
    """End-to-end: create memory -> promote (auto-creates dynamics) ->
    get-dynamics shows access_count incremented -> score returns breakdown."""
    # Create a memory via the slice-1 endpoint so we have a real id.
    r = await http_client.post("/v1/memories", json={
        "user_id": "live-fsrs-1",
        "content": "User prefers Vim over Emacs",
        "memory_type": "preference",
    })
    assert r.status_code == 200, r.text
    mem_id = r.json()["data"]["id"]

    # Promote (auto-creates dynamics row).
    r = await http_client.post(
        f"/v1/memories/{mem_id}/promote",
        json={"user_id": "live-fsrs-1", "grade": 3, "signal_type": "used_in_response"},
    )
    assert r.status_code == 200, r.text
    dyn = r.json()["data"]
    assert dyn["memory_id"] == mem_id
    assert dyn["access_count"] == 1
    # Initial GOOD stability is w[2] = 2.3065 (first review).
    assert dyn["stability"] == pytest.approx(2.3065)

    # Get dynamics should show the same row.
    r = await http_client.get(
        f"/v1/memories/{mem_id}/dynamics?user_id=live-fsrs-1",
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["access_count"] == 1

    # Score should return the 4-key breakdown.
    r = await http_client.post(
        f"/v1/memories/{mem_id}/score",
        json={"user_id": "live-fsrs-1", "semantic_score": 0.8},
    )
    assert r.status_code == 200, r.text
    breakdown = r.json()["data"]
    assert set(breakdown.keys()) == {
        "composite_score", "fsrs_score", "retrievability", "storage_strength",
    }
    # composite = 0.6 * semantic + 0.4 * fsrs_score, so composite > 0.6 * 0.8 = 0.48.
    assert breakdown["composite_score"] > 0.48
    # Just-promoted memory: retrievability ~ 1.0 (no time elapsed).
    assert breakdown["retrievability"] == pytest.approx(1.0, abs=0.01)


@pytest.mark.asyncio
async def test_demote_records_failure_log_live(http_client):
    """Demote should write a MemoryAccessLog with grade=1 (AGAIN)."""
    r = await http_client.post("/v1/memories", json={
        "user_id": "live-fsrs-2",
        "content": "Stale fact about user",
        "memory_type": "semantic",
    })
    mem_id = r.json()["data"]["id"]

    r = await http_client.post(
        f"/v1/memories/{mem_id}/demote",
        json={"user_id": "live-fsrs-2", "reason": "user_correction"},
    )
    assert r.status_code == 200, r.text

    # Read access logs directly to confirm grade=1 was recorded. Scope to
    # the "test" tenant schema so the direct read sees what the HTTP demote
    # wrote (auth-disabled requests run as the default "test" tenant).
    from mypalace.database import async_session
    from mypalace.models import MemoryAccessLog
    from mypalace.tenancy import tenant_scope

    with tenant_scope("test"):
        async with async_session() as db:
            result = await db.execute(
                select(MemoryAccessLog).where(MemoryAccessLog.memory_id == mem_id),
            )
            logs = result.scalars().all()

    assert len(logs) == 1
    assert logs[0].grade == 1  # AGAIN
    assert logs[0].signal_type == "user_correction"
    assert logs[0].user_id == "live-fsrs-2"


@pytest.mark.asyncio
async def test_prune_access_logs_live(http_client):
    """Old access logs should be deleted by the prune endpoint."""
    # Seed dynamics + an old log directly via the DB. Scope to the "test"
    # tenant schema so the seed + the final read match where the HTTP prune
    # endpoint operates (auth-disabled requests run as the default tenant).
    from mypalace.database import async_session
    from mypalace.models import MemoryAccessLog, MemoryDynamics
    from mypalace.tenancy import tenant_scope

    mem_id = "live-prune-mem-1"
    user_id = "live-prune-user-1"

    with tenant_scope("test"):
        async with async_session() as db:
            db.add(MemoryDynamics(memory_id=mem_id, user_id=user_id, tenant_id="test"))
            await db.flush()
            # Old log: 100 days ago.
            old_log = MemoryAccessLog(
                memory_id=mem_id,
                user_id=user_id,
                tenant_id="test",
                grade=3,
                signal_type="used_in_response",
                retrievability_at_access=0.9,
                accessed_at=datetime.now(UTC) - timedelta(days=100),
            )
            # Recent log: today.
            recent_log = MemoryAccessLog(
                memory_id=mem_id,
                user_id=user_id,
                tenant_id="test",
                grade=3,
                signal_type="used_in_response",
                retrievability_at_access=0.95,
            )
            db.add(old_log)
            db.add(recent_log)
            await db.commit()

    # Prune logs older than 30 days.
    r = await http_client.post(
        "/v1/maintenance/prune-access-logs?retention_days=30",
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] == 1

    # Confirm only the recent log remains.
    with tenant_scope("test"):
        async with async_session() as db:
            result = await db.execute(
                select(MemoryAccessLog).where(MemoryAccessLog.memory_id == mem_id),
            )
            remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].retrievability_at_access == pytest.approx(0.95)
