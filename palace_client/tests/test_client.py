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
