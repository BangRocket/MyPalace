# Palace Phase 2 — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship slice 1 of phase 2: three new memory endpoints, a `palace_client` async Python subpackage, opt-in TestContainers integration tests, and a reference router for mypalclara — enabling per-method drop-in delegation between embedded ClaraMemory and remote Palace.

**Architecture:** Five-commit slice on the `phase-2` branch. Each commit is independently reviewable; checkpoints between them. JSONB column promotion enables metadata-filter queries; the new endpoints mirror `ClaraMemory.add/get_all/delete_all` semantics. The client is async-first and depends only on `httpx` + `pydantic`. Integration tests are opt-in via pytest marker.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy 2.0 (async, asyncpg), Qdrant async client, httpx, pydantic v2, pytest, pytest-asyncio, testcontainers-python.

**Spec:** `docs/superpowers/specs/2026-05-03-palace-phase-2-design.md` (commits `2b5deff` + `17b58f3` on this branch).

**Repo root:** `/Volumes/Storage/Code/Palace`

---

## File map

### Created

| File | Responsibility |
|------|---------------|
| `palace_client/pyproject.toml` | Package metadata for the client subpackage |
| `palace_client/palace_client/__init__.py` | Re-exports `PalaceClient`, models, exceptions |
| `palace_client/palace_client/client.py` | The `PalaceClient` async class |
| `palace_client/palace_client/exceptions.py` | `PalaceError`, `PalaceNotFound`, `PalaceTransport` |
| `palace_client/palace_client/models.py` | Pydantic wire-type models |
| `palace_client/tests/__init__.py` | Empty marker |
| `palace_client/tests/test_client.py` | MockTransport unit tests for every client method |
| `examples/__init__.py` | Empty marker |
| `examples/mypalclara_router.py` | Explicit pass-through router reference |
| `tests/integration/__init__.py` | Empty marker |
| `tests/integration/conftest.py` | TestContainers fixtures for postgres + qdrant + Palace app |
| `tests/integration/test_memories_live.py` | End-to-end memory CRUD/search/list/delete-all against real backends |
| `tests/integration/test_sessions_live.py` | End-to-end session/message lifecycle |
| `tests/integration/test_client_e2e.py` | `palace_client` against a running Palace |

### Modified

| File | Change |
|------|--------|
| `palace/models.py` | `Memory.metadata_json` → JSONB column typed as `dict | None` |
| `palace/memory_service.py` | Drop `json.dumps()` calls; add `create_batch`, `list_filtered`, `delete_for_user` |
| `palace/api/common.py` | Drop `json.loads()` in `MemoryOut.from_memory`; add `BatchCreateMemoriesRequest`, `ListMemoriesRequest`, `BatchMessage` |
| `palace/api/memories.py` | Add `POST /v1/memories/batch`, `POST /v1/memories/list` routes; add `users_router` `DELETE /{user_id}/memories` route |
| `pyproject.toml` | Add `testcontainers` dev dep; add `[tool.pytest.ini_options].markers` registration |
| `README.md` | New "Drop-in mode for mypalclara" and "Integration tests" sections |

---

## Commit roadmap

1. **Commit 1 — Models migration to JSONB** (1 task)
2. **Commit 2 — Three new endpoints** (3 tasks)
3. **Commit 3 — `palace_client` package** (4 tasks)
4. **Commit 4 — Integration tests** (3 tasks)
5. **Commit 5 — Examples + README** (2 tasks)

Review checkpoints between commits.

---

# COMMIT 1 — Models migration to JSONB

## Task 1: Promote `Memory.metadata_json` to JSONB

**Files:**
- Modify: `palace/models.py`
- Modify: `palace/memory_service.py:42` (drop `json.dumps`), `palace/memory_service.py:101-102` (drop `json.dumps`)
- Modify: `palace/api/common.py:5` (drop unused `json` import after edit), `palace/api/common.py:102` (drop `json.loads`)
- Test: `tests/test_memories.py` (add round-trip test)

- [ ] **Step 1.1: Write the failing test**

Add this test to `tests/test_memories.py` at the end of the file:

```python
def test_create_memory_with_dict_metadata(client, mock_memory_service):
    """Slice-1 contract: metadata is a dict on the wire AND in the model.
    No more json.loads at the API boundary."""
    memory_with_meta = FakeMemory(
        id="mem-meta-1",
        user_id="user-1",
        agent_id=None,
        content="With metadata",
        memory_type="preference",
        source=None,
        importance=1.0,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
        accessed_at=None,
        access_count=0,
        metadata_json={"category": "ui", "confidence": 0.9},
    )
    mock_memory_service.create.return_value = memory_with_meta

    resp = client.post("/v1/memories", json={
        "user_id": "user-1",
        "content": "With metadata",
        "metadata": {"category": "ui", "confidence": 0.9},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["metadata"] == {"category": "ui", "confidence": 0.9}
```

- [ ] **Step 1.2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_memories.py::test_create_memory_with_dict_metadata -v`

Expected: FAIL with `TypeError: the JSON object must be str, bytes or bytearray, not dict` (because `MemoryOut.from_memory` calls `json.loads` on a dict).

- [ ] **Step 1.3: Update `palace/models.py` to use JSONB**

Replace the `Memory` class in `palace/models.py` (the `__tablename__ = "memories"` block) with:

```python
class Memory(SQLModel, table=True):
    """A stored memory — fact, preference, episode, etc."""

    __tablename__ = "memories"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    content: str
    memory_type: str = Field(default="semantic", index=True)
    source: str | None = None
    importance: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    accessed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    access_count: int = Field(default=0)
    metadata_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
```

And add the `JSONB` import at the top of `palace/models.py`. The full top-of-file imports should become:

```python
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel
```

- [ ] **Step 1.4: Update `palace/memory_service.py` to pass dict directly**

In `palace/memory_service.py`, in the `create` method (around line 35-46), replace:

```python
            memory = Memory(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=importance,
                metadata_json=json.dumps(metadata) if metadata else None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
```

with:

```python
            memory = Memory(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=importance,
                metadata_json=metadata,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
```

In the same file's `update` method (around line 101-102), replace:

```python
            if metadata is not None:
                memory.metadata_json = json.dumps(metadata)
```

with:

```python
            if metadata is not None:
                memory.metadata_json = metadata
```

Then remove the now-unused `import json` line at the top of the file.

- [ ] **Step 1.5: Update `palace/api/common.py` to drop `json.loads`**

In `palace/api/common.py`, replace this line in `MemoryOut.from_memory`:

```python
            metadata=json.loads(m.metadata_json) if m.metadata_json else None,
```

with:

```python
            metadata=m.metadata_json,
```

Then remove the `import json` line at the top of the file (it becomes unused).

- [ ] **Step 1.6: Run the new test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_memories.py::test_create_memory_with_dict_metadata -v`

Expected: PASS.

- [ ] **Step 1.7: Run the full test suite to confirm no regressions**

Run: `.venv/bin/python -m pytest`

Expected: All 15 tests PASS (14 prior + 1 new).

- [ ] **Step 1.8: Run lint**

Run: `.venv/bin/ruff check palace tests`

Expected: `All checks passed!`

If lint fails, fix the reported issues and re-run.

- [ ] **Step 1.9: Commit**

```bash
git add palace/models.py palace/memory_service.py palace/api/common.py tests/test_memories.py
git commit -m "$(cat <<'EOF'
feat(models): promote Memory.metadata_json to JSONB

Switch Memory.metadata_json from String to JSONB and pass dicts
directly through the service + API layer (no more json.dumps/loads
at the boundary). Enables JSONB containment queries for the
upcoming /v1/memories/list endpoint (slice 1, commit 2).

DESTRUCTIVE: this changes the schema. Any existing Palace database
must be dropped and recreated. No Alembic in slice 1 by design
(spec D8); migrations land in a later phase when schema changes
start mattering. Phase-1 deployments have no live data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## ✋ CHECKPOINT 1 — Review commit 1 before continuing

Stop here. Before starting commit 2:

- Verify `git log --oneline -1` shows the new commit on `phase-2`.
- Re-read the diff: `git show HEAD`.
- Confirm `pytest` is fully green and `ruff check` is clean.
- If review feedback requires changes, amend or follow-up commit, then continue.

---

# COMMIT 2 — Three new endpoints

## Task 2: `POST /v1/memories/batch` — batch create from messages

**Files:**
- Modify: `palace/api/common.py` (add `BatchMessage`, `BatchCreateMemoriesRequest`)
- Modify: `palace/memory_service.py` (add `create_batch` method)
- Modify: `palace/api/memories.py` (add `POST /batch` route)
- Test: `tests/test_memories.py` (add 3 tests)

- [ ] **Step 2.1: Write the failing tests**

Add these tests at the end of `tests/test_memories.py`:

```python
def test_batch_create_memories(client, mock_memory_service):
    """One memory per input message, role merged into per-memory metadata."""
    m1 = FakeMemory(
        id="m-batch-1", user_id="u1", agent_id="clara",
        content="I love dark mode", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user", "session_id": "s1"},
    )
    m2 = FakeMemory(
        id="m-batch-2", user_id="u1", agent_id="clara",
        content="Got it", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "assistant", "session_id": "s1"},
    )
    mock_memory_service.create_batch = AsyncMock(return_value=[m1, m2])

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "agent_id": "clara",
        "messages": [
            {"role": "user", "content": "I love dark mode"},
            {"role": "assistant", "content": "Got it"},
        ],
        "memory_type": "episodic",
        "metadata": {"session_id": "s1"},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    assert data[0]["content"] == "I love dark mode"
    assert data[0]["metadata"] == {"role": "user", "session_id": "s1"}
    assert data[1]["metadata"] == {"role": "assistant", "session_id": "s1"}


def test_batch_create_per_message_keys_win(client, mock_memory_service):
    """Per-message metadata keys override request-level metadata on collision."""
    m = FakeMemory(
        id="m-batch-3", user_id="u1", agent_id=None,
        content="hi", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user", "session_id": "from_message"},
    )
    mock_memory_service.create_batch = AsyncMock(return_value=[m])

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "messages": [{"role": "user", "content": "hi", "session_id": "from_message"}],
        "metadata": {"session_id": "from_request"},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["metadata"]["session_id"] == "from_message"


def test_batch_create_infer_ignored_in_slice_1(client, mock_memory_service):
    """infer=True is accepted but doesn't change behavior in slice 1 (D7)."""
    m = FakeMemory(
        id="m-batch-4", user_id="u1", agent_id=None,
        content="hi", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user"},
    )
    mock_memory_service.create_batch = AsyncMock(return_value=[m])

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "messages": [{"role": "user", "content": "hi"}],
        "infer": True,
    })

    assert resp.status_code == 200
    # Verify the service was called with infer=True (forwarded but ignored impl-side)
    kwargs = mock_memory_service.create_batch.call_args.kwargs
    assert kwargs.get("infer") is True
```

Note: these tests use `AsyncMock` which is already imported at the top of `tests/test_memories.py` (via `from unittest.mock import patch` — you may need to add `AsyncMock`). If `AsyncMock` is not imported at the top of the file, add it: change `from unittest.mock import patch` to `from unittest.mock import AsyncMock, patch` (or simply `from unittest.mock import AsyncMock`).

- [ ] **Step 2.2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "batch"`

Expected: All three new tests FAIL with 404 (route doesn't exist).

- [ ] **Step 2.3: Add request models in `palace/api/common.py`**

Add these classes after the existing `class CreateMemoryRequest` block (around line 25):

```python
class BatchMessage(BaseModel):
    """A single message in a batch-create request. Extra keys allowed and
    flow through into per-memory metadata (per-message keys win over request
    metadata on collision)."""
    model_config = {"extra": "allow"}
    role: str
    content: str


class BatchCreateMemoriesRequest(BaseModel):
    user_id: str
    messages: list[BatchMessage]
    agent_id: str | None = None
    memory_type: str = "episodic"
    metadata: dict[str, Any] | None = None
    source: str | None = None
    infer: bool = False  # accepted but ignored in slice 1 (spec D7)
```

- [ ] **Step 2.4: Add `create_batch` to `palace/memory_service.py`**

Add this method to the `MemoryService` class, after the existing `create` method:

```python
    async def create_batch(
        self,
        user_id: str,
        messages: list[dict],
        agent_id: str | None = None,
        memory_type: str = "episodic",
        metadata: dict | None = None,
        source: str | None = None,
        infer: bool = False,  # accepted but ignored in slice 1
    ) -> list[Memory]:
        """One memory per message. Per-message keys (other than 'content')
        merge into metadata, with per-message keys winning over request-level
        metadata on key collision."""
        base_metadata = metadata or {}
        results: list[Memory] = []
        for msg in messages:
            content = msg["content"]
            extra = {k: v for k, v in msg.items() if k != "content"}
            merged = {**base_metadata, **extra}
            mem = await self.create(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=1.0,
                metadata=merged or None,
            )
            results.append(mem)
        return results
```

- [ ] **Step 2.5: Add the route in `palace/api/memories.py`**

At the top of `palace/api/memories.py`, extend the import from `palace.api.common` to include the new request model:

```python
from palace.api.common import (
    ApiResponse,
    BatchCreateMemoriesRequest,
    CreateMemoryRequest,
    MemoryOut,
    Meta,
    SearchedMemoryOut,
    SearchMemoriesRequest,
    UpdateMemoryRequest,
)
```

Then add this route after the existing `create_memory` route (after the `@router.post("")` block):

```python
@router.post("/batch", response_model=ApiResponse[list[MemoryOut]])
async def batch_create_memories(req: BatchCreateMemoriesRequest):
    start = time.time()
    messages = [m.model_dump() for m in req.messages]
    memories = await memory_service.create_batch(
        user_id=req.user_id,
        messages=messages,
        agent_id=req.agent_id,
        memory_type=req.memory_type,
        metadata=req.metadata,
        source=req.source,
        infer=req.infer,
    )
    took = int((time.time() - start) * 1000)
    data = [MemoryOut.from_memory(m) for m in memories]
    return ApiResponse(data=data, meta=Meta(count=len(data), took_ms=took))
```

- [ ] **Step 2.6: Update conftest mock to include `create_batch`**

In `tests/conftest.py`, in `mock_memory_service` fixture, add this line alongside the other `AsyncMock()` setups:

```python
    mock.create_batch = AsyncMock()
```

- [ ] **Step 2.7: Run batch tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "batch"`

Expected: All three batch tests PASS.

---

## Task 3: `POST /v1/memories/list` — list with rich filters

**Files:**
- Modify: `palace/api/common.py` (add `ListMemoriesRequest`)
- Modify: `palace/memory_service.py` (add `list_filtered` method)
- Modify: `palace/api/memories.py` (add `POST /list` route)
- Test: `tests/test_memories.py` (add 3 tests)

- [ ] **Step 3.1: Write the failing tests**

Add to `tests/test_memories.py`:

```python
def test_list_memories_no_filters(client, mock_memory_service):
    m = FakeMemory(
        id="m-list-1", user_id="u1", agent_id=None,
        content="x", memory_type="semantic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0, metadata_json=None,
    )
    mock_memory_service.list_filtered = AsyncMock(return_value=[m])

    resp = client.post("/v1/memories/list", json={})

    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1
    # Defaults: limit=50, offset=0, all filters None
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs == {
        "user_id": None, "agent_id": None, "run_id": None,
        "memory_type": None, "metadata": None,
        "limit": 50, "offset": 0,
    }


def test_list_memories_with_filters(client, mock_memory_service):
    mock_memory_service.list_filtered = AsyncMock(return_value=[])

    resp = client.post("/v1/memories/list", json={
        "user_id": "u1",
        "agent_id": "clara",
        "run_id": "session-123",
        "memory_type": "preference",
        "metadata": {"category": "ui"},
        "limit": 25,
        "offset": 100,
    })

    assert resp.status_code == 200
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs["user_id"] == "u1"
    assert kwargs["agent_id"] == "clara"
    assert kwargs["run_id"] == "session-123"
    assert kwargs["memory_type"] == "preference"
    assert kwargs["metadata"] == {"category": "ui"}
    assert kwargs["limit"] == 25
    assert kwargs["offset"] == 100


def test_list_memories_clamps_limit(client, mock_memory_service):
    """limit > 500 is server-clamped to 500."""
    mock_memory_service.list_filtered = AsyncMock(return_value=[])

    resp = client.post("/v1/memories/list", json={"limit": 9999})

    assert resp.status_code == 200
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs["limit"] == 500
```

- [ ] **Step 3.2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "list_memories"`

Expected: All three tests FAIL with 404.

- [ ] **Step 3.3: Add `ListMemoriesRequest` in `palace/api/common.py`**

Add after the `BatchCreateMemoriesRequest` class:

```python
class ListMemoriesRequest(BaseModel):
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    memory_type: str | None = None
    metadata: dict[str, Any] | None = None
    limit: int = 50
    offset: int = 0
```

- [ ] **Step 3.4: Add `list_filtered` to `palace/memory_service.py`**

Add this method to `MemoryService`, after the existing `list_for_user` method. Note the imports needed at the top of the file: `from sqlalchemy import and_, desc, select`. The current file already imports `desc, select`; add `and_` to that import.

Then add the method:

```python
    async def list_filtered(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        metadata: dict | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        """List memories with filters. Metadata matching uses JSONB
        containment (`@>`)."""
        clauses = []
        if user_id is not None:
            clauses.append(Memory.user_id == user_id)
        if agent_id is not None:
            clauses.append(Memory.agent_id == agent_id)
        if memory_type is not None:
            clauses.append(Memory.memory_type == memory_type)
        if run_id is not None:
            clauses.append(Memory.metadata_json.op("@>")({"run_id": run_id}))
        if metadata:
            clauses.append(Memory.metadata_json.op("@>")(metadata))

        stmt = (
            select(Memory)
            .where(and_(*clauses)) if clauses else select(Memory)
        )
        stmt = stmt.order_by(desc(Memory.created_at)).limit(limit).offset(offset)

        async with async_session() as db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
```

- [ ] **Step 3.5: Add the route + clamp logic in `palace/api/memories.py`**

Extend the imports at the top:

```python
from palace.api.common import (
    ApiResponse,
    BatchCreateMemoriesRequest,
    CreateMemoryRequest,
    ListMemoriesRequest,
    MemoryOut,
    Meta,
    SearchedMemoryOut,
    SearchMemoriesRequest,
    UpdateMemoryRequest,
)
```

Add the route after the batch route:

```python
MAX_LIST_LIMIT = 500


@router.post("/list", response_model=ApiResponse[list[MemoryOut]])
async def list_memories(req: ListMemoriesRequest):
    start = time.time()
    limit = min(req.limit, MAX_LIST_LIMIT)
    memories = await memory_service.list_filtered(
        user_id=req.user_id,
        agent_id=req.agent_id,
        run_id=req.run_id,
        memory_type=req.memory_type,
        metadata=req.metadata,
        limit=limit,
        offset=req.offset,
    )
    took = int((time.time() - start) * 1000)
    data = [MemoryOut.from_memory(m) for m in memories]
    return ApiResponse(data=data, meta=Meta(count=len(data), took_ms=took))
```

- [ ] **Step 3.6: Update conftest mock to include `list_filtered`**

In `tests/conftest.py`, add to `mock_memory_service`:

```python
    mock.list_filtered = AsyncMock(return_value=[])
```

- [ ] **Step 3.7: Run list tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "list_memories"`

Expected: All three tests PASS.

---

## Task 4: `DELETE /v1/users/{user_id}/memories` — purge by user

**Files:**
- Modify: `palace/memory_service.py` (add `delete_for_user` method)
- Modify: `palace/api/memories.py` (add route on `users_router`)
- Test: `tests/test_memories.py` (add 2 tests)

- [ ] **Step 4.1: Write the failing tests**

Add to `tests/test_memories.py`:

```python
def test_delete_user_memories_no_filters(client, mock_memory_service):
    mock_memory_service.delete_for_user = AsyncMock(return_value=12)

    resp = client.delete("/v1/users/u1/memories")

    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": 12}
    kwargs = mock_memory_service.delete_for_user.call_args.kwargs
    assert kwargs["user_id"] == "u1"
    assert kwargs["agent_id"] is None
    assert kwargs["run_id"] is None


def test_delete_user_memories_with_filters(client, mock_memory_service):
    mock_memory_service.delete_for_user = AsyncMock(return_value=0)

    resp = client.delete("/v1/users/u1/memories?agent_id=clara&run_id=s-123")

    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": 0}
    kwargs = mock_memory_service.delete_for_user.call_args.kwargs
    assert kwargs["agent_id"] == "clara"
    assert kwargs["run_id"] == "s-123"
```

- [ ] **Step 4.2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "delete_user"`

Expected: Both FAIL with 404 or 405.

- [ ] **Step 4.3: Add `delete_for_user` to `palace/memory_service.py`**

Add this method to `MemoryService`, after `delete`:

```python
    async def delete_for_user(
        self,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Delete all memories for a user (optionally filtered by agent/run).
        Removes from postgres AND from Qdrant. Returns count deleted."""
        clauses = [Memory.user_id == user_id]
        if agent_id is not None:
            clauses.append(Memory.agent_id == agent_id)
        if run_id is not None:
            clauses.append(Memory.metadata_json.op("@>")({"run_id": run_id}))

        async with async_session() as db:
            stmt = select(Memory).where(and_(*clauses))
            result = await db.execute(stmt)
            memories = list(result.scalars().all())
            ids = [m.id for m in memories]
            for m in memories:
                await db.delete(m)
            await db.commit()

        # Remove vectors in batches of 500
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for mid in chunk:
                await vector_store.delete(mid)
        return len(ids)
```

(Note: `vector_store.delete` already takes a single id at a time. A future optimization could batch the Qdrant delete calls; out of scope for slice 1.)

- [ ] **Step 4.4: Add the route on `users_router` in `palace/api/memories.py`**

Add this route after the existing `list_user_memories` route on `users_router`:

```python
@users_router.delete("/{user_id}/memories", response_model=ApiResponse[dict])
async def delete_user_memories(
    user_id: str,
    agent_id: str | None = None,
    run_id: str | None = None,
):
    start = time.time()
    deleted = await memory_service.delete_for_user(
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data={"deleted": deleted},
        meta=Meta(count=deleted, took_ms=took),
    )
```

- [ ] **Step 4.5: Update conftest mock**

In `tests/conftest.py`, add to `mock_memory_service`:

```python
    mock.delete_for_user = AsyncMock(return_value=0)
```

- [ ] **Step 4.6: Run delete tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_memories.py -v -k "delete_user"`

Expected: Both PASS.

- [ ] **Step 4.7: Run full suite + lint**

Run: `.venv/bin/python -m pytest && .venv/bin/ruff check palace tests`

Expected: All tests PASS (15 + 8 new = 23). Lint clean.

- [ ] **Step 4.8: Commit**

```bash
git add palace/api/common.py palace/api/memories.py palace/memory_service.py tests/test_memories.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(api): batch create, filtered list, delete-by-user endpoints

Three new endpoints completing the slice-1 wire contract for the
ClaraMemory.add/get_all/delete_all surface:

- POST /v1/memories/batch — N messages → N memories. Per-message keys
  merge into metadata, winning over request-level metadata on collision.
  infer flag accepted but ignored (forward-compat per spec D7).
- POST /v1/memories/list — JSONB-containment filters on user_id,
  agent_id, run_id, memory_type, and arbitrary metadata. Limit
  server-clamped to 500.
- DELETE /v1/users/{user_id}/memories — purge by user with optional
  agent_id/run_id query filters. Returns count deleted (0 is success,
  not 404). Removes from both postgres and Qdrant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## ✋ CHECKPOINT 2 — Review commit 2 before continuing

Stop. Verify:
- `git log --oneline -2` shows the new commit.
- `pytest` is green; `ruff check` is clean.
- All three endpoints are registered (you can verify with `python -c "from palace.main import app; print([r.path for r in app.routes if hasattr(r,'path')])"` — should include `/v1/memories/batch`, `/v1/memories/list`, and a DELETE on `/v1/users/{user_id}/memories`).
- Address any review feedback before continuing.

---

# COMMIT 3 — `palace_client` package

## Task 5: Set up `palace_client` package skeleton, exceptions, and wire models

**Files:**
- Create: `palace_client/pyproject.toml`
- Create: `palace_client/palace_client/__init__.py`
- Create: `palace_client/palace_client/exceptions.py`
- Create: `palace_client/palace_client/models.py`
- Create: `palace_client/tests/__init__.py`
- Create: `palace_client/tests/test_models.py`

- [ ] **Step 5.1: Create `palace_client/pyproject.toml`**

```toml
[project]
name = "palace-client"
version = "0.1.0"
description = "Async Python client for the Palace Memory Service"
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.28",
    "pydantic>=2.10",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 5.2: Create `palace_client/palace_client/exceptions.py`**

```python
"""Exception hierarchy for the Palace client."""

from typing import Any


class PalaceError(Exception):
    """Base error. Raised on any non-2xx HTTP response other than 404."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, message={self.message!r})"


class PalaceNotFound(PalaceError):
    """Raised on HTTP 404."""


class PalaceTransport(PalaceError):
    """Raised on network/timeout errors (no HTTP status reached)."""
```

- [ ] **Step 5.3: Create `palace_client/palace_client/models.py`**

```python
"""Pydantic wire types — mirror Palace's response shapes 1:1."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Memory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    memory_type: str
    source: str | None = None
    importance: float
    created_at: datetime | None = None
    updated_at: datetime | None = None
    accessed_at: datetime | None = None
    access_count: int = 0
    metadata: dict[str, Any] | None = None


class ScoredMemory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    content: str
    memory_type: str
    importance: float
    score: float
    created_at: datetime | None = None


class Session(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    title: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    role: str
    content: str
    created_at: datetime | None = None


class SessionWithMessages(Session):
    messages: list[Message] = Field(default_factory=list)


class Context(BaseModel):
    model_config = ConfigDict(extra="ignore")
    memories: list[dict[str, Any]] = Field(default_factory=list)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
```

- [ ] **Step 5.4: Create `palace_client/palace_client/__init__.py`**

```python
"""Palace Memory Service async client."""

from palace_client.client import PalaceClient
from palace_client.exceptions import PalaceError, PalaceNotFound, PalaceTransport
from palace_client.models import (
    Context,
    Memory,
    Message,
    ScoredMemory,
    Session,
    SessionWithMessages,
)

__all__ = [
    "PalaceClient",
    "PalaceError",
    "PalaceNotFound",
    "PalaceTransport",
    "Memory",
    "ScoredMemory",
    "Session",
    "Message",
    "SessionWithMessages",
    "Context",
]
```

- [ ] **Step 5.5: Create `palace_client/tests/__init__.py`** (empty file)

- [ ] **Step 5.6: Create `palace_client/tests/test_models.py`**

```python
"""Wire-model parsing smoke test — ensures datetimes are tz-aware."""

from datetime import datetime

from palace_client.models import Memory, ScoredMemory


def test_memory_parses_iso_datetime():
    m = Memory.model_validate({
        "id": "m1",
        "user_id": "u1",
        "content": "x",
        "memory_type": "semantic",
        "importance": 1.0,
        "created_at": "2026-05-03T19:33:40.210487+00:00",
        "metadata": {"k": "v"},
    })
    assert isinstance(m.created_at, datetime)
    assert m.created_at.tzinfo is not None
    assert m.metadata == {"k": "v"}


def test_scored_memory_minimal():
    s = ScoredMemory.model_validate({
        "id": "m1",
        "content": "x",
        "memory_type": "semantic",
        "importance": 1.0,
        "score": 0.95,
    })
    assert s.score == 0.95
```

- [ ] **Step 5.7: Verify the package layout is importable**

Install in editable mode for local testing:

```bash
.venv/bin/python -m pip install -e ./palace_client
```

Then run the model tests:

```bash
cd palace_client && ../.venv/bin/python -m pytest -v && cd ..
```

Expected: 2 tests PASS.

---

## Task 6: Implement `PalaceClient` memory methods + tests

**Files:**
- Create: `palace_client/palace_client/client.py`
- Create: `palace_client/tests/test_client.py`

- [ ] **Step 6.1: Write the failing tests for memory methods**

Create `palace_client/tests/test_client.py`:

```python
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
```

- [ ] **Step 6.2: Run the tests to verify they fail**

Run: `cd palace_client && ../.venv/bin/python -m pytest -v && cd ..`

Expected: All `test_client.py` tests FAIL with `ImportError` (PalaceClient doesn't exist) or `ModuleNotFoundError`.

- [ ] **Step 6.3: Create `palace_client/palace_client/client.py`**

```python
"""PalaceClient — async HTTP client for the Palace Memory Service."""

from typing import Any

import httpx

from palace_client.exceptions import PalaceError, PalaceNotFound, PalaceTransport
from palace_client.models import (
    Context,
    Memory,
    Message,
    ScoredMemory,
    Session,
    SessionWithMessages,
)


class PalaceClient:
    """Async client for Palace. Use as an async context manager or call
    `aclose()` explicitly."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=timeout, headers=headers,
            )
            self._owns_client = True

    async def __aenter__(self) -> "PalaceClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- HTTP helpers ----

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        try:
            resp = await self._client.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise PalaceTransport(str(e)) from e

        if resp.status_code == 404:
            payload = self._safe_json(resp)
            raise PalaceNotFound(
                self._error_message(payload, "Not found"),
                status_code=404, payload=payload,
            )
        if resp.status_code >= 400:
            payload = self._safe_json(resp)
            raise PalaceError(
                self._error_message(payload, f"HTTP {resp.status_code}"),
                status_code=resp.status_code, payload=payload,
            )
        return self._safe_json(resp)

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict:
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _error_message(payload: dict, fallback: str) -> str:
        if isinstance(payload, dict):
            return str(payload.get("detail") or payload.get("message") or fallback)
        return fallback

    @staticmethod
    def _data(envelope: dict) -> Any:
        return envelope.get("data")

    # ---- memories ----

    async def add(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        memory_type: str = "episodic",
        metadata: dict | None = None,
        source: str | None = None,
        infer: bool = False,
    ) -> list[Memory]:
        body = {
            "user_id": user_id,
            "messages": messages,
            "memory_type": memory_type,
            "infer": infer,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if metadata is not None:
            body["metadata"] = metadata
        if source is not None:
            body["source"] = source
        envelope = await self._request("POST", "/v1/memories/batch", json=body)
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
        source: str | None = None,
    ) -> Memory:
        body = {
            "user_id": user_id,
            "content": content,
            "memory_type": memory_type,
            "importance": importance,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if metadata is not None:
            body["metadata"] = metadata
        if source is not None:
            body["source"] = source
        envelope = await self._request("POST", "/v1/memories", json=body)
        return Memory.model_validate(self._data(envelope))

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[ScoredMemory]:
        body: dict[str, Any] = {"query": query, "limit": limit, "min_score": min_score}
        if user_id is not None:
            body["user_id"] = user_id
        if agent_id is not None:
            body["agent_id"] = agent_id
        if memory_type is not None:
            body["memory_type"] = memory_type
        envelope = await self._request("POST", "/v1/memories/search", json=body)
        return [ScoredMemory.model_validate(m) for m in self._data(envelope) or []]

    async def get(self, memory_id: str) -> Memory:
        envelope = await self._request("GET", f"/v1/memories/{memory_id}")
        return Memory.model_validate(self._data(envelope))

    async def update(self, memory_id: str, **fields: Any) -> Memory:
        envelope = await self._request("PATCH", f"/v1/memories/{memory_id}", json=fields)
        return Memory.model_validate(self._data(envelope))

    async def delete(self, memory_id: str) -> None:
        await self._request("DELETE", f"/v1/memories/{memory_id}")
        return None

    async def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        metadata: dict | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id is not None:
            body["user_id"] = user_id
        if agent_id is not None:
            body["agent_id"] = agent_id
        if run_id is not None:
            body["run_id"] = run_id
        if memory_type is not None:
            body["memory_type"] = memory_type
        if metadata is not None:
            body["metadata"] = metadata
        envelope = await self._request("POST", "/v1/memories/list", json=body)
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    async def delete_all(
        self,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        params: dict[str, str] = {}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if run_id is not None:
            params["run_id"] = run_id
        envelope = await self._request(
            "DELETE", f"/v1/users/{user_id}/memories", params=params,
        )
        data = self._data(envelope) or {}
        return int(data.get("deleted", 0))

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[Memory]:
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/memories", params={"limit": limit},
        )
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    # ---- sessions ----

    async def create_session(self, user_id: str, title: str | None = None) -> Session:
        body: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            body["title"] = title
        envelope = await self._request("POST", "/v1/sessions", json=body)
        return Session.model_validate(self._data(envelope))

    async def get_session(self, session_id: str) -> SessionWithMessages:
        envelope = await self._request("GET", f"/v1/sessions/{session_id}")
        return SessionWithMessages.model_validate(self._data(envelope))

    async def add_message(
        self, session_id: str, user_id: str, role: str, content: str,
    ) -> Message:
        body = {"user_id": user_id, "role": role, "content": content}
        envelope = await self._request(
            "POST", f"/v1/sessions/{session_id}/messages", json=body,
        )
        return Message.model_validate(self._data(envelope))

    async def update_session(self, session_id: str, **fields: Any) -> Session:
        envelope = await self._request(
            "PATCH", f"/v1/sessions/{session_id}", json=fields,
        )
        return Session.model_validate(self._data(envelope))

    async def delete_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/v1/sessions/{session_id}")
        return None

    # ---- context ----

    async def assemble_context(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        max_memories: int = 10,
        max_messages: int = 20,
    ) -> Context:
        body: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "max_memories": max_memories,
            "max_messages": max_messages,
        }
        if session_id is not None:
            body["session_id"] = session_id
        envelope = await self._request("POST", "/v1/context", json=body)
        return Context.model_validate(self._data(envelope))

    # ---- health ----

    async def health(self) -> dict:
        return await self._request("GET", "/health")
```

- [ ] **Step 6.4: Run all client tests**

Run: `cd palace_client && ../.venv/bin/python -m pytest -v && cd ..`

Expected: All tests in `test_client.py` AND `test_models.py` PASS (~14 tests total).

---

## Task 7: Implement and test session + context client methods

**Files:**
- Modify: `palace_client/tests/test_client.py` (add session + context tests)

The methods are already implemented in Task 6. This task adds the unit tests.

- [ ] **Step 7.1: Append session + context tests to `palace_client/tests/test_client.py`**

```python
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
```

- [ ] **Step 7.2: Run all client tests again**

Run: `cd palace_client && ../.venv/bin/python -m pytest -v && cd ..`

Expected: ~22 tests, all PASS, in under 2 seconds.

---

## Task 8: Verify the client installs cleanly via `pip install -e`

- [ ] **Step 8.1: Verify editable install works in a fresh import**

Run:

```bash
.venv/bin/python -c "from palace_client import PalaceClient, Memory, PalaceNotFound; print('client ok:', PalaceClient.__module__)"
```

Expected: `client ok: palace_client.client`

- [ ] **Step 8.2: Run the parent-repo test suite to confirm nothing regressed**

Run: `.venv/bin/python -m pytest`

Expected: All 23 tests in `palace/` PASS (the parent suite, not the client suite).

- [ ] **Step 8.3: Run lint on the client package**

Run: `.venv/bin/ruff check palace_client/palace_client palace_client/tests`

Expected: `All checks passed!` (if it complains about ruff config not finding pyproject, that's fine — the client has its own pyproject.toml).

If ruff fails, fix the issues.

- [ ] **Step 8.4: Commit**

```bash
git add palace_client/
git commit -m "$(cat <<'EOF'
feat(client): introduce palace_client async Python subpackage

A standalone installable client (httpx + pydantic only — no
sqlalchemy/qdrant/torch) that mirrors the Palace HTTP API:

- PalaceClient: async-first, supports async context manager,
  injectable httpx client for tests.
- Methods: add (batch), create, search, get, update, delete,
  get_all, delete_all, list_for_user, session CRUD,
  assemble_context, health.
- Errors: PalaceError, PalaceNotFound (404), PalaceTransport
  (network/timeout) — never silent failures.
- Wire types: Memory, ScoredMemory, Session, Message,
  SessionWithMessages, Context — Pydantic, mirror Palace 1:1.
- Tests: 22 unit tests using httpx.MockTransport, ~1s total.

Installable via `pip install -e ./palace_client` for local dev or
`pip install git+https://...#subdirectory=palace_client` from
mypalclara.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## ✋ CHECKPOINT 3 — Review commit 3 before continuing

Stop. Verify:
- `git log --oneline -3` shows three slice-1 commits.
- `cd palace_client && ../.venv/bin/python -m pytest && cd ..` is green.
- The parent `pytest` is still green.
- Address review feedback before continuing.

---

# COMMIT 4 — Integration tests

## Task 9: Add `testcontainers` dep + pytest marker registration

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 9.1: Add `testcontainers` to dev deps + register the `integration` marker**

Edit `pyproject.toml`. The `[project.optional-dependencies]` block currently has:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "pytest-httpx>=0.35",
    "httpx>=0.28",
    "ruff>=0.9",
]
```

Add `testcontainers[postgres]>=4.9` to that list, so it becomes:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "pytest-httpx>=0.35",
    "httpx>=0.28",
    "ruff>=0.9",
    "testcontainers[postgres]>=4.9",
]
```

Then update the `[tool.pytest.ini_options]` block from:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

to:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: tests that require live postgres + qdrant containers (opt-in via -m integration)",
]
```

- [ ] **Step 9.2: Install the new dep**

Run: `.venv/bin/python -m pip install -e ".[dev]"`

Expected: `testcontainers` (and `psycopg2-binary` from `[postgres]` extra) get installed.

---

## Task 10: TestContainers conftest + first integration test (memories)

**Files:**
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_memories_live.py`

- [ ] **Step 10.1: Create `tests/integration/__init__.py`** (empty file)

- [ ] **Step 10.2: Create `tests/integration/conftest.py`**

```python
"""Integration test fixtures: live postgres + qdrant via TestContainers."""

import asyncio
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.postgres import PostgresContainer


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    """Poll an HTTP URL until it returns 2xx or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 400:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Spin up postgres for the test session. Returns asyncpg URL."""
    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers gives us a sync URL; rewrite to asyncpg
        sync_url = pg.get_connection_url()
        # Format: postgresql+psycopg2://user:pass@host:port/db
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        # Some versions return postgresql:// directly
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        yield async_url


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Spin up qdrant for the test session."""
    container = DockerContainer("qdrant/qdrant:latest").with_exposed_ports(6333)
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6333)
        url = f"http://{host}:{port}"
        _wait_for_http(f"{url}/healthz")
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def palace_settings(postgres_url: str, qdrant_url: str) -> dict[str, str]:
    """Env vars Palace needs to point at the test containers.
    Use a small embedding model so test sessions stay fast."""
    return {
        "PALACE_DATABASE_URL": postgres_url,
        "QDRANT_URL": qdrant_url,
        "QDRANT_COLLECTION": f"palace_int_{uuid.uuid4().hex[:8]}",
        "EMBEDDING_PROVIDER": "huggingface",
        "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    }


@pytest_asyncio.fixture(scope="session")
async def palace_app(palace_settings: dict[str, str]):
    """Boot the Palace ASGI app pointed at the test containers.
    Yields the FastAPI app instance.

    Module reload order matters: each downstream module captures the previous
    module's symbols at import time, so we must reload outward from config
    (settings) → database/vector/memory_service (engine + singletons) →
    api routers (closed-over singletons) → main (assembles the app).
    """
    for k, v in palace_settings.items():
        os.environ[k] = v

    import importlib
    from palace import config as palace_config
    importlib.reload(palace_config)
    from palace import database, memory_service, session_service, vector
    importlib.reload(database)
    importlib.reload(vector)
    importlib.reload(memory_service)
    importlib.reload(session_service)
    from palace import context_service
    importlib.reload(context_service)
    # API router modules close over the singletons via `from ... import`
    # — reload them so routes pick up the new memory_service / vector_store.
    from palace.api import common as api_common
    importlib.reload(api_common)
    from palace.api import memories as api_memories
    from palace.api import sessions as api_sessions
    from palace.api import context as api_context
    importlib.reload(api_memories)
    importlib.reload(api_sessions)
    importlib.reload(api_context)
    from palace import main as palace_main
    importlib.reload(palace_main)

    # Run lifespan startup (creates tables + Qdrant collection)
    await palace_main.init_db()
    await palace_main.memory_service.init()
    yield palace_main.app


@pytest_asyncio.fixture
async def http_client(palace_app) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI in-process client (no real TCP) — fast and avoids port collisions."""
    transport = httpx.ASGITransport(app=palace_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://palace.test",
    ) as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(palace_app):
    """Truncate tables and clear Qdrant points between tests."""
    from palace.database import async_session
    from palace.models import Memory, Message, Session as SessionModel
    from palace.vector import vector_store
    from sqlalchemy import delete

    async with async_session() as db:
        await db.execute(delete(Message))
        await db.execute(delete(SessionModel))
        await db.execute(delete(Memory))
        await db.commit()

    # Clear all vector points by recreating the collection
    try:
        await vector_store.client.delete_collection(vector_store.collection)
    except Exception:
        pass
    from palace.memory_service import memory_service
    await memory_service.init()
    yield
```

Note on the conftest:
- The `_truncate_tables` fixture is `autouse=True` so every test starts with a clean slate.
- Module reloading is necessary because `palace.config.settings` is read at import time and bound into singletons (`memory_service`, `vector_store`, `engine`).
- The Qdrant collection name is randomized per session so parallel sessions don't collide.

- [ ] **Step 10.3: Create `tests/integration/test_memories_live.py`**

```python
"""End-to-end memory CRUD/search/list/delete-all against live postgres + qdrant."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_get_delete_memory(http_client):
    # Create
    r = await http_client.post("/v1/memories", json={
        "user_id": "live-1",
        "content": "User loves dark mode",
        "memory_type": "preference",
        "metadata": {"category": "ui"},
    })
    assert r.status_code == 200
    mem_id = r.json()["data"]["id"]
    assert r.json()["data"]["metadata"] == {"category": "ui"}

    # Get
    r = await http_client.get(f"/v1/memories/{mem_id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == mem_id

    # Delete
    r = await http_client.delete(f"/v1/memories/{mem_id}")
    assert r.status_code == 200

    # Get again — should 404
    r = await http_client.get(f"/v1/memories/{mem_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_semantic_search_ranks_relevant_first(http_client):
    await http_client.post("/v1/memories", json={
        "user_id": "live-2", "content": "User uses Vim daily",
        "memory_type": "preference",
    })
    await http_client.post("/v1/memories", json={
        "user_id": "live-2", "content": "User is allergic to peanuts",
        "memory_type": "fact",
    })

    r = await http_client.post("/v1/memories/search", json={
        "query": "text editor preferences",
        "user_id": "live-2",
        "limit": 5,
    })
    assert r.status_code == 200
    results = r.json()["data"]
    assert len(results) >= 1
    assert "Vim" in results[0]["content"]


@pytest.mark.asyncio
async def test_batch_create_and_list(http_client):
    r = await http_client.post("/v1/memories/batch", json={
        "user_id": "live-3", "agent_id": "clara",
        "messages": [
            {"role": "user", "content": "I love dark mode"},
            {"role": "assistant", "content": "Got it"},
        ],
        "memory_type": "episodic",
        "metadata": {"session_id": "sess-1"},
    })
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2

    # List by metadata
    r = await http_client.post("/v1/memories/list", json={
        "user_id": "live-3",
        "metadata": {"session_id": "sess-1"},
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert all(m["metadata"]["session_id"] == "sess-1" for m in data)


@pytest.mark.asyncio
async def test_list_filter_by_run_id(http_client):
    await http_client.post("/v1/memories/batch", json={
        "user_id": "live-4",
        "messages": [{"role": "user", "content": "x"}],
        "metadata": {"run_id": "r-aaa"},
    })
    await http_client.post("/v1/memories/batch", json={
        "user_id": "live-4",
        "messages": [{"role": "user", "content": "y"}],
        "metadata": {"run_id": "r-bbb"},
    })

    r = await http_client.post("/v1/memories/list", json={
        "user_id": "live-4", "run_id": "r-aaa",
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["content"] == "x"


@pytest.mark.asyncio
async def test_delete_all_for_user(http_client):
    for content in ["a", "b", "c"]:
        await http_client.post("/v1/memories", json={
            "user_id": "live-5", "content": content,
        })

    # Verify they exist
    r = await http_client.get("/v1/users/live-5/memories")
    assert len(r.json()["data"]) == 3

    # Delete all
    r = await http_client.delete("/v1/users/live-5/memories")
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] == 3

    # Verify gone
    r = await http_client.get("/v1/users/live-5/memories")
    assert len(r.json()["data"]) == 0


@pytest.mark.asyncio
async def test_delete_all_with_agent_filter(http_client):
    await http_client.post("/v1/memories", json={
        "user_id": "live-6", "content": "by clara", "agent_id": "clara",
    })
    await http_client.post("/v1/memories", json={
        "user_id": "live-6", "content": "by bob", "agent_id": "bob",
    })

    r = await http_client.delete("/v1/users/live-6/memories?agent_id=clara")
    assert r.json()["data"]["deleted"] == 1

    r = await http_client.get("/v1/users/live-6/memories")
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["agent_id"] == "bob"
```

- [ ] **Step 10.4: Run integration tests for memories**

Run: `.venv/bin/python -m pytest tests/integration/test_memories_live.py -v -m integration`

Expected: 6 tests PASS. First run downloads the postgres + qdrant images and the embedding model, so it may take a few minutes. Subsequent runs are 30-60s.

If a test fails, read the failure carefully — common issues:
- Container engine not running (start `podman machine start` or Docker Desktop).
- Port already in use (kill stray containers from prior runs).
- `_truncate_tables` not picking up tables — make sure the conftest reloads modules in the right order.

---

## Task 11: Add session live tests + client e2e tests

**Files:**
- Create: `tests/integration/test_sessions_live.py`
- Create: `tests/integration/test_client_e2e.py`

- [ ] **Step 11.1: Create `tests/integration/test_sessions_live.py`**

```python
"""End-to-end session/message lifecycle against live postgres."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_session_lifecycle(http_client):
    # Create
    r = await http_client.post("/v1/sessions", json={
        "user_id": "live-s1", "title": "Test chat",
    })
    assert r.status_code == 200
    sid = r.json()["data"]["id"]

    # Add messages
    for role, content in [("user", "Hello"), ("assistant", "Hi there")]:
        r = await http_client.post(f"/v1/sessions/{sid}/messages", json={
            "user_id": "live-s1", "role": role, "content": content,
        })
        assert r.status_code == 200

    # Fetch with messages
    r = await http_client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "Test chat"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Hello"

    # Update
    r = await http_client.patch(f"/v1/sessions/{sid}", json={"summary": "S"})
    assert r.json()["data"]["summary"] == "S"

    # Delete (cascades messages)
    r = await http_client.delete(f"/v1/sessions/{sid}")
    assert r.status_code == 200

    # Get → 404
    r = await http_client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_assemble_context_with_session(http_client):
    # Seed a memory
    await http_client.post("/v1/memories", json={
        "user_id": "live-s2", "content": "User uses Vim",
        "memory_type": "preference",
    })

    # Create a session and add a message
    r = await http_client.post("/v1/sessions", json={"user_id": "live-s2"})
    sid = r.json()["data"]["id"]
    await http_client.post(f"/v1/sessions/{sid}/messages", json={
        "user_id": "live-s2", "role": "user", "content": "What editor?",
    })

    # Assemble
    r = await http_client.post("/v1/context", json={
        "user_id": "live-s2",
        "query": "editor preferences",
        "session_id": sid,
        "max_memories": 5,
    })
    assert r.status_code == 200
    ctx = r.json()["data"]
    assert len(ctx["memories"]) >= 1
    assert "Vim" in ctx["memories"][0]["content"]
    assert len(ctx["recent_messages"]) == 1
```

- [ ] **Step 11.2: Create `tests/integration/test_client_e2e.py`**

```python
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
```

- [ ] **Step 11.3: Run all integration tests**

Run: `.venv/bin/python -m pytest tests/integration/ -v -m integration`

Expected: ~12 tests PASS (6 memories + 2 sessions + 4 client e2e). Total ~30-60s on warm caches.

- [ ] **Step 11.4: Confirm the default test suite is unchanged (no integration tests run)**

Run: `.venv/bin/python -m pytest`

Expected: Only the 23 mock-based tests run (no integration tests, because no `-m integration`).

- [ ] **Step 11.5: Run lint**

Run: `.venv/bin/ruff check tests/integration palace_client/palace_client palace`

Expected: Clean.

- [ ] **Step 11.6: Commit**

```bash
git add pyproject.toml tests/integration/
git commit -m "$(cat <<'EOF'
test(integration): TestContainers-backed end-to-end suite

Opt-in integration tests gated behind `pytest -m integration`. Mock
tests stay default for fast iteration (~2s); integration tests spin
up real postgres + qdrant containers per session and exercise the
full stack end-to-end.

Coverage:
- tests/integration/test_memories_live.py — CRUD, semantic search
  ranking, batch create + list with metadata containment, run_id
  filter, delete_all with agent filter.
- tests/integration/test_sessions_live.py — full session/message
  lifecycle, context assembly with seeded memories.
- tests/integration/test_client_e2e.py — palace_client driving a
  live Palace app via in-process ASGI transport, proves wire-contract
  agreement between client and server.

Containers via testcontainers-python; tables truncated per test for
isolation; Qdrant collection randomized per session to avoid
parallel-test collisions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## ✋ CHECKPOINT 4 — Review commit 4 before continuing

Stop. Verify:
- `git log --oneline -4` shows four slice-1 commits.
- `pytest` is green (mock tests).
- `pytest -m integration` is green (live tests) — tries with podman/Docker running.
- Address review feedback before continuing.

---

# COMMIT 5 — Examples + README

## Task 12: Write the explicit-pass-through router example

**Files:**
- Create: `examples/__init__.py` (empty)
- Create: `examples/mypalclara_router.py`

The router enumerates every public method of the embedded `ClaraMemory` and `MemoryManager` from mypalclara. Each gets either a routed branch (slice 1 methods) or an explicit one-line embedded delegation. **No `__getattr__` fallthrough** (spec D6).

- [ ] **Step 12.1: Create `examples/__init__.py`** (empty file)

- [ ] **Step 12.2: Create `examples/mypalclara_router.py`**

```python
"""
Reference router for mypalclara: per-method delegation between remote
Palace (HTTP) and the embedded ClaraMemory + MemoryManager.

How to use:
    1. Install palace_client into mypalclara's environment:
         pip install -e /path/to/palace-memory/palace_client
       or via git+url:
         pip install "git+https://github.com/BangRocket/palace-memory.git@<sha>#subdirectory=palace_client"
    2. Copy this file into mypalclara as `mypalclara/core/memory/routed.py`
       and adjust the embedded imports to match mypalclara's layout.
    3. Replace every `from mypalclara.core.memory import PALACE` (and the
       analogous MemoryManager import) with imports from the new module.
    4. Toggle behavior at runtime via env vars:
         export USE_PALACE_SERVICE=true
         export PALACE_SERVICE_URL=http://palace.local:8000
         export PALACE_API_KEY=...

This router uses **explicit pass-throughs** (per phase-2 design D6): every
public method of the embedded ClaraMemory + MemoryManager has its own
entry. No __getattr__ fallthrough — adding a new method on the embedded
side requires adding an explicit entry here, otherwise calls raise
AttributeError loudly.

Slice-1 methods routed to remote when toggle is on:
    PALACE.add, .search, .get_all, .delete_all, .get, .delete, .update.
Everything else stays embedded until later slices land.
"""

from __future__ import annotations

import asyncio
import os

from palace_client import PalaceClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USE_PALACE_SERVICE = os.getenv("USE_PALACE_SERVICE", "false").lower() == "true"
PALACE_SERVICE_URL = os.getenv("PALACE_SERVICE_URL", "http://localhost:8000")
PALACE_API_KEY = os.getenv("PALACE_API_KEY")


# ---------------------------------------------------------------------------
# Embedded singletons (replace these imports for the mypalclara environment)
# ---------------------------------------------------------------------------
# In the real mypalclara repo:
#   from mypalclara.core.memory import PALACE as _EMBEDDED_PALACE
#   from mypalclara.core.memory_manager import MemoryManager as _EmbeddedMM
# This file is committed to the palace-memory repo as a reference, so we
# stub them here. Remove the stubs when copying into mypalclara.
class _EmbeddedStub:
    def __getattr__(self, name):
        raise NotImplementedError(
            f"_EmbeddedStub.{name}: replace this stub with the real "
            f"mypalclara import when copying this file in."
        )


_EMBEDDED_PALACE = _EmbeddedStub()
_EmbeddedMM = _EmbeddedStub()


# ---------------------------------------------------------------------------
# Remote client (lazy)
# ---------------------------------------------------------------------------

_REMOTE: PalaceClient | None = None


def _remote() -> PalaceClient:
    global _REMOTE
    if _REMOTE is None:
        _REMOTE = PalaceClient(
            base_url=PALACE_SERVICE_URL, api_key=PALACE_API_KEY,
        )
    return _REMOTE


async def _maybe_await(value):
    """Embedded ClaraMemory is sync; PalaceClient is async. Router methods
    are async, so callers always `await`. This helper awaitifies sync
    return values so the same code path works either way."""
    if asyncio.iscoroutine(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# RoutedPalace — mirror of ClaraMemory's surface
# ---------------------------------------------------------------------------

class RoutedPalace:
    """Looks like ClaraMemory; explicit per-method routing."""

    # ---- Slice 1: remote-eligible ----

    async def add(self, messages, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().add(messages, user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.add(messages, user_id=user_id, **kw),
        )

    async def search(self, query, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().search(query, user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.search(query, user_id=user_id, **kw),
        )

    async def get_all(self, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().get_all(user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.get_all(user_id=user_id, **kw),
        )

    async def delete_all(self, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().delete_all(user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.delete_all(user_id=user_id, **kw),
        )

    async def get(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().get(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.get(memory_id))

    async def delete(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().delete(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.delete(memory_id))

    async def update(self, memory_id, **fields):
        if USE_PALACE_SERVICE:
            return await _remote().update(memory_id, **fields)
        return await _maybe_await(_EMBEDDED_PALACE.update(memory_id, **fields))

    # ---- Slice 2+ candidates: embedded only for now ----

    async def history(self, memory_id):
        # Slice 2 candidate (memory history endpoint).
        return await _maybe_await(_EMBEDDED_PALACE.history(memory_id))

    async def update_memory_visibility(self, memory_id, visibility):
        # Slice 2 candidate.
        return await _maybe_await(
            _EMBEDDED_PALACE.update_memory_visibility(memory_id, visibility),
        )

    # ---- Sub-objects: embedded only in slice 1 ----
    # These are direct attribute accesses (not methods); callers reach into
    # PALACE.embedding_model.embed(...) and PALACE.graph.search(...). When
    # USE_PALACE_SERVICE is on, these still resolve to the embedded objects
    # because there are no remote endpoints for them yet. Slice 2+ may add
    # POST /v1/embeddings and a graph API; this section is the natural place
    # to introduce remote-aware proxies later.

    @property
    def embedding_model(self):
        return _EMBEDDED_PALACE.embedding_model

    @property
    def graph(self):
        return _EMBEDDED_PALACE.graph

    @property
    def episode_store(self):
        return _EMBEDDED_PALACE.episode_store


# ---------------------------------------------------------------------------
# RoutedMemoryManager — mirror of MemoryManager's surface
# ---------------------------------------------------------------------------
# Every public method gets an explicit entry. Slice-1 routes none of these
# (they all stay embedded); branches will be added as slices 2-5 land.

class RoutedMemoryManager:
    """Looks like MemoryManager; every method explicit pass-through to
    embedded in slice 1. Branches added in slices 3-5 as endpoints land.

    Note: Many MemoryManager methods take an SQLAlchemy `db` session as the
    first arg. Those stay embedded indefinitely — there is no plan to send
    a remote DB session over HTTP. They are listed here for completeness so
    that the router shape mirrors the embedded API exactly.
    """

    # ---- Singleton lifecycle ----

    @classmethod
    def initialize(cls, llm_callable, agent_id=None, on_memory_event=None):
        return _EmbeddedMM.initialize(llm_callable, agent_id, on_memory_event)

    @classmethod
    def get_instance(cls):
        return _EmbeddedMM.get_instance()

    @classmethod
    def reset(cls):
        return _EmbeddedMM.reset()

    # ---- Session management (DB-bound, embedded indefinitely) ----

    def get_or_create_session(self, db, user_id, context_id, project_id, title):
        return _EmbeddedMM.get_instance().get_or_create_session(
            db, user_id, context_id, project_id, title,
        )

    def get_thread(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_thread(db, thread_id)

    def get_recent_messages(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_recent_messages(db, thread_id)

    def get_message_count(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_message_count(db, thread_id)

    def store_message(self, db, thread_id, user_id, role, content):
        return _EmbeddedMM.get_instance().store_message(
            db, thread_id, user_id, role, content,
        )

    def should_update_summary(self, db, thread_id):
        return _EmbeddedMM.get_instance().should_update_summary(db, thread_id)

    def update_thread_summary(self, db, thread):
        return _EmbeddedMM.get_instance().update_thread_summary(db, thread)

    # ---- Memory retrieval & writing ----

    def fetch_context(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_context(*args, **kw)

    def add_to_palace(self, *args, **kw):
        return _EmbeddedMM.get_instance().add_to_palace(*args, **kw)

    def add_to_memory(self, *args, **kw):
        return _EmbeddedMM.get_instance().add_to_memory(*args, **kw)

    # ---- Prompt building ----

    def fetch_emotional_context(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_emotional_context(*args, **kw)

    def build_prompt(self, *args, **kw):
        return _EmbeddedMM.get_instance().build_prompt(*args, **kw)

    def build_prompt_layered(self, *args, **kw):
        # Slice 5 candidate.
        return _EmbeddedMM.get_instance().build_prompt_layered(*args, **kw)

    def fetch_topic_recurrence(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_topic_recurrence(*args, **kw)

    async def load_user_workspace(self, user_id, vm_manager):
        return await _maybe_await(
            _EmbeddedMM.get_instance().load_user_workspace(user_id, vm_manager),
        )

    # ---- FSRS dynamics (slice 3) ----

    def get_memory_dynamics(self, memory_id, user_id):
        return _EmbeddedMM.get_instance().get_memory_dynamics(memory_id, user_id)

    def ensure_memory_dynamics(self, memory_id, user_id, is_key):
        return _EmbeddedMM.get_instance().ensure_memory_dynamics(
            memory_id, user_id, is_key,
        )

    def promote_memory(self, memory_id, user_id, grade, signal_type):
        return _EmbeddedMM.get_instance().promote_memory(
            memory_id, user_id, grade, signal_type,
        )

    def demote_memory(self, memory_id, user_id, reason):
        return _EmbeddedMM.get_instance().demote_memory(memory_id, user_id, reason)

    def calculate_memory_score(self, memory_id, user_id, semantic_score):
        return _EmbeddedMM.get_instance().calculate_memory_score(
            memory_id, user_id, semantic_score,
        )

    def get_last_retrieved_memory_ids(self, user_id):
        return _EmbeddedMM.get_instance().get_last_retrieved_memory_ids(user_id)

    def prune_old_access_logs(self, db, retention_days):
        return _EmbeddedMM.get_instance().prune_old_access_logs(db, retention_days)

    # ---- Intentions (slice 4) ----

    def set_intention(self, *args, **kw):
        return _EmbeddedMM.get_instance().set_intention(*args, **kw)

    def check_intentions(self, *args, **kw):
        return _EmbeddedMM.get_instance().check_intentions(*args, **kw)

    def format_intentions_for_prompt(self, fired_intentions):
        return _EmbeddedMM.get_instance().format_intentions_for_prompt(
            fired_intentions,
        )

    # ---- Reflection (slice 4) ----

    async def reflect_on_session(self, messages, user_id, session_id):
        return await _maybe_await(
            _EmbeddedMM.get_instance().reflect_on_session(
                messages, user_id, session_id,
            ),
        )

    async def run_narrative_synthesis(self, user_id):
        return await _maybe_await(
            _EmbeddedMM.get_instance().run_narrative_synthesis(user_id),
        )

    # ---- Smart ingestion (slice 5) ----

    def smart_ingest(self, *args, **kw):
        return _EmbeddedMM.get_instance().smart_ingest(*args, **kw)

    def supersede_memory(self, *args, **kw):
        return _EmbeddedMM.get_instance().supersede_memory(*args, **kw)


# ---------------------------------------------------------------------------
# Public singletons — these are what mypalclara should import.
# ---------------------------------------------------------------------------

PALACE = RoutedPalace()
MM = RoutedMemoryManager()
```

- [ ] **Step 12.3: Verify the example imports cleanly**

Run: `.venv/bin/python -c "import examples.mypalclara_router as r; print('classes:', [c for c in dir(r) if not c.startswith('_')])"`

Expected: prints a list including `PALACE`, `MM`, `RoutedPalace`, `RoutedMemoryManager`, `PalaceClient`, etc. (Imports succeed even though `_EmbeddedStub` stands in for the real mypalclara imports.)

---

## Task 13: Update README with drop-in mode + integration test sections

**Files:**
- Modify: `README.md`

- [ ] **Step 13.1: Add "Drop-in mode for mypalclara" section**

In `README.md`, find the line `## License` near the bottom. Insert the following two sections **before** the `## License` heading:

```markdown
## Drop-in mode for mypalclara (phase 2, slice 1)

Palace ships an async Python client (`palace_client/`) that mypalclara can
use to delegate per-method memory calls to a remote Palace instance,
falling back to the embedded `ClaraMemory` for everything not yet routable.

Install the client into mypalclara's environment:

```bash
pip install "git+https://github.com/BangRocket/palace-memory.git@<sha>#subdirectory=palace_client"
```

Copy `examples/mypalclara_router.py` into mypalclara as
`mypalclara/core/memory/routed.py`, adjust the embedded imports, then
replace every `from mypalclara.core.memory import PALACE` with the routed
version. Toggle behavior at runtime:

```bash
export USE_PALACE_SERVICE=true
export PALACE_SERVICE_URL=http://palace.local:8000
export PALACE_API_KEY=  # optional, forward-compat for phase 3
```

The router uses **explicit pass-throughs** — every public method of
ClaraMemory + MemoryManager has its own entry, no `__getattr__`
fallthrough. Slice-1 methods routed to remote: `add`, `search`,
`get_all`, `delete_all`, `get`, `delete`, `update`. Everything else stays
embedded until later slices land.

See `docs/superpowers/specs/2026-05-03-palace-phase-2-design.md` for the
full design and slice roadmap.

## Integration tests

Default `pytest` runs only the fast mock-based suite (~2s). Live
end-to-end tests against real postgres + qdrant are opt-in:

```bash
pytest                       # mocks only — fast iteration
pytest -m integration        # live containers via testcontainers-python
```

The integration suite spins up postgres + qdrant containers per session
(via [testcontainers-python](https://testcontainers-python.readthedocs.io/)),
truncates tables between tests, and exercises:

- Memory CRUD, semantic search ranking, batch create + filtered list,
  delete-all with filters (`tests/integration/test_memories_live.py`).
- Session/message lifecycle and context assembly
  (`tests/integration/test_sessions_live.py`).
- `palace_client` against a live Palace via in-process ASGI transport,
  proving wire-contract agreement (`tests/integration/test_client_e2e.py`).

Requires Docker or podman with a running machine. First run pulls
postgres + qdrant images and downloads the small embedding model
(`sentence-transformers/all-MiniLM-L6-v2`); subsequent runs are 30-60s.

```

- [ ] **Step 13.2: Run lint over the docs directory and verify the README is well-formed**

Run: `.venv/bin/python -c "import pathlib; print(len(pathlib.Path('README.md').read_text()), 'chars')"`

Expected: a sensible character count (>3000), and no parse error.

- [ ] **Step 13.3: Run the full mock test suite one last time**

Run: `.venv/bin/python -m pytest`

Expected: 23 tests PASS.

- [ ] **Step 13.4: Run lint final pass**

Run: `.venv/bin/ruff check palace tests palace_client/palace_client palace_client/tests examples`

Expected: clean.

- [ ] **Step 13.5: Commit**

```bash
git add examples/ README.md
git commit -m "$(cat <<'EOF'
docs(examples): mypalclara router reference + README updates

- examples/mypalclara_router.py: explicit pass-throughs for every
  public method of ClaraMemory + MemoryManager (per spec D6, no
  __getattr__ fallthrough). Slice-1 routable methods branch on
  USE_PALACE_SERVICE; everything else is a one-line embedded
  delegation. Sub-object proxies (.embedding_model, .graph,
  .episode_store) stay embedded until later slices add remote
  endpoints for them.

- README.md: new "Drop-in mode for mypalclara" section explaining
  client install, file copy, and toggle env vars; new "Integration
  tests" section documenting the opt-in `pytest -m integration`
  flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## ✋ FINAL CHECKPOINT — Verify slice 1 done criteria

Stop. Verify everything in the spec's done criteria:

- [ ] All three new endpoints (`POST /v1/memories/batch`, `POST /v1/memories/list`, `DELETE /v1/users/{user_id}/memories`) implemented, mock-tested, and integration-tested.
- [ ] `palace_client` package installable via `.venv/bin/python -m pip install -e ./palace_client` and importable as `from palace_client import PalaceClient`.
- [ ] All `PalaceClient` methods covered by MockTransport unit tests in `palace_client/tests/test_client.py`.
- [ ] `tests/integration/test_client_e2e.py` round-trips every slice-1 method against a live Palace.
- [ ] `examples/mypalclara_router.py` enumerates every public ClaraMemory + MemoryManager method explicitly (per D6).
- [ ] `README.md` has "Drop-in mode for mypalclara" and "Integration tests" sections.
- [ ] `git log --oneline -5` shows 5 slice-1 commits on `phase-2`.

Then either:

```bash
# Push the branch and open a PR for review
git push -u origin phase-2
gh pr create --title "Phase 2 slice 1: drop-in MVP + palace_client" --body-file docs/superpowers/specs/2026-05-03-palace-phase-2-design.md

# OR fast-forward merge to main locally if no PR review is needed:
git checkout main && git merge --ff-only phase-2 && git push
```

Slice 1 done. Slice 2 (Episodes) starts on a fresh branch off `main`: `phase-2-slice-2-episodes`.

---

# Out of scope (deferred to later slices)

- **Slice 2 — Episodes.** New `Episode` model, LLM-driven extraction, episode CRUD endpoints. Builds on slice-1 client + integration test infra.
- **Slice 3 — FSRS dynamics.** `MemoryDynamics` + `MemoryAccessLog` models, FSRS-6 scoring, promote/demote endpoints.
- **Slice 4 — Reflection + intentions.** `POST /v1/reflection/session`, intention CRUD, `POST /v1/intentions/check`.
- **Slice 5 — Layered retrieval + smart ingestion.** Merges key→semantic→episodic→graph; dedup/supersedence; activates `infer=True` semantics.
- **Phase 3.** Graph (FalkorDB), Redis embedding cache, gRPC, auth, multi-tenancy, PyPI publishing of `palace_client`.

Each gets its own design doc + implementation plan when its turn comes. See the spec's "Phase 2 roadmap" table for ordering and dependencies.
