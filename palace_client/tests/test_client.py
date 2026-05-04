"""PalaceClient unit tests using httpx.MockTransport — no live server."""

import json

import httpx
import pytest

from palace_client import (
    Memory,
    PalaceClient,
    PalaceError,
    PalaceNotFound,
    PalaceTransport,
    ScoredMemory,
)


def make_envelope(data, count: int | None = None):
    """Wrap a payload in Palace's ApiResponse envelope."""
    return {
        "data": data,
        "meta": {"count": count if count is not None else 1, "took_ms": 0},
    }


def fake_memory(id: str = "m1", **overrides) -> dict:
    base = {
        "id": id,
        "user_id": "u1",
        "agent_id": None,
        "content": "hello",
        "memory_type": "semantic",
        "source": None,
        "importance": 1.0,
        "created_at": "2026-05-03T19:33:40.210487+00:00",
        "updated_at": "2026-05-03T19:33:40.210487+00:00",
        "accessed_at": None,
        "access_count": 0,
        "metadata": None,
    }
    base.update(overrides)
    return base


def make_client(handler) -> PalaceClient:
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.AsyncClient(
        transport=transport, base_url="http://palace.test"
    )
    return PalaceClient(base_url="http://palace.test", client=httpx_client)


# ---- memory CRUD ----

@pytest.mark.asyncio
async def test_create_memory():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(fake_memory(id="new-1")))

    client = make_client(handler)
    mem = await client.create(
        user_id="u1", content="hello", memory_type="preference",
    )

    assert captured["url"] == "http://palace.test/v1/memories"
    assert captured["body"]["user_id"] == "u1"
    assert captured["body"]["content"] == "hello"
    assert captured["body"]["memory_type"] == "preference"
    assert isinstance(mem, Memory)
    assert mem.id == "new-1"


@pytest.mark.asyncio
async def test_add_batch():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(
            [fake_memory(id="a1"), fake_memory(id="a2")], count=2,
        ))

    client = make_client(handler)
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    result = await client.add(messages=msgs, user_id="u1", agent_id="clara")

    assert captured["url"] == "http://palace.test/v1/memories/batch"
    assert captured["body"]["messages"] == msgs
    assert captured["body"]["agent_id"] == "clara"
    assert captured["body"]["infer"] is False  # spec D7 default
    assert len(result) == 2
    assert result[0].id == "a1"


@pytest.mark.asyncio
async def test_search():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope([
            {
                "id": "m1", "content": "vim", "memory_type": "preference",
                "importance": 1.0, "score": 0.93,
                "created_at": "2026-05-03T19:33:40.210487+00:00",
            },
        ], count=1))

    client = make_client(handler)
    results = await client.search(query="editor", user_id="u1")
    assert len(results) == 1
    assert isinstance(results[0], ScoredMemory)
    assert results[0].score == 0.93


@pytest.mark.asyncio
async def test_get_memory():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/memories/m1"
        return httpx.Response(200, json=make_envelope(fake_memory(id="m1")))

    client = make_client(handler)
    mem = await client.get("m1")
    assert mem.id == "m1"


@pytest.mark.asyncio
async def test_get_memory_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Memory not found"})

    client = make_client(handler)
    with pytest.raises(PalaceNotFound) as exc_info:
        await client.get("missing")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_memory():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(
            fake_memory(id="m1", importance=5.0),
        ))

    client = make_client(handler)
    mem = await client.update("m1", importance=5.0)
    assert captured["body"] == {"importance": 5.0}
    assert mem.importance == 5.0


@pytest.mark.asyncio
async def test_delete_memory_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope({"deleted": True}))

    client = make_client(handler)
    result = await client.delete("m1")
    assert result is None


@pytest.mark.asyncio
async def test_get_all():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(
            [fake_memory(id="a"), fake_memory(id="b")], count=2,
        ))

    client = make_client(handler)
    result = await client.get_all(
        user_id="u1", agent_id="clara", run_id="r1",
        memory_type="pref", metadata={"k": "v"}, limit=25, offset=10,
    )
    assert captured["url"] == "http://palace.test/v1/memories/list"
    assert captured["body"] == {
        "user_id": "u1", "agent_id": "clara", "run_id": "r1",
        "memory_type": "pref", "metadata": {"k": "v"},
        "limit": 25, "offset": 10,
    }
    assert len(result) == 2


@pytest.mark.asyncio
async def test_delete_all_returns_count():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=make_envelope({"deleted": 7}, count=7))

    client = make_client(handler)
    deleted = await client.delete_all(user_id="u1", agent_id="clara")
    assert deleted == 7
    assert captured["url"].startswith("http://palace.test/v1/users/u1/memories")
    assert captured["params"] == {"agent_id": "clara"}


@pytest.mark.asyncio
async def test_list_for_user():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/memories"
        return httpx.Response(200, json=make_envelope([fake_memory()], count=1))

    client = make_client(handler)
    mems = await client.list_for_user("u1", limit=20)
    assert len(mems) == 1


# ---- error handling ----

@pytest.mark.asyncio
async def test_500_raises_palace_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = make_client(handler)
    with pytest.raises(PalaceError) as exc_info:
        await client.get("m1")
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_transport_error_raises_palace_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = make_client(handler)
    with pytest.raises(PalaceTransport):
        await client.health()


# ---- sessions ----

@pytest.mark.asyncio
async def test_create_session():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope({
            "id": "s1", "user_id": "u1", "title": "T",
            "summary": None,
            "created_at": "2026-05-03T19:33:40.210487+00:00",
            "updated_at": "2026-05-03T19:33:40.210487+00:00",
        }))

    client = make_client(handler)
    s = await client.create_session("u1", title="T")
    assert s.id == "s1"
    assert captured["body"] == {"user_id": "u1", "title": "T"}


@pytest.mark.asyncio
async def test_get_session_with_messages():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope({
            "id": "s1", "user_id": "u1", "title": None, "summary": None,
            "created_at": "2026-05-03T19:33:40.210487+00:00",
            "updated_at": "2026-05-03T19:33:40.210487+00:00",
            "messages": [
                {
                    "id": "msg-1", "user_id": "u1", "role": "user",
                    "content": "hi",
                    "created_at": "2026-05-03T19:33:40.210487+00:00",
                },
            ],
        }))

    client = make_client(handler)
    s = await client.get_session("s1")
    assert s.id == "s1"
    assert len(s.messages) == 1
    assert s.messages[0].role == "user"


@pytest.mark.asyncio
async def test_add_message():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope({
            "id": "msg-2", "user_id": "u1", "role": "user", "content": "x",
            "created_at": "2026-05-03T19:33:40.210487+00:00",
        }))

    client = make_client(handler)
    msg = await client.add_message("s1", user_id="u1", role="user", content="x")
    assert "/v1/sessions/s1/messages" in captured["url"]
    assert captured["body"] == {"user_id": "u1", "role": "user", "content": "x"}
    assert msg.id == "msg-2"


@pytest.mark.asyncio
async def test_update_session():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope({
            "id": "s1", "user_id": "u1", "title": "Updated", "summary": None,
            "created_at": "2026-05-03T19:33:40.210487+00:00",
            "updated_at": "2026-05-03T19:33:40.210487+00:00",
        }))

    client = make_client(handler)
    s = await client.update_session("s1", title="Updated")
    assert captured["body"] == {"title": "Updated"}
    assert s.title == "Updated"


@pytest.mark.asyncio
async def test_delete_session():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope({"deleted": True}))

    client = make_client(handler)
    result = await client.delete_session("s1")
    assert result is None


# ---- context ----

@pytest.mark.asyncio
async def test_assemble_context():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope({
            "memories": [{"id": "m1", "content": "x"}],
            "recent_messages": [{"role": "user", "content": "y"}],
            "summary": "z",
        }, count=2))

    client = make_client(handler)
    ctx = await client.assemble_context(
        user_id="u1", query="q", session_id="s1",
    )
    assert len(ctx.memories) == 1
    assert ctx.summary == "z"


# ---- health ----

@pytest.mark.asyncio
async def test_health():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = make_client(handler)
    h = await client.health()
    assert h == {"status": "ok"}


# ---- context manager ----

@pytest.mark.asyncio
async def test_async_context_manager_owns_client():
    """When client= is passed, aclose() doesn't touch it."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"}))
    httpx_client = httpx.AsyncClient(transport=transport, base_url="http://palace.test")
    async with PalaceClient(base_url="http://palace.test", client=httpx_client) as c:
        h = await c.health()
        assert h == {"status": "ok"}
    # The injected client should still be usable (PalaceClient didn't close it).
    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_2xx_with_malformed_json_raises_palace_error():
    """Spec: a 200 with garbage body is a server bug. Fail loudly."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    client = make_client(handler)
    with pytest.raises(PalaceError) as exc_info:
        await client.health()
    assert exc_info.value.status_code == 200
    assert "not valid JSON" in exc_info.value.message


@pytest.mark.asyncio
async def test_4xx_with_html_body_still_raises_palace_error():
    """Error bodies are best-effort — a 502 HTML page should still surface
    as PalaceError with status_code 502."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"<html><body>Bad Gateway</body></html>")

    client = make_client(handler)
    with pytest.raises(PalaceError) as exc_info:
        await client.get("any-id")
    assert exc_info.value.status_code == 502


# ---- episodes / reflection ----

def fake_episode(id: str = "ep1", **overrides) -> dict:
    base = {
        "id": id, "user_id": "u1", "agent_id": None,
        "content": "x", "summary": "s",
        "participants": [], "topics": [],
        "emotional_tone": "neutral", "significance": 0.5,
        "timestamp": "2026-05-03T19:33:40.210487+00:00",
        "session_id": None, "message_count": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_reflect_session_sync():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=make_envelope(
            [fake_episode("ep-new")], count=1,
        ))

    client = make_client(handler)
    result = await client.reflect_session(
        messages=[{"role": "user", "content": "hi"}],
        user_id="u1", agent_id="clara", session_id="s-1",
        mode="sync",
    )
    assert captured["url"].startswith("http://palace.test/v1/reflection/session")
    assert captured["params"] == {"mode": "sync"}
    assert captured["body"]["user_id"] == "u1"
    assert captured["body"]["agent_id"] == "clara"
    assert captured["body"]["session_id"] == "s-1"
    assert isinstance(result, list)
    assert result[0].id == "ep-new"


@pytest.mark.asyncio
async def test_reflect_session_async_returns_job_pending():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json=make_envelope(
            {"job_id": "j1", "status": "pending"},
        ))

    client = make_client(handler)
    result = await client.reflect_session(
        messages=[{"role": "user", "content": "hi"}], user_id="u1",
    )
    from palace_client import JobPending
    assert isinstance(result, JobPending)
    assert result.job_id == "j1"


@pytest.mark.asyncio
async def test_search_episodes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope(
            [fake_episode("ep-1", score=0.95)], count=1,
        ))

    client = make_client(handler)
    results = await client.search_episodes("career", user_id="u1", min_significance=0.3)
    assert results[0].score == 0.95


@pytest.mark.asyncio
async def test_get_recent_episodes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/episodes/recent"
        return httpx.Response(200, json=make_envelope(
            [fake_episode("a"), fake_episode("b")], count=2,
        ))

    client = make_client(handler)
    eps = await client.get_recent_episodes("u1", limit=5)
    assert len(eps) == 2


# ---- arcs / synthesis ----

def fake_arc(id: str = "arc1", **overrides) -> dict:
    base = {
        "id": id, "user_id": "u1", "agent_id": None,
        "title": "T", "summary": "S", "status": "active",
        "key_episode_ids": [], "emotional_trajectory": "",
        "created_at": "2026-05-03T19:33:40.210487+00:00",
        "updated_at": "2026-05-03T19:33:40.210487+00:00",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_synthesize_narratives_sync():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope([fake_arc("arc-new")]))

    client = make_client(handler)
    result = await client.synthesize_narratives(user_id="u1", mode="sync")
    assert isinstance(result, list)
    assert result[0].id == "arc-new"


@pytest.mark.asyncio
async def test_synthesize_narratives_async():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json=make_envelope(
            {"job_id": "j-syn", "status": "pending"},
        ))

    client = make_client(handler)
    result = await client.synthesize_narratives(user_id="u1")
    from palace_client import JobPending
    assert isinstance(result, JobPending)


@pytest.mark.asyncio
async def test_get_active_arcs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/arcs/active"
        return httpx.Response(200, json=make_envelope([fake_arc("a1")]))

    client = make_client(handler)
    arcs = await client.get_active_arcs("u1", limit=10)
    assert len(arcs) == 1
    assert arcs[0].id == "a1"


# ---- jobs ----

@pytest.mark.asyncio
async def test_get_job():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_envelope({
            "id": "j-1", "kind": "reflection", "user_id": "u1",
            "status": "completed",
            "created_at": "2026-05-03T19:33:40.210487+00:00",
            "completed_at": "2026-05-03T19:34:00.000000+00:00",
            "result": [{"x": 1}], "error": None,
        }))

    client = make_client(handler)
    job = await client.get_job("j-1")
    assert job.status == "completed"
    assert job.result == [{"x": 1}]


@pytest.mark.asyncio
async def test_get_job_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Job not found"})

    from palace_client import PalaceNotFound
    client = make_client(handler)
    with pytest.raises(PalaceNotFound):
        await client.get_job("missing")


# ---- dynamics (slice 3) ----

def fake_dynamics(memory_id: str = "m1", **overrides) -> dict:
    base = {
        "memory_id": memory_id,
        "user_id": "u1",
        "stability": 2.3065,
        "difficulty": 2.118,
        "retrieval_strength": 1.0,
        "storage_strength": 0.5,
        "is_key": False,
        "importance_weight": 1.0,
        "category": None,
        "tags": None,
        "last_accessed_at": "2026-05-03T19:33:40.210487+00:00",
        "access_count": 1,
        "created_at": "2026-05-03T19:33:40.210487+00:00",
        "updated_at": "2026-05-03T19:33:40.210487+00:00",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_promote_memory():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(fake_dynamics(access_count=2)))

    client = make_client(handler)
    from palace_client import MemoryDynamics
    dyn = await client.promote_memory("m1", user_id="u1", grade=3)
    assert "/v1/memories/m1/promote" in captured["url"]
    assert captured["body"] == {
        "user_id": "u1", "grade": 3, "signal_type": "used_in_response",
    }
    assert isinstance(dyn, MemoryDynamics)
    assert dyn.memory_id == "m1"
    assert dyn.access_count == 2


@pytest.mark.asyncio
async def test_demote_memory():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope(fake_dynamics()))

    client = make_client(handler)
    dyn = await client.demote_memory("m1", user_id="u1", reason="user_correction")
    assert "/v1/memories/m1/demote" in captured["url"]
    assert captured["body"] == {"user_id": "u1", "reason": "user_correction"}
    assert dyn.memory_id == "m1"


@pytest.mark.asyncio
async def test_get_dynamics():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=make_envelope(fake_dynamics()))

    client = make_client(handler)
    dyn = await client.get_dynamics("m1", user_id="u1")
    assert "/v1/memories/m1/dynamics" in captured["url"]
    assert captured["params"] == {"user_id": "u1"}
    assert dyn.user_id == "u1"


@pytest.mark.asyncio
async def test_get_dynamics_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Dynamics not found"})

    from palace_client import PalaceNotFound
    client = make_client(handler)
    with pytest.raises(PalaceNotFound):
        await client.get_dynamics("missing", user_id="u1")


@pytest.mark.asyncio
async def test_score_memory():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_envelope({
            "composite_score": 0.79,
            "fsrs_score": 0.65,
            "retrievability": 0.82,
            "storage_strength": 0.5,
        }))

    client = make_client(handler)
    from palace_client import ScoreBreakdown
    breakdown = await client.score_memory("m1", user_id="u1", semantic_score=0.87)
    assert "/v1/memories/m1/score" in captured["url"]
    assert captured["body"] == {"user_id": "u1", "semantic_score": 0.87}
    assert isinstance(breakdown, ScoreBreakdown)
    assert breakdown.composite_score == pytest.approx(0.79)


@pytest.mark.asyncio
async def test_prune_access_logs():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=make_envelope({"deleted": 5}, count=5))

    client = make_client(handler)
    deleted = await client.prune_access_logs(retention_days=30)
    assert "/v1/maintenance/prune-access-logs" in captured["url"]
    assert captured["params"] == {"retention_days": "30"}
    assert deleted == 5
