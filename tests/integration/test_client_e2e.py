"""End-to-end: palace_client against a live Palace ASGI app.
Verifies the client and server agree on the wire contract."""

import pytest
import pytest_asyncio

from palace_client import PalaceClient

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(palace_app):
    """A PalaceClient pointed at the in-process Palace ASGI app."""
    import httpx
    transport = httpx.ASGITransport(app=palace_app)
    httpx_client = httpx.AsyncClient(
        transport=transport, base_url="http://palace.test",
    )
    pc = PalaceClient(base_url="http://palace.test", client=httpx_client)
    yield pc
    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_client_full_memory_lifecycle(client: PalaceClient):
    # health
    h = await client.health()
    assert h["status"] == "ok"

    # create
    mem = await client.create(
        user_id="e2e-1", content="hello", memory_type="preference",
        metadata={"k": "v"},
    )
    assert mem.metadata == {"k": "v"}

    # get
    fetched = await client.get(mem.id)
    assert fetched.id == mem.id

    # update
    updated = await client.update(mem.id, importance=5.0)
    assert updated.importance == 5.0

    # search
    results = await client.search("hi", user_id="e2e-1")
    assert len(results) >= 1

    # delete
    await client.delete(mem.id)

    # get after delete → PalaceNotFound
    from palace_client import PalaceNotFound
    with pytest.raises(PalaceNotFound):
        await client.get(mem.id)


@pytest.mark.asyncio
async def test_client_batch_and_list(client: PalaceClient):
    mems = await client.add(
        messages=[
            {"role": "user", "content": "I love dark mode"},
            {"role": "assistant", "content": "Got it"},
        ],
        user_id="e2e-2",
        agent_id="clara",
        metadata={"session_id": "ss-1"},
    )
    assert len(mems) == 2
    assert mems[0].metadata["session_id"] == "ss-1"
    assert mems[0].metadata["role"] == "user"

    listed = await client.get_all(user_id="e2e-2", metadata={"session_id": "ss-1"})
    assert len(listed) == 2


@pytest.mark.asyncio
async def test_client_delete_all(client: PalaceClient):
    for c in ["a", "b", "c"]:
        await client.create(user_id="e2e-3", content=c)

    deleted = await client.delete_all("e2e-3")
    assert deleted == 3

    remaining = await client.list_for_user("e2e-3")
    assert remaining == []


@pytest.mark.asyncio
async def test_client_session_and_context(client: PalaceClient):
    s = await client.create_session("e2e-4", title="X")
    assert s.title == "X"

    msg = await client.add_message(s.id, user_id="e2e-4", role="user", content="hi")
    assert msg.content == "hi"

    fetched = await client.get_session(s.id)
    assert len(fetched.messages) == 1

    await client.create(user_id="e2e-4", content="User uses Vim")
    ctx = await client.assemble_context(
        user_id="e2e-4", query="editor", session_id=s.id,
    )
    assert len(ctx.memories) >= 1
    assert len(ctx.recent_messages) == 1

    await client.delete_session(s.id)
