"""Live intention tests against real postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_set_then_check_fires_keyword_trigger_live(http_client):
    """Set a keyword-trigger intention, then check with a matching message —
    the intention fires."""
    r = await http_client.post("/v1/intentions", json={
        "user_id": "live-int-1",
        "content": "Remind about the standup",
        "trigger_conditions": {"type": "keyword", "keywords": ["standup"]},
        "priority": 5,
    })
    assert r.status_code == 200, r.text
    intention_id = r.json()["data"]["id"]

    r = await http_client.post("/v1/intentions/check", json={
        "user_id": "live-int-1",
        "message": "When's the standup today?",
    })
    assert r.status_code == 200, r.text
    fired = r.json()["data"]
    assert len(fired) == 1
    assert fired[0]["id"] == intention_id
    assert fired[0]["trigger_type"] == "keyword"
    assert fired[0]["priority"] == 5
    assert "standup" in fired[0]["match_details"]["matched_keywords"]


@pytest.mark.asyncio
async def test_fire_once_deletes_after_first_fire_live(http_client):
    """fire_once=True intentions vanish from the table after the first fire."""
    r = await http_client.post("/v1/intentions", json={
        "user_id": "live-int-2",
        "content": "Remind about lunch",
        "trigger_conditions": {"type": "keyword", "keywords": ["lunch"]},
        "fire_once": True,
    })
    assert r.status_code == 200, r.text
    intention_id = r.json()["data"]["id"]

    # First check fires.
    r = await http_client.post("/v1/intentions/check", json={
        "user_id": "live-int-2",
        "message": "Lunch plans?",
    })
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1

    # Confirm the intention row is gone.
    from mypalace.database import async_session
    from mypalace.models import Intention

    async with async_session() as db:
        result = await db.execute(
            select(Intention).where(Intention.id == intention_id),
        )
        assert result.scalar_one_or_none() is None

    # Second check returns nothing.
    r = await http_client.post("/v1/intentions/check", json={
        "user_id": "live-int-2",
        "message": "Lunch plans?",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_cleanup_expired_intentions_live(http_client):
    """Intentions with expires_at in the past are deleted by the cleanup
    endpoint."""
    # Scope the seed + final read to the "test" tenant schema so they match
    # where the HTTP cleanup endpoint operates (auth-disabled requests run
    # as the default "test" tenant).
    from mypalace.database import async_session
    from mypalace.models import Intention
    from mypalace.tenancy import tenant_scope

    user_id = "live-int-3"
    past = datetime.now(UTC) - timedelta(days=1)
    future = datetime.now(UTC) + timedelta(days=1)

    with tenant_scope("test"):
        async with async_session() as db:
            db.add(Intention(
                user_id=user_id,
                tenant_id="test",
                content="expired one",
                trigger_conditions={"type": "keyword", "keywords": ["x"]},
                expires_at=past,
            ))
            db.add(Intention(
                user_id=user_id,
                tenant_id="test",
                content="still valid",
                trigger_conditions={"type": "keyword", "keywords": ["y"]},
                expires_at=future,
            ))
            await db.commit()

    r = await http_client.post("/v1/maintenance/cleanup-intentions")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] == 1

    with tenant_scope("test"):
        async with async_session() as db:
            result = await db.execute(
                select(Intention).where(Intention.user_id == user_id),
            )
            remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].content == "still valid"
