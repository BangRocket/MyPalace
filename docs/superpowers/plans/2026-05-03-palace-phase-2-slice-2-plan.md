# Palace Phase 2 — Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Ship slice 2 of phase 2: episodic memory subsystem (Episodes in Qdrant, NarrativeArcs in Postgres JSONB, sync+async LLM-driven extraction with job tracking) + matching client + integration tests with stubbed LLM.

**Architecture:** Five-commit slice on `phase-2-slice-2-episodes`. Each commit is independently reviewable. Episodes stored in a separate `palace_episodes` Qdrant collection; arcs in a new `narrative_arcs` Postgres table; jobs in `reflection_jobs` Postgres table. Async mode uses pure asyncio (no Celery/arq). LLM extraction via the existing `palace/llm.py` httpx client.

**Tech Stack:** Same as slice 1, plus: prompts as Python constants under `palace/prompts/`, asyncio.create_task for background jobs, dependency-injected LLM stub in integration tests.

**Spec:** `docs/superpowers/specs/2026-05-03-palace-phase-2-slice-2-episodes-design.md` (commit `5d3fb18` on this branch).

**Repo root:** `/Volumes/Storage/Code/Palace`

---

## File map

### Created

| File | Responsibility |
|------|---------------|
| `palace/episode_service.py` | EpisodeService — Qdrant CRUD + search + LLM-driven reflect_session |
| `palace/arc_service.py` | ArcService — Postgres CRUD + LLM-driven synthesize_narratives |
| `palace/job_service.py` | JobService — reflection_jobs CRUD + asyncio.create_task wrapper |
| `palace/prompts/__init__.py` | Empty marker |
| `palace/prompts/reflection.py` | SESSION_REFLECTION_PROMPT constant |
| `palace/prompts/synthesis.py` | NARRATIVE_SYNTHESIS_PROMPT constant |
| `palace/api/episodes.py` | episode + reflection routes |
| `palace/api/arcs.py` | arc + synthesis routes |
| `palace/api/jobs.py` | job status route |
| `tests/test_episodes.py` | mock-based endpoint + service tests |
| `tests/test_arcs.py` | mock-based arc endpoint tests |
| `tests/test_jobs.py` | mock-based job endpoint tests |
| `tests/integration/test_episodes_live.py` | live integration with stubbed LLM |
| `tests/integration/test_arcs_live.py` | live arc synthesis integration |
| `tests/integration/test_jobs_live.py` | live async job lifecycle |

### Modified

| File | Change |
|------|--------|
| `palace/models.py` | + NarrativeArc table + ReflectionJob table |
| `palace/api/common.py` | + ReflectSessionRequest, SynthesizeRequest, SearchEpisodesRequest, EpisodeOut, NarrativeArcOut, JobOut |
| `palace/main.py` | Register the three new routers + EpisodeService.init() in lifespan |
| `palace/vector.py` | `VectorStore.__init__` accepts an optional `collection` name; new `episode_vector_store` singleton bound to `palace_episodes`. Plus `ensure_payload_indexes` helper for filterable Qdrant fields. |
| `palace_client/palace_client/client.py` | + 6 new methods |
| `palace_client/palace_client/models.py` | + Episode, NarrativeArc, Job |
| `palace_client/palace_client/__init__.py` | re-export new types |
| `palace_client/tests/test_client.py` | + MockTransport tests for 6 new methods |
| `tests/conftest.py` | + mocks for episode_service, arc_service, job_service |
| `tests/integration/conftest.py` | + LLM stub fixture |
| `examples/mypalclara_router.py` | RoutedPalace.episode_store routes; RoutedMemoryManager.reflect_on_session and run_narrative_synthesis branch |
| `README.md` | + slice 2 subsection |

---

## Commit roadmap

1. **Commit 1 — Models + Qdrant collection helper** (Tasks 1-2)
2. **Commit 2 — Endpoints + services + prompts + mock tests** (Tasks 3-7)
3. **Commit 3 — palace_client additions + MockTransport tests** (Tasks 8-9)
4. **Commit 4 — Integration tests with LLM stub** (Tasks 10-12)
5. **Commit 5 — Router updates + README** (Tasks 13-14)

Review checkpoints between commits (no implementation pause — keep moving).

---

# COMMIT 1 — Models + episodes Qdrant collection

## Task 1: NarrativeArc + ReflectionJob SQLModel tables

**Files:**
- Modify: `palace/models.py`
- Test: `tests/test_models_slice2.py` (new tiny test file, optional — round-trip dict via the JSONB column)

- [ ] **Step 1.1: Append the two new tables to `palace/models.py`**

After the existing `Message` class:

```python
class NarrativeArc(SQLModel, table=True):
    """A narrative arc rolling up multiple Episodes into a storyline."""

    __tablename__ = "narrative_arcs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    title: str
    summary: str
    status: str = Field(default="active", index=True)  # active | resolved | dormant
    key_episode_ids: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    emotional_trajectory: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class ReflectionJob(SQLModel, table=True):
    """Tracks status of background reflection/synthesis jobs."""

    __tablename__ = "reflection_jobs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    kind: str = Field(index=True)  # "reflection" | "synthesis"
    user_id: str = Field(index=True)
    status: str = Field(default="pending", index=True)  # pending | completed | failed
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    completed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    result_json: list | dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    error: str | None = None
```

The `JSONB` and `Column` imports already exist (added in slice 1's Task 1). No new imports needed.

- [ ] **Step 1.2: Run the existing test suite to confirm no regression**

```bash
.venv/bin/python -m pytest
```

Expected: 24 PASS (existing slice-1 tests). The new tables don't break anything because no code references them yet.

- [ ] **Step 1.3: Verify SQLModel generates the right schema**

Quick smoke check — start an in-memory SQLite engine and create_all:

```bash
.venv/bin/python -c "
from sqlmodel import SQLModel, create_engine
from palace.models import Memory, Session, Message, NarrativeArc, ReflectionJob
engine = create_engine('sqlite:///:memory:')
SQLModel.metadata.create_all(engine)
print('tables:', [t.name for t in SQLModel.metadata.tables.values()])
"
```

Expected: prints `['memories', 'sessions', 'messages', 'narrative_arcs', 'reflection_jobs']`. If JSONB-on-SQLite errors, that's expected — JSONB is Postgres-only; switch the smoke check to skip the JSONB columns or accept the limitation. (We never actually run on SQLite.)

If the smoke check breaks because of JSONB, skip this verification — the integration tests in commit 4 will exercise the schema against real Postgres.

- [ ] **Step 1.4: Lint**

```bash
.venv/bin/ruff check palace tests
```

Expected: clean.

---

## Task 2: Multi-collection Qdrant support + EpisodeService.init scaffold

**Files:**
- Modify: `palace/vector.py`
- Create: `palace/episode_service.py` (skeleton — full implementation in Task 4)

- [ ] **Step 2.1: Extend `palace/vector.py` to support a named non-default collection**

The current `VectorStore` class hardcodes `self.collection = settings.qdrant_collection`. We need a separate collection for episodes. Two reasonable shapes:

- (a) Pass a collection name to `VectorStore(collection=...)` constructor
- (b) Add a `collection_name` parameter to every method

Choose **(a)** — backwards-compatible (existing `vector_store` singleton keeps the default), cheaper at call sites.

Edit `palace/vector.py`. Replace the `__init__` and the `# Singleton` block at the bottom:

```python
class VectorStore:
    """Async Qdrant vector store wrapper."""

    def __init__(self, collection: str | None = None) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url)
        self.collection = collection or settings.qdrant_collection
        self._dim: int | None = None
```

(The rest of the methods reference `self.collection` already — no other changes.)

At the bottom:

```python
# Singletons — one for memories (the default collection), one for episodes
vector_store = VectorStore()
episode_vector_store = VectorStore(collection="palace_episodes")
```

- [ ] **Step 2.2: Add Qdrant payload-index ensure call for episodes**

Episodes need indexed payload fields (`user_id`, `agent_id`, `significance`, `timestamp`) so Qdrant can filter efficiently. Extend `VectorStore` with a method:

```python
    async def ensure_payload_indexes(self, indexes: dict[str, str]) -> None:
        """Create payload indexes if they don't exist.
        indexes maps field name -> qdrant field type (e.g. 'keyword', 'float', 'datetime').
        Idempotent — Qdrant raises if the index exists, we swallow that case."""
        from qdrant_client.http import models as qmodels

        type_map = {
            "keyword": qmodels.PayloadSchemaType.KEYWORD,
            "float": qmodels.PayloadSchemaType.FLOAT,
            "integer": qmodels.PayloadSchemaType.INTEGER,
            "datetime": qmodels.PayloadSchemaType.DATETIME,
        }
        for field, typ in indexes.items():
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=type_map[typ],
                )
            except Exception:
                # Already exists — Qdrant raises 4xx; safe to ignore.
                pass
```

- [ ] **Step 2.3: Create the EpisodeService skeleton**

`palace/episode_service.py`:

```python
"""Episode storage + LLM-driven reflection service.

Episodes live Qdrant-only (no Postgres table) per design D3. Each Episode is
one Qdrant point in the `palace_episodes` collection: vector = embedding of
`content`; payload = all other fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from palace.embeddings import EmbeddingProvider, get_embedder
from palace.vector import episode_vector_store


class EpisodeService:
    """Business logic for episode storage and retrieval."""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    async def init(self) -> None:
        """Ensure Qdrant collection + payload indexes exist."""
        await episode_vector_store.ensure_collection(self.embedder.dim)
        await episode_vector_store.ensure_payload_indexes({
            "user_id": "keyword",
            "agent_id": "keyword",
            "significance": "float",
            "timestamp": "datetime",
        })

    # reflect_session, search, get_recent — implemented in Task 4


# Singleton
episode_service = EpisodeService()
```

- [ ] **Step 2.4: Wire EpisodeService.init into the app lifespan**

Edit `palace/main.py`. The current `lifespan` calls `init_db()` and `memory_service.init()`. Add the episode init:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and init vector collections."""
    await init_db()
    await memory_service.init()
    await episode_service.init()
    yield
```

Add the import at the top:

```python
from palace.episode_service import episode_service
```

- [ ] **Step 2.5: Run tests to confirm no regression**

```bash
.venv/bin/python -m pytest
```

Expected: 24 PASS. (The new singleton instantiation is lazy — no embedder loaded until init/use.)

- [ ] **Step 2.6: Lint**

```bash
.venv/bin/ruff check palace tests
```

Clean.

- [ ] **Step 2.7: Commit**

```bash
git add palace/models.py palace/vector.py palace/episode_service.py palace/main.py
git commit -m "$(cat <<'EOF'
feat(models): episode storage scaffolding (NarrativeArc, ReflectionJob, Qdrant collection)

Slice 2 commit 1: schema and storage primitives only, no behavior.

- NarrativeArc Postgres table with JSONB key_episode_ids array
- ReflectionJob Postgres table for async-mode tracking
- VectorStore supports a non-default collection (used by new
  episode_vector_store singleton bound to "palace_episodes")
- VectorStore.ensure_payload_indexes for Qdrant filterable fields
- EpisodeService skeleton + lifespan init for collection + indexes

No new endpoints; existing 24-test mock suite stays green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# COMMIT 2 — Endpoints + services + prompts + mock tests

## Task 3: Prompt constants

**Files:**
- Create: `palace/prompts/__init__.py` (empty)
- Create: `palace/prompts/reflection.py`
- Create: `palace/prompts/synthesis.py`

- [ ] **Step 3.1: Create `palace/prompts/__init__.py`** (empty)

- [ ] **Step 3.2: Create `palace/prompts/reflection.py`**

```python
"""Prompt constant for session reflection (episode extraction)."""

SESSION_REFLECTION_PROMPT = """You are analyzing a conversation to extract meaningful episodes.

Conversation:
{conversation_text}

Extract 1-5 distinct episodes from this conversation. For each episode, provide:
- summary: one sentence describing what happened
- topics: list of 1-5 short topic tags
- emotional_tone: one of [happy, sad, anxious, frustrated, curious, neutral, excited, contemplative]
- significance: float 0.0-1.0 indicating how meaningful this exchange was
- start_index, end_index: integer indices into the message list (inclusive, 0-based)

Return ONLY valid JSON in exactly this shape (no markdown fences, no commentary):
{{"episodes": [{{"summary": "...", "topics": ["..."], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}}]}}
"""
```

- [ ] **Step 3.3: Create `palace/prompts/synthesis.py`**

```python
"""Prompt constant for narrative arc synthesis."""

NARRATIVE_SYNTHESIS_PROMPT = """You are identifying narrative arcs across a user's recent episodes.

Recent episodes (most recent first):
{episodes_text}

Existing active arcs (do not duplicate or rename — only update status if needed):
{existing_arcs_text}

Identify ongoing storylines. For each arc, return:
- title: short name (e.g. "Job search", "Move to Berlin")
- summary: 2-3 sentences describing the trajectory
- status: "active" | "resolved" | "dormant"
- key_episode_ids: list of episode IDs that belong to this arc
- emotional_trajectory: brief description of how feelings have evolved
- existing_id: if this updates an existing arc, its ID; otherwise null

Return ONLY valid JSON (no markdown fences):
{{"arcs": [{{"title": "...", "summary": "...", "status": "active", "key_episode_ids": ["..."], "emotional_trajectory": "...", "existing_id": null}}]}}
"""
```

- [ ] **Step 3.4: Lint**

```bash
.venv/bin/ruff check palace
```

Clean.

---

## Task 4: EpisodeService full implementation

**Files:**
- Modify: `palace/episode_service.py` (add reflect_session, search, get_recent)
- Test: `tests/test_episodes.py` (new — service-level tests with mocked LLM and stubbed Qdrant)

- [ ] **Step 4.1: Write the failing service tests first**

Create `tests/test_episodes.py`:

```python
"""Mock-based tests for EpisodeService."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.episode_service import EpisodeService


@pytest.mark.asyncio
async def test_reflect_session_calls_llm_and_writes_episodes():
    """reflect_session should call the LLM, parse JSON, write 1+ episodes
    to Qdrant, and return the parsed list."""
    svc = EpisodeService()

    fake_llm_response = json.dumps({
        "episodes": [
            {
                "summary": "User shared career frustration",
                "topics": ["career", "growth"],
                "emotional_tone": "frustrated",
                "significance": 0.7,
                "start_index": 0,
                "end_index": 1,
            },
        ]
    })

    messages = [
        {"role": "user", "content": "I haven't grown in two years."},
        {"role": "assistant", "content": "What would change that?"},
    ]

    with (
        patch("palace.episode_service.llm.complete", new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "_embedder", create=True, new=MagicMock(embed=AsyncMock(return_value=[[0.1] * 384]))),
        patch("palace.episode_service.episode_vector_store.upsert", new=AsyncMock()) as mock_upsert,
    ):
        episodes = await svc.reflect_session(
            messages=messages, user_id="u1", agent_id="clara", session_id="s-123",
        )

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep["summary"] == "User shared career frustration"
    assert ep["user_id"] == "u1"
    assert ep["agent_id"] == "clara"
    assert ep["session_id"] == "s-123"
    assert ep["topics"] == ["career", "growth"]
    assert ep["significance"] == 0.7
    assert "id" in ep
    assert mock_upsert.called


@pytest.mark.asyncio
async def test_reflect_session_raises_on_llm_returns_garbage():
    """If the LLM returns non-JSON, we raise — no silent fallback (Joshua's
    'fail loudly' rule)."""
    svc = EpisodeService()

    with (
        patch("palace.episode_service.llm.complete", new=AsyncMock(return_value="not json at all")),
        patch.object(svc, "_embedder", create=True, new=MagicMock(embed=AsyncMock())),
    ):
        with pytest.raises(ValueError, match="(?i)json|parse"):
            await svc.reflect_session(messages=[{"role": "user", "content": "hi"}], user_id="u1")


@pytest.mark.asyncio
async def test_search_episodes_filters_by_significance():
    """search() should pass min_significance into the Qdrant query."""
    svc = EpisodeService()

    fake_results = [
        ("ep-1", 0.95),
        ("ep-2", 0.81),
    ]
    fake_payloads = {
        "ep-1": {"summary": "one", "user_id": "u1", "significance": 0.7, "content": "x", "timestamp": "2026-01-01T00:00:00+00:00", "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},
        "ep-2": {"summary": "two", "user_id": "u1", "significance": 0.5, "content": "x", "timestamp": "2026-01-01T00:00:00+00:00", "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},
    }

    async def fake_query_points(**kwargs):
        # Verify min_significance was applied in the filter
        f = kwargs.get("query_filter")
        assert f is not None  # filter applied
        # Return points with payloads
        from types import SimpleNamespace
        return SimpleNamespace(points=[
            SimpleNamespace(id=eid, score=score, payload=fake_payloads[eid])
            for eid, score in fake_results
        ])

    with (
        patch.object(svc, "_embedder", create=True, new=MagicMock(embed=AsyncMock(return_value=[[0.1] * 384]))),
        patch("palace.episode_service.episode_vector_store.client.query_points", new=fake_query_points),
    ):
        results = await svc.search(query="career", user_id="u1", min_significance=0.3, limit=5)

    assert len(results) == 2
    assert results[0]["id"] == "ep-1"


@pytest.mark.asyncio
async def test_get_recent_orders_by_timestamp_desc():
    """get_recent should return episodes newest-first."""
    svc = EpisodeService()

    older = "2026-01-01T00:00:00+00:00"
    newer = "2026-06-01T00:00:00+00:00"

    fake_payloads = [
        {"id": "ep-old", "summary": "old", "user_id": "u1", "timestamp": older, "content": "x", "significance": 0.5, "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},
        {"id": "ep-new", "summary": "new", "user_id": "u1", "timestamp": newer, "content": "x", "significance": 0.5, "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},
    ]

    async def fake_scroll(**kwargs):
        from types import SimpleNamespace
        points = [SimpleNamespace(id=p["id"], payload=p) for p in fake_payloads]
        return (points, None)  # qdrant scroll returns (points, next_offset)

    with patch("palace.episode_service.episode_vector_store.client.scroll", new=fake_scroll):
        results = await svc.get_recent(user_id="u1", limit=5)

    assert len(results) == 2
    # Newest first
    assert results[0]["id"] == "ep-new"
    assert results[1]["id"] == "ep-old"
```

- [ ] **Step 4.2: Verify they fail**

```bash
.venv/bin/python -m pytest tests/test_episodes.py -v
```

Expected: All 4 tests FAIL with `AttributeError: 'EpisodeService' object has no attribute 'reflect_session'` (etc).

- [ ] **Step 4.3: Implement `EpisodeService` methods**

Replace the placeholder block in `palace/episode_service.py` (the comment `# reflect_session, search, get_recent — implemented in Task 4`) with the full implementation. Also add the missing imports at the top.

Full file content for `palace/episode_service.py`:

```python
"""Episode storage + LLM-driven reflection service.

Episodes live Qdrant-only (no Postgres table) per design D3. Each Episode is
one Qdrant point in the `palace_episodes` collection: vector = embedding of
`content`; payload = all other fields.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
)

from palace.embeddings import EmbeddingProvider, get_embedder
from palace.llm import llm
from palace.prompts.reflection import SESSION_REFLECTION_PROMPT
from palace.vector import episode_vector_store


class EpisodeService:
    """Business logic for episode storage and retrieval."""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    async def init(self) -> None:
        """Ensure Qdrant collection + payload indexes exist."""
        await episode_vector_store.ensure_collection(self.embedder.dim)
        await episode_vector_store.ensure_payload_indexes({
            "user_id": "keyword",
            "agent_id": "keyword",
            "significance": "float",
            "timestamp": "datetime",
        })

    async def reflect_session(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        """Call the LLM, parse extracted episodes, write each to Qdrant.
        Returns the list of episodes (as dicts) that were written.

        Raises ValueError if the LLM returns malformed JSON."""
        conversation_text = "\n".join(
            f"[{i}] {m['role']}: {m['content']}" for i, m in enumerate(messages)
        )
        prompt = SESSION_REFLECTION_PROMPT.format(conversation_text=conversation_text)

        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned non-JSON for reflection: {e}") from e

        extracted = parsed.get("episodes", [])
        if not isinstance(extracted, list):
            raise ValueError(f"LLM returned non-list 'episodes' field: {type(extracted).__name__}")

        now = datetime.now(UTC)
        episodes: list[dict] = []

        for raw_ep in extracted:
            start = raw_ep.get("start_index", 0)
            end = raw_ep.get("end_index", len(messages) - 1)
            content_slice = messages[start : end + 1]
            content = "\n".join(f"{m['role']}: {m['content']}" for m in content_slice)

            participants = sorted({m.get("role", "user") for m in content_slice})

            ep = {
                "id": str(uuid4()),
                "user_id": user_id,
                "agent_id": agent_id,
                "content": content,
                "summary": raw_ep.get("summary", ""),
                "participants": participants,
                "topics": raw_ep.get("topics", []),
                "emotional_tone": raw_ep.get("emotional_tone", "neutral"),
                "significance": float(raw_ep.get("significance", 0.5)),
                "timestamp": now.isoformat(),
                "session_id": session_id,
                "message_count": len(content_slice),
            }

            # Embed content and upsert into Qdrant
            vectors = await self.embedder.embed([content])
            await episode_vector_store.upsert(
                memory_id=ep["id"],
                vector=vectors[0],
                payload={k: v for k, v in ep.items() if k != "id"},
            )
            episodes.append(ep)

        return episodes

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        min_significance: float = 0.0,
    ) -> list[dict]:
        """Semantic search over episodes. Filters: user_id (required),
        significance >= min_significance."""
        vectors = await self.embedder.embed([query])

        conditions: list[Any] = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        ]
        if min_significance > 0.0:
            conditions.append(
                FieldCondition(key="significance", range=Range(gte=min_significance)),
            )

        response = await episode_vector_store.client.query_points(
            collection_name=episode_vector_store.collection,
            query=vectors[0],
            limit=limit,
            query_filter=Filter(must=conditions),
            with_payload=True,
        )

        results: list[dict] = []
        for point in response.points:
            payload = dict(point.payload or {})
            payload["id"] = point.id
            payload["score"] = point.score
            results.append(payload)
        return results

    async def get_recent(self, user_id: str, limit: int = 5) -> list[dict]:
        """Recent episodes for a user, newest first."""
        # Qdrant scroll with payload filter; we sort client-side because OrderBy
        # on a payload field has uneven version support.
        points, _ = await episode_vector_store.client.scroll(
            collection_name=episode_vector_store.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))],
            ),
            limit=max(limit * 4, 50),  # over-fetch since we sort client-side
            with_payload=True,
            with_vectors=False,
        )
        items = []
        for p in points:
            payload = dict(p.payload or {})
            payload["id"] = p.id
            items.append(payload)

        # Sort by timestamp desc (timestamps are ISO strings, lex order works for tz-aware ISO)
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:limit]


# Singleton
episode_service = EpisodeService()
```

- [ ] **Step 4.4: Run service tests**

```bash
.venv/bin/python -m pytest tests/test_episodes.py -v
```

Expected: 4 PASS.

- [ ] **Step 4.5: Confirm full mock suite still passes**

```bash
.venv/bin/python -m pytest
```

Expected: 28 PASS (24 prior + 4 new).

---

## Task 5: ArcService full implementation

**Files:**
- Create: `palace/arc_service.py`
- Test: `tests/test_arcs.py` (mock-based)

- [ ] **Step 5.1: Write the failing arc tests first**

Create `tests/test_arcs.py`:

```python
"""Mock-based tests for ArcService."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from palace.arc_service import ArcService


@pytest.mark.asyncio
async def test_synthesize_creates_new_arcs():
    """synthesize_narratives calls the LLM with recent episodes + active arcs,
    parses the response, writes new arc rows."""
    svc = ArcService()

    fake_llm_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "User is exploring leaving current job.",
                "status": "active",
                "key_episode_ids": ["ep-1", "ep-2"],
                "emotional_trajectory": "frustrated -> determined",
                "existing_id": None,
            },
        ]
    })

    fake_recent_episodes = [
        {"id": "ep-1", "summary": "user shared frustration", "timestamp": "2026-06-01T00:00:00+00:00"},
        {"id": "ep-2", "summary": "user named what they want", "timestamp": "2026-06-02T00:00:00+00:00"},
    ]

    created_arc_holder: list = []

    class FakeArcServiceCreate:
        async def __call__(self, **fields):
            class FakeArc:
                pass
            arc = FakeArc()
            for k, v in fields.items():
                setattr(arc, k, v)
            arc.id = "arc-new"
            created_arc_holder.append(arc)
            return arc

    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=fake_recent_episodes)),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        patch.object(svc, "create", new=FakeArcServiceCreate()),
    ):
        arcs = await svc.synthesize_narratives(user_id="u1")

    assert len(arcs) == 1
    assert created_arc_holder[0].title == "Job search"
    assert created_arc_holder[0].status == "active"


@pytest.mark.asyncio
async def test_synthesize_updates_existing_arcs():
    """If LLM returns existing_id, the matching arc is updated, not created."""
    svc = ArcService()

    fake_llm_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "Updated summary.",
                "status": "resolved",
                "key_episode_ids": ["ep-1", "ep-2", "ep-3"],
                "emotional_trajectory": "frustrated -> determined -> relieved",
                "existing_id": "arc-existing",
            },
        ]
    })

    update_calls: list = []

    async def fake_update(arc_id, **fields):
        update_calls.append({"arc_id": arc_id, "fields": fields})
        class FakeArc:
            pass
        a = FakeArc()
        a.id = arc_id
        for k, v in fields.items():
            setattr(a, k, v)
        return a

    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=[])),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        patch.object(svc, "update", new=fake_update),
        patch.object(svc, "create", new=AsyncMock()),
    ):
        arcs = await svc.synthesize_narratives(user_id="u1")

    assert len(update_calls) == 1
    assert update_calls[0]["arc_id"] == "arc-existing"
    assert update_calls[0]["fields"]["status"] == "resolved"
    svc.create.assert_not_called()


@pytest.mark.asyncio
async def test_synthesize_raises_on_garbage_llm():
    svc = ArcService()
    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=[])),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value="not json")),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
    ):
        with pytest.raises(ValueError, match="(?i)json|parse"):
            await svc.synthesize_narratives(user_id="u1")
```

- [ ] **Step 5.2: Verify they fail (no ArcService yet)**

```bash
.venv/bin/python -m pytest tests/test_arcs.py -v
```

Expected: ImportError on `from palace.arc_service import ArcService`.

- [ ] **Step 5.3: Create `palace/arc_service.py`**

```python
"""Narrative arc storage + LLM-driven synthesis."""

from __future__ import annotations

import json

from sqlalchemy import select

from palace.database import async_session
from palace.episode_service import episode_service
from palace.llm import llm
from palace.models import NarrativeArc, utcnow
from palace.prompts.synthesis import NARRATIVE_SYNTHESIS_PROMPT


class ArcService:
    """Business logic for narrative arcs."""

    async def get_active(
        self, user_id: str, limit: int = 10,
    ) -> list[NarrativeArc]:
        """Active arcs for a user, most-recently-updated first."""
        async with async_session() as db:
            from sqlalchemy import desc as sa_desc
            stmt = (
                select(NarrativeArc)
                .where(NarrativeArc.user_id == user_id)
                .where(NarrativeArc.status == "active")
                .order_by(sa_desc(NarrativeArc.updated_at))
                .limit(limit)
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def get(self, arc_id: str) -> NarrativeArc | None:
        async with async_session() as db:
            result = await db.execute(select(NarrativeArc).where(NarrativeArc.id == arc_id))
            return result.scalar_one_or_none()

    async def create(self, **fields) -> NarrativeArc:
        async with async_session() as db:
            arc = NarrativeArc(**fields)
            db.add(arc)
            await db.commit()
            await db.refresh(arc)
            return arc

    async def update(self, arc_id: str, **fields) -> NarrativeArc | None:
        async with async_session() as db:
            result = await db.execute(select(NarrativeArc).where(NarrativeArc.id == arc_id))
            arc = result.scalar_one_or_none()
            if not arc:
                return None
            for k, v in fields.items():
                setattr(arc, k, v)
            arc.updated_at = utcnow()
            await db.commit()
            await db.refresh(arc)
            return arc

    async def synthesize_narratives(
        self,
        user_id: str,
        agent_id: str | None = None,
        lookback_episodes: int = 20,
    ) -> list[NarrativeArc]:
        """Call the LLM with recent episodes + active arcs, parse arcs from
        the response, create new arcs or update existing ones.

        Raises ValueError if the LLM returns malformed JSON."""
        recent_episodes = await episode_service.get_recent(
            user_id=user_id, limit=lookback_episodes,
        )
        existing_arcs = await self.get_active(user_id=user_id)

        episodes_text = "\n".join(
            f"[{e.get('id')}] ({e.get('timestamp', '')}) {e.get('summary', '')}"
            for e in recent_episodes
        ) or "(none)"
        existing_arcs_text = "\n".join(
            f"[{a.id}] {a.title}: {a.summary} (status={a.status})"
            for a in existing_arcs
        ) or "(none)"

        prompt = NARRATIVE_SYNTHESIS_PROMPT.format(
            episodes_text=episodes_text,
            existing_arcs_text=existing_arcs_text,
        )

        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned non-JSON for synthesis: {e}") from e

        extracted = parsed.get("arcs", [])
        if not isinstance(extracted, list):
            raise ValueError(f"LLM returned non-list 'arcs' field: {type(extracted).__name__}")

        results: list[NarrativeArc] = []
        for raw_arc in extracted:
            existing_id = raw_arc.get("existing_id")
            fields = {
                "title": raw_arc.get("title", ""),
                "summary": raw_arc.get("summary", ""),
                "status": raw_arc.get("status", "active"),
                "key_episode_ids": raw_arc.get("key_episode_ids", []),
                "emotional_trajectory": raw_arc.get("emotional_trajectory", ""),
            }
            if existing_id:
                arc = await self.update(existing_id, **fields)
                if arc:
                    results.append(arc)
            else:
                arc = await self.create(
                    user_id=user_id, agent_id=agent_id, **fields,
                )
                results.append(arc)
        return results


# Singleton
arc_service = ArcService()
```

- [ ] **Step 5.4: Run arc tests**

```bash
.venv/bin/python -m pytest tests/test_arcs.py -v
```

Expected: 3 PASS.

---

## Task 6: JobService

**Files:**
- Create: `palace/job_service.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 6.1: Failing tests first**

Create `tests/test_jobs.py`:

```python
"""Mock-based tests for JobService."""

from __future__ import annotations

import asyncio

import pytest

from palace.job_service import JobService


@pytest.mark.asyncio
async def test_create_persists_pending_job():
    svc = JobService()
    # We use real DB here? No — that's an integration concern. Mock the session.
    # For slice 2 we test with the integration suite; this mock test just verifies
    # the public surface exists and the run_async helper schedules a task.
    # Actual persistence behavior is exercised in tests/integration/test_jobs_live.py.

    async def fake_coro():
        return [{"x": 1}]

    # Patch async_session to a no-op for this surface check
    from unittest.mock import AsyncMock, MagicMock, patch
    fake_db = MagicMock()
    fake_db.add = MagicMock()
    fake_db.commit = AsyncMock()
    fake_db.refresh = AsyncMock()

    class FakeAsyncSession:
        async def __aenter__(self): return fake_db
        async def __aexit__(self, *args): return None

    with patch("palace.job_service.async_session", lambda: FakeAsyncSession()):
        job = await svc.create(kind="reflection", user_id="u1")

    fake_db.add.assert_called_once()
    fake_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_run_async_schedules_task_and_returns_pending():
    """run_async creates the job + schedules the coroutine as a task."""
    svc = JobService()

    completed_event = asyncio.Event()
    captured_results: list = []

    async def fake_coro():
        captured_results.append("ran")
        return [{"x": 1}]

    from unittest.mock import AsyncMock, MagicMock, patch

    fake_job = MagicMock()
    fake_job.id = "job-1"

    with (
        patch.object(svc, "create", new=AsyncMock(return_value=fake_job)),
        patch.object(svc, "complete", new=AsyncMock(side_effect=lambda *a, **kw: completed_event.set())),
        patch.object(svc, "fail", new=AsyncMock()),
    ):
        job = await svc.run_async(kind="reflection", user_id="u1", coro_factory=fake_coro)

    assert job.id == "job-1"
    # Wait for the spawned task to complete
    await asyncio.wait_for(completed_event.wait(), timeout=2.0)
    assert captured_results == ["ran"]


@pytest.mark.asyncio
async def test_run_async_records_failure_when_coro_raises():
    svc = JobService()

    failed_event = asyncio.Event()
    captured_errors: list = []

    async def bad_coro():
        raise RuntimeError("kaboom")

    from unittest.mock import AsyncMock, MagicMock, patch

    fake_job = MagicMock()
    fake_job.id = "job-2"

    async def fake_fail(job_id, error):
        captured_errors.append((job_id, error))
        failed_event.set()

    with (
        patch.object(svc, "create", new=AsyncMock(return_value=fake_job)),
        patch.object(svc, "complete", new=AsyncMock()),
        patch.object(svc, "fail", new=fake_fail),
    ):
        await svc.run_async(kind="reflection", user_id="u1", coro_factory=bad_coro)

    await asyncio.wait_for(failed_event.wait(), timeout=2.0)
    assert captured_errors[0][0] == "job-2"
    assert "kaboom" in captured_errors[0][1]
```

- [ ] **Step 6.2: Run them — expect ImportError**

```bash
.venv/bin/python -m pytest tests/test_jobs.py -v
```

- [ ] **Step 6.3: Create `palace/job_service.py`**

```python
"""Background reflection/synthesis job tracking using pure asyncio (no Celery)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from palace.database import async_session
from palace.models import ReflectionJob, utcnow


class JobService:
    """CRUD for ReflectionJob + asyncio.create_task wrapper."""

    async def create(self, kind: str, user_id: str) -> ReflectionJob:
        async with async_session() as db:
            job = ReflectionJob(kind=kind, user_id=user_id, status="pending")
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job

    async def get(self, job_id: str) -> ReflectionJob | None:
        async with async_session() as db:
            result = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            return result.scalar_one_or_none()

    async def complete(self, job_id: str, result: list | dict) -> None:
        async with async_session() as db:
            r = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            job = r.scalar_one_or_none()
            if not job:
                return
            job.status = "completed"
            job.result_json = result
            job.completed_at = utcnow()
            await db.commit()

    async def fail(self, job_id: str, error: str) -> None:
        async with async_session() as db:
            r = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            job = r.scalar_one_or_none()
            if not job:
                return
            job.status = "failed"
            job.error = error
            job.completed_at = utcnow()
            await db.commit()

    async def run_async(
        self,
        kind: str,
        user_id: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> ReflectionJob:
        """Create a pending job, spawn coro_factory() as an asyncio.Task that
        writes result/error back to the job row when done. Returns the
        pending job immediately."""
        job = await self.create(kind=kind, user_id=user_id)

        async def runner():
            try:
                result = await coro_factory()
                # Coerce ORM models to dicts where needed before JSON storage
                serializable = _serialize_result(result)
                await self.complete(job.id, serializable)
            except Exception as e:
                await self.fail(job.id, repr(e))

        asyncio.create_task(runner())
        return job


def _serialize_result(result: Any) -> list | dict:
    """Coerce service return values into JSON-storable shapes for result_json."""
    if isinstance(result, list):
        return [_one(item) for item in result]
    if isinstance(result, dict):
        return result
    return {"value": _one(result)}


def _one(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dict__"):
        # Skip SQLAlchemy internal attrs
        return {k: v for k, v in vars(item).items() if not k.startswith("_")}
    return item


# Singleton
job_service = JobService()
```

- [ ] **Step 6.4: Run job tests**

```bash
.venv/bin/python -m pytest tests/test_jobs.py -v
```

Expected: 3 PASS.

---

## Task 7: API routes + commit 2

**Files:**
- Modify: `palace/api/common.py`
- Create: `palace/api/episodes.py`
- Create: `palace/api/arcs.py`
- Create: `palace/api/jobs.py`
- Modify: `palace/main.py` (register the three routers)
- Modify: `tests/conftest.py` (add mocks for the three new services)
- Modify: `tests/test_episodes.py`, `tests/test_arcs.py`, `tests/test_jobs.py` (add route-level tests on top of service tests)

- [ ] **Step 7.1: Add request/response models in `palace/api/common.py`**

Append to `palace/api/common.py` (after the slice-1 models):

```python
class ReflectionMessage(BaseModel):
    """A single message in a reflection request body."""
    model_config = {"extra": "allow"}
    role: str
    content: str


class ReflectSessionRequest(BaseModel):
    user_id: str
    messages: list[ReflectionMessage]
    agent_id: str | None = None
    session_id: str | None = None


class SynthesizeRequest(BaseModel):
    user_id: str
    agent_id: str | None = None
    lookback_episodes: int = 20


class SearchEpisodesRequest(BaseModel):
    query: str
    user_id: str
    limit: int = 5
    min_significance: float = 0.0


class EpisodeOut(BaseModel):
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    summary: str
    participants: list[str] = []
    topics: list[str] = []
    emotional_tone: str
    significance: float
    timestamp: str | None = None
    session_id: str | None = None
    message_count: int = 0
    score: float | None = None  # only present in search results


class NarrativeArcOut(BaseModel):
    id: str
    user_id: str
    agent_id: str | None = None
    title: str
    summary: str
    status: str
    key_episode_ids: list[str] = []
    emotional_trajectory: str = ""
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_arc(cls, arc) -> "NarrativeArcOut":
        return cls(
            id=arc.id,
            user_id=arc.user_id,
            agent_id=arc.agent_id,
            title=arc.title,
            summary=arc.summary,
            status=arc.status,
            key_episode_ids=arc.key_episode_ids or [],
            emotional_trajectory=arc.emotional_trajectory or "",
            created_at=arc.created_at.isoformat() if arc.created_at else None,
            updated_at=arc.updated_at.isoformat() if arc.updated_at else None,
        )


class JobOut(BaseModel):
    id: str
    kind: str
    user_id: str
    status: str
    created_at: str | None = None
    completed_at: str | None = None
    result: list | dict | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, j) -> "JobOut":
        return cls(
            id=j.id,
            kind=j.kind,
            user_id=j.user_id,
            status=j.status,
            created_at=j.created_at.isoformat() if j.created_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            result=j.result_json,
            error=j.error,
        )


class JobPendingOut(BaseModel):
    job_id: str
    status: str = "pending"
```

- [ ] **Step 7.2: Create `palace/api/episodes.py`**

```python
"""Episode + reflection routes."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from palace.api.common import (
    ApiResponse,
    EpisodeOut,
    JobPendingOut,
    Meta,
    ReflectSessionRequest,
    SearchEpisodesRequest,
)
from palace.episode_service import episode_service
from palace.job_service import job_service

router = APIRouter()              # /v1/episodes/...
reflection_router = APIRouter()   # /v1/reflection/...
users_episodes_router = APIRouter()  # /v1/users/{user_id}/episodes/...


@reflection_router.post("/session")
async def reflect_session(
    req: ReflectSessionRequest,
    mode: Literal["sync", "async"] = Query(default="async"),
):
    start = time.time()
    messages = [m.model_dump() for m in req.messages]

    if mode == "sync":
        episodes = await episode_service.reflect_session(
            messages=messages,
            user_id=req.user_id,
            agent_id=req.agent_id,
            session_id=req.session_id,
        )
        took = int((time.time() - start) * 1000)
        return ApiResponse(
            data=[EpisodeOut(**e) for e in episodes],
            meta=Meta(count=len(episodes), took_ms=took),
        )

    # async mode
    async def coro():
        return await episode_service.reflect_session(
            messages=messages,
            user_id=req.user_id,
            agent_id=req.agent_id,
            session_id=req.session_id,
        )

    job = await job_service.run_async(kind="reflection", user_id=req.user_id, coro_factory=coro)
    took = int((time.time() - start) * 1000)
    from fastapi import Response
    response = ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1, took_ms=took),
    )
    # Return 202 for async
    from fastapi.responses import JSONResponse
    return JSONResponse(content=response.model_dump(), status_code=202)


@router.post("/search", response_model=ApiResponse[list[EpisodeOut]])
async def search_episodes(req: SearchEpisodesRequest):
    start = time.time()
    results = await episode_service.search(
        query=req.query,
        user_id=req.user_id,
        limit=req.limit,
        min_significance=req.min_significance,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EpisodeOut(**r) for r in results],
        meta=Meta(count=len(results), took_ms=took),
    )


@users_episodes_router.get("/{user_id}/episodes/recent", response_model=ApiResponse[list[EpisodeOut]])
async def recent_episodes(user_id: str, limit: int = 5):
    start = time.time()
    items = await episode_service.get_recent(user_id=user_id, limit=limit)
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EpisodeOut(**i) for i in items],
        meta=Meta(count=len(items), took_ms=took),
    )
```

- [ ] **Step 7.3: Create `palace/api/arcs.py`**

```python
"""Narrative arc + synthesis routes."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from palace.api.common import (
    ApiResponse,
    JobPendingOut,
    Meta,
    NarrativeArcOut,
    SynthesizeRequest,
)
from palace.arc_service import arc_service
from palace.job_service import job_service

synthesis_router = APIRouter()           # /v1/synthesis/...
users_arcs_router = APIRouter()          # /v1/users/{user_id}/arcs/...


@synthesis_router.post("/narratives")
async def synthesize_narratives(
    req: SynthesizeRequest,
    mode: Literal["sync", "async"] = Query(default="async"),
):
    start = time.time()

    if mode == "sync":
        arcs = await arc_service.synthesize_narratives(
            user_id=req.user_id,
            agent_id=req.agent_id,
            lookback_episodes=req.lookback_episodes,
        )
        took = int((time.time() - start) * 1000)
        return ApiResponse(
            data=[NarrativeArcOut.from_arc(a) for a in arcs],
            meta=Meta(count=len(arcs), took_ms=took),
        )

    async def coro():
        return await arc_service.synthesize_narratives(
            user_id=req.user_id,
            agent_id=req.agent_id,
            lookback_episodes=req.lookback_episodes,
        )

    job = await job_service.run_async(kind="synthesis", user_id=req.user_id, coro_factory=coro)
    took = int((time.time() - start) * 1000)
    response = ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1, took_ms=took),
    )
    return JSONResponse(content=response.model_dump(), status_code=202)


@users_arcs_router.get("/{user_id}/arcs/active", response_model=ApiResponse[list[NarrativeArcOut]])
async def active_arcs(user_id: str, limit: int = 10):
    start = time.time()
    arcs = await arc_service.get_active(user_id=user_id, limit=limit)
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[NarrativeArcOut.from_arc(a) for a in arcs],
        meta=Meta(count=len(arcs), took_ms=took),
    )
```

- [ ] **Step 7.4: Create `palace/api/jobs.py`**

```python
"""Job status route."""

from fastapi import APIRouter, HTTPException

from palace.api.common import ApiResponse, JobOut, Meta
from palace.job_service import job_service

router = APIRouter()


@router.get("/{job_id}", response_model=ApiResponse[JobOut])
async def get_job(job_id: str):
    job = await job_service.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiResponse(data=JobOut.from_job(job), meta=Meta(count=1))
```

- [ ] **Step 7.5: Wire the routers in `palace/main.py`**

Add the imports + router includes:

```python
from palace.api import arcs, context, episodes, jobs, memories, sessions
```

And in the router-include section after the slice-1 includes:

```python
app.include_router(episodes.router, prefix="/v1/episodes", tags=["episodes"])
app.include_router(episodes.reflection_router, prefix="/v1/reflection", tags=["episodes"])
app.include_router(episodes.users_episodes_router, prefix="/v1/users", tags=["episodes"])
app.include_router(arcs.synthesis_router, prefix="/v1/synthesis", tags=["arcs"])
app.include_router(arcs.users_arcs_router, prefix="/v1/users", tags=["arcs"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
```

- [ ] **Step 7.6: Update conftest mocks**

Edit `tests/conftest.py`. Add fixtures alongside the existing `mock_memory_service`:

```python
@pytest.fixture
def mock_episode_service():
    mock = MagicMock()
    mock.reflect_session = AsyncMock(return_value=[])
    mock.search = AsyncMock(return_value=[])
    mock.get_recent = AsyncMock(return_value=[])
    mock.init = AsyncMock()
    return mock


@pytest.fixture
def mock_arc_service():
    mock = MagicMock()
    mock.synthesize_narratives = AsyncMock(return_value=[])
    mock.get_active = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_job_service():
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.run_async = AsyncMock()
    return mock
```

And extend the `client` fixture's patch block:

```python
    with (
        patch("palace.api.memories.memory_service", mock_memory_service),
        patch("palace.api.sessions.session_service", mock_session_service),
        patch("palace.api.context.context_service", mock_context_service),
        patch("palace.api.episodes.episode_service", mock_episode_service),
        patch("palace.api.episodes.job_service", mock_job_service),
        patch("palace.api.arcs.arc_service", mock_arc_service),
        patch("palace.api.arcs.job_service", mock_job_service),
        patch("palace.api.jobs.job_service", mock_job_service),
        patch("palace.memory_service.memory_service", mock_memory_service),
        patch("palace.episode_service.episode_service", mock_episode_service),
        patch("palace.database.init_db", AsyncMock()),
    ):
```

Update the `client` fixture signature to include the new fixtures: `client(mock_memory_service, mock_session_service, mock_context_service, mock_episode_service, mock_arc_service, mock_job_service)`.

- [ ] **Step 7.7: Add route-level mock tests**

Append to `tests/test_episodes.py`:

```python
def test_reflect_session_sync_returns_episodes(client, mock_episode_service):
    """POST /v1/reflection/session?mode=sync calls service and returns episodes."""
    mock_episode_service.reflect_session.return_value = [
        {
            "id": "ep-1", "user_id": "u1", "agent_id": "clara",
            "content": "x", "summary": "s",
            "participants": ["user"], "topics": ["t"],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": "s-1", "message_count": 1,
        }
    ]

    resp = client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "u1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == "ep-1"
    mock_episode_service.reflect_session.assert_awaited_once()


def test_reflect_session_async_returns_job_id(client, mock_episode_service, mock_job_service):
    """Default async mode returns 202 + job_id."""
    fake_job = MagicMock()
    fake_job.id = "job-abc"
    mock_job_service.run_async.return_value = fake_job

    resp = client.post(
        "/v1/reflection/session",
        json={
            "user_id": "u1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["job_id"] == "job-abc"
    assert data["status"] == "pending"
    mock_job_service.run_async.assert_awaited_once()


def test_search_episodes(client, mock_episode_service):
    mock_episode_service.search.return_value = [
        {
            "id": "ep-1", "user_id": "u1", "agent_id": None,
            "content": "x", "summary": "s",
            "participants": [], "topics": [],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": None, "message_count": 0, "score": 0.95,
        }
    ]
    resp = client.post(
        "/v1/episodes/search",
        json={"query": "career", "user_id": "u1", "limit": 5, "min_significance": 0.3},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["score"] == 0.95


def test_recent_episodes(client, mock_episode_service):
    mock_episode_service.get_recent.return_value = [
        {
            "id": "ep-x", "user_id": "u1", "agent_id": None,
            "content": "x", "summary": "s",
            "participants": [], "topics": [],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": None, "message_count": 0,
        }
    ]
    resp = client.get("/v1/users/u1/episodes/recent?limit=10")
    assert resp.status_code == 200
    assert resp.json()["meta"]["count"] == 1
```

(Note: `MagicMock` import — add `from unittest.mock import MagicMock` to the file's imports.)

Append to `tests/test_arcs.py`:

```python
class FakeArc:
    def __init__(self, **kw):
        self.id = kw.get("id", "arc-1")
        self.user_id = kw.get("user_id", "u1")
        self.agent_id = kw.get("agent_id", None)
        self.title = kw.get("title", "T")
        self.summary = kw.get("summary", "S")
        self.status = kw.get("status", "active")
        self.key_episode_ids = kw.get("key_episode_ids", [])
        self.emotional_trajectory = kw.get("emotional_trajectory", "")
        from datetime import datetime, UTC
        self.created_at = kw.get("created_at", datetime.now(UTC))
        self.updated_at = kw.get("updated_at", datetime.now(UTC))


def test_synthesize_narratives_sync(client, mock_arc_service):
    mock_arc_service.synthesize_narratives.return_value = [FakeArc(id="arc-new")]
    resp = client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "u1", "lookback_episodes": 20},
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "arc-new"


def test_synthesize_narratives_async(client, mock_arc_service, mock_job_service):
    from unittest.mock import MagicMock
    fake_job = MagicMock()
    fake_job.id = "job-syn"
    mock_job_service.run_async.return_value = fake_job

    resp = client.post("/v1/synthesis/narratives", json={"user_id": "u1"})
    assert resp.status_code == 202
    assert resp.json()["data"]["job_id"] == "job-syn"


def test_active_arcs(client, mock_arc_service):
    mock_arc_service.get_active.return_value = [FakeArc(id="a1", title="Job search")]
    resp = client.get("/v1/users/u1/arcs/active?limit=5")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["title"] == "Job search"
```

Append to `tests/test_jobs.py`:

```python
def test_get_job_found(client, mock_job_service):
    from datetime import datetime, UTC
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.id = "j1"
    fake.kind = "reflection"
    fake.user_id = "u1"
    fake.status = "completed"
    fake.created_at = datetime.now(UTC)
    fake.completed_at = datetime.now(UTC)
    fake.result_json = [{"x": 1}]
    fake.error = None
    mock_job_service.get.return_value = fake

    resp = client.get("/v1/jobs/j1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["result"] == [{"x": 1}]


def test_get_job_404(client, mock_job_service):
    mock_job_service.get.return_value = None
    resp = client.get("/v1/jobs/missing")
    assert resp.status_code == 404
```

- [ ] **Step 7.8: Run full mock suite**

```bash
.venv/bin/python -m pytest -v
```

Expected: ~37-40 tests PASS (24 prior + ~13-16 new across episodes/arcs/jobs).

- [ ] **Step 7.9: Lint**

```bash
.venv/bin/ruff check palace tests
```

Clean.

- [ ] **Step 7.10: Commit**

```bash
git add palace/episode_service.py palace/arc_service.py palace/job_service.py palace/prompts/ palace/api/episodes.py palace/api/arcs.py palace/api/jobs.py palace/api/common.py palace/main.py tests/test_episodes.py tests/test_arcs.py tests/test_jobs.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(api): episode + arc + reflection + synthesis + job endpoints

Slice 2 commit 2: full endpoint surface + service implementations.

Endpoints:
- POST /v1/reflection/session (sync/async modes via ?mode= query)
- POST /v1/episodes/search (semantic + min_significance filter)
- GET /v1/users/{user_id}/episodes/recent
- POST /v1/synthesis/narratives (sync/async modes)
- GET /v1/users/{user_id}/arcs/active
- GET /v1/jobs/{job_id}

Services: EpisodeService (Qdrant + LLM), ArcService (Postgres + LLM),
JobService (asyncio.create_task wrapper around reflection_jobs table).

Both LLM-driven services raise ValueError on malformed JSON — no
silent fallback. Async mode persists pending job, spawns asyncio
task, writes result/error back to row when done.

Prompts as plain Python constants in palace/prompts/.

~13 new mock tests covering routes + service behavior with mocked
LLM. Live LLM not exercised here — that's commit 4 (integration).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# COMMIT 3 — palace_client + MockTransport tests

## Task 8: Wire types + client methods

**Files:**
- Modify: `palace_client/palace_client/models.py`
- Modify: `palace_client/palace_client/__init__.py`
- Modify: `palace_client/palace_client/client.py`

- [ ] **Step 8.1: Add wire types in `models.py`**

Append:

```python
class Episode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    emotional_tone: str
    significance: float
    timestamp: datetime | None = None
    session_id: str | None = None
    message_count: int = 0
    score: float | None = None


class NarrativeArc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    title: str
    summary: str
    status: str
    key_episode_ids: list[str] = Field(default_factory=list)
    emotional_trajectory: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    kind: str
    user_id: str
    status: str
    created_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any | None = None
    error: str | None = None


class JobPending(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_id: str
    status: str = "pending"
```

- [ ] **Step 8.2: Re-export from `__init__.py`**

Add to the `from palace_client.models import (...)` block:

```python
    Episode,
    Job,
    JobPending,
    NarrativeArc,
```

And to `__all__`.

- [ ] **Step 8.3: Add 6 client methods to `client.py`**

Append before `# ---- health ----`:

```python
    # ---- episodes / reflection ----

    async def reflect_session(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        mode: str = "async",
    ) -> "list[Episode] | JobPending":
        body: dict[str, Any] = {"user_id": user_id, "messages": messages}
        if agent_id is not None:
            body["agent_id"] = agent_id
        if session_id is not None:
            body["session_id"] = session_id
        envelope = await self._request(
            "POST", "/v1/reflection/session",
            json=body, params={"mode": mode},
        )
        data = self._data(envelope)
        if mode == "sync":
            return [Episode.model_validate(e) for e in data or []]
        return JobPending.model_validate(data)

    async def search_episodes(
        self, query: str, user_id: str,
        limit: int = 5, min_significance: float = 0.0,
    ) -> "list[Episode]":
        body = {
            "query": query, "user_id": user_id,
            "limit": limit, "min_significance": min_significance,
        }
        envelope = await self._request("POST", "/v1/episodes/search", json=body)
        return [Episode.model_validate(e) for e in self._data(envelope) or []]

    async def get_recent_episodes(self, user_id: str, limit: int = 5) -> "list[Episode]":
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/episodes/recent",
            params={"limit": limit},
        )
        return [Episode.model_validate(e) for e in self._data(envelope) or []]

    # ---- arcs / synthesis ----

    async def synthesize_narratives(
        self, user_id: str, agent_id: str | None = None,
        lookback_episodes: int = 20, mode: str = "async",
    ) -> "list[NarrativeArc] | JobPending":
        body: dict[str, Any] = {"user_id": user_id, "lookback_episodes": lookback_episodes}
        if agent_id is not None:
            body["agent_id"] = agent_id
        envelope = await self._request(
            "POST", "/v1/synthesis/narratives",
            json=body, params={"mode": mode},
        )
        data = self._data(envelope)
        if mode == "sync":
            return [NarrativeArc.model_validate(a) for a in data or []]
        return JobPending.model_validate(data)

    async def get_active_arcs(self, user_id: str, limit: int = 10) -> "list[NarrativeArc]":
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/arcs/active",
            params={"limit": limit},
        )
        return [NarrativeArc.model_validate(a) for a in self._data(envelope) or []]

    # ---- jobs ----

    async def get_job(self, job_id: str) -> "Job":
        envelope = await self._request("GET", f"/v1/jobs/{job_id}")
        return Job.model_validate(self._data(envelope))
```

Add the imports at the top of client.py:

```python
from palace_client.models import (
    Context,
    Episode,
    Job,
    JobPending,
    Memory,
    Message,
    NarrativeArc,
    ScoredMemory,
    Session,
    SessionWithMessages,
)
```

---

## Task 9: Client tests + commit 3

**Files:**
- Modify: `palace_client/tests/test_client.py`

- [ ] **Step 9.1: Append client tests**

Append at the end of `palace_client/tests/test_client.py`:

```python
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
```

- [ ] **Step 9.2: Run client tests**

```bash
cd palace_client && ../.venv/bin/python -m pytest -v && cd ..
```

Expected: ~33 PASS (24 prior + 9 new).

- [ ] **Step 9.3: Run parent + lint**

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check palace_client/palace_client palace_client/tests
```

Both clean.

- [ ] **Step 9.4: Commit**

```bash
git add palace_client/
git commit -m "$(cat <<'EOF'
feat(client): episode/arc/job methods + wire types

Slice 2 commit 3: palace_client gains 6 new methods covering the
episode subsystem.

Methods:
- reflect_session(messages, user_id, ..., mode='async') — returns
  list[Episode] in sync mode or JobPending in async mode.
- search_episodes(query, user_id, ..., min_significance)
- get_recent_episodes(user_id, limit)
- synthesize_narratives(user_id, ..., mode='async') — same dual
  return as reflect_session.
- get_active_arcs(user_id, limit)
- get_job(job_id) — raises PalaceNotFound on 404.

New wire types: Episode, NarrativeArc, Job, JobPending. All Pydantic
v2, mirror server response shapes 1:1, datetimes parsed tz-aware.

9 new MockTransport unit tests cover request shapes, response
parsing, sync vs async dispatch, and 404 handling.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# COMMIT 4 — Integration tests with stubbed LLM

## Task 10: LLM stub fixture + episodes live tests

**Files:**
- Modify: `tests/integration/conftest.py` (add LLM stub fixture)
- Create: `tests/integration/test_episodes_live.py`

- [ ] **Step 10.1: Add `stub_llm` fixture in `tests/integration/conftest.py`**

Append to the file:

```python
@pytest_asyncio.fixture
async def stub_llm(palace_app):
    """Override palace.llm.llm.complete with a per-test stub.
    Tests set `stub_llm.next_response = "..."` before triggering reflection."""

    from unittest.mock import AsyncMock

    from palace import llm as llm_module

    holder = type("Holder", (), {"next_response": ""})()
    original = llm_module.llm.complete
    llm_module.llm.complete = AsyncMock(side_effect=lambda *a, **kw: holder.next_response)
    yield holder
    llm_module.llm.complete = original
```

- [ ] **Step 10.2: Create `tests/integration/test_episodes_live.py`**

```python
"""End-to-end episode tests with a stubbed LLM."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_reflect_creates_episodes_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "User shared a small win",
                "topics": ["work"],
                "emotional_tone": "happy",
                "significance": 0.6,
                "start_index": 0,
                "end_index": 1,
            }
        ]
    })

    resp = await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "live-ep-1",
            "messages": [
                {"role": "user", "content": "I shipped the migration today!"},
                {"role": "assistant", "content": "Nice — how do you feel?"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["summary"] == "User shared a small win"
    assert data[0]["significance"] == 0.6
    assert data[0]["user_id"] == "live-ep-1"


@pytest.mark.asyncio
async def test_search_episodes_live(http_client, stub_llm):
    """Seed two episodes via reflect, then search and verify they come back."""
    stub_llm.next_response = json.dumps({
        "episodes": [
            {"summary": "shipped migration", "topics": ["work"], "emotional_tone": "happy", "significance": 0.7, "start_index": 0, "end_index": 0},
            {"summary": "talked about Vim", "topics": ["editor"], "emotional_tone": "neutral", "significance": 0.4, "start_index": 1, "end_index": 1},
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "live-ep-2",
            "messages": [
                {"role": "user", "content": "Migration done."},
                {"role": "user", "content": "Vim is great."},
            ],
        },
    )

    resp = await http_client.post(
        "/v1/episodes/search",
        json={"query": "production deployment", "user_id": "live-ep-2", "limit": 5},
    )
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_recent_episodes_orders_newest_first_live(http_client, stub_llm):
    """Reflect twice; the newer episodes should appear first in /recent."""
    stub_llm.next_response = json.dumps({
        "episodes": [{"summary": "older", "topics": [], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-ep-3", "messages": [{"role": "user", "content": "first"}]},
    )

    import asyncio
    await asyncio.sleep(0.05)  # ensure timestamp ordering

    stub_llm.next_response = json.dumps({
        "episodes": [{"summary": "newer", "topics": [], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-ep-3", "messages": [{"role": "user", "content": "second"}]},
    )

    resp = await http_client.get("/v1/users/live-ep-3/episodes/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 2
    assert data[0]["summary"] == "newer"


@pytest.mark.asyncio
async def test_search_filters_by_significance_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {"summary": "low sig", "topics": [], "emotional_tone": "neutral", "significance": 0.2, "start_index": 0, "end_index": 0},
            {"summary": "high sig", "topics": [], "emotional_tone": "neutral", "significance": 0.8, "start_index": 0, "end_index": 0},
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-ep-4", "messages": [{"role": "user", "content": "x"}]},
    )

    resp = await http_client.post(
        "/v1/episodes/search",
        json={"query": "anything", "user_id": "live-ep-4", "limit": 5, "min_significance": 0.5},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Only the high-sig episode should be present
    assert all(e["significance"] >= 0.5 for e in data)
```

Also extend the integration `_truncate_tables` autouse fixture to clean the new tables + the episodes Qdrant collection. In `tests/integration/conftest.py`, find the existing `_truncate_tables` fixture and update its body:

```python
@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(palace_app):
    """Truncate tables and clear Qdrant points between tests."""
    from sqlalchemy import delete

    from palace.database import async_session
    from palace.models import (
        Memory, Message, NarrativeArc, ReflectionJob,
        Session as SessionModel,
    )
    from palace.vector import episode_vector_store, vector_store

    async with async_session() as db:
        await db.execute(delete(Message))
        await db.execute(delete(SessionModel))
        await db.execute(delete(Memory))
        await db.execute(delete(NarrativeArc))
        await db.execute(delete(ReflectionJob))
        await db.commit()

    # Clear all vector points by recreating the collections
    import contextlib
    with contextlib.suppress(Exception):
        await vector_store.client.delete_collection(vector_store.collection)
    with contextlib.suppress(Exception):
        await episode_vector_store.client.delete_collection(episode_vector_store.collection)

    from palace.episode_service import episode_service
    from palace.memory_service import memory_service
    await memory_service.init()
    await episode_service.init()
    yield
```

- [ ] **Step 10.3: Run episode integration tests**

```bash
.venv/bin/python -m pytest tests/integration/test_episodes_live.py -v -m integration
```

Expected: 4 PASS. May take 30-60s on warm caches (first run pulls qdrant/postgres images and downloads the small embedding model).

---

## Task 11: Arcs + jobs integration tests

**Files:**
- Create: `tests/integration/test_arcs_live.py`
- Create: `tests/integration/test_jobs_live.py`

- [ ] **Step 11.1: Create `tests/integration/test_arcs_live.py`**

```python
"""End-to-end narrative arc tests with a stubbed LLM."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_synthesize_creates_arcs_live(http_client, stub_llm):
    # First seed an episode so synthesize_narratives has something to look at
    stub_llm.next_response = json.dumps({
        "episodes": [
            {"summary": "user shared career frustration", "topics": ["career"], "emotional_tone": "frustrated", "significance": 0.7, "start_index": 0, "end_index": 0},
        ]
    })
    seed_resp = await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-arc-1", "messages": [{"role": "user", "content": "I'm stuck at this job."}]},
    )
    assert seed_resp.status_code == 200

    # Now synthesize
    stub_llm.next_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "User is exploring leaving their current role.",
                "status": "active",
                "key_episode_ids": [seed_resp.json()["data"][0]["id"]],
                "emotional_trajectory": "frustrated",
                "existing_id": None,
            }
        ]
    })
    resp = await http_client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "live-arc-1", "lookback_episodes": 20},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Job search"


@pytest.mark.asyncio
async def test_active_arcs_filters_by_status_live(http_client, stub_llm):
    """Create one active and one resolved arc; only active should show in /active."""
    stub_llm.next_response = json.dumps({
        "episodes": [
            {"summary": "x", "topics": [], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-arc-2", "messages": [{"role": "user", "content": "x"}]},
    )

    stub_llm.next_response = json.dumps({
        "arcs": [
            {"title": "Active arc", "summary": "S", "status": "active", "key_episode_ids": [], "emotional_trajectory": "", "existing_id": None},
            {"title": "Resolved arc", "summary": "S", "status": "resolved", "key_episode_ids": [], "emotional_trajectory": "", "existing_id": None},
        ]
    })
    await http_client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "live-arc-2"},
    )

    resp = await http_client.get("/v1/users/live-arc-2/arcs/active?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(a["status"] == "active" for a in data)
    titles = [a["title"] for a in data]
    assert "Active arc" in titles
    assert "Resolved arc" not in titles
```

- [ ] **Step 11.2: Create `tests/integration/test_jobs_live.py`**

```python
"""End-to-end async job lifecycle tests."""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_async_reflection_job_lifecycle_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {"summary": "x", "topics": [], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}
        ]
    })

    # POST async — returns 202 + job_id immediately
    resp = await http_client.post(
        "/v1/reflection/session",
        json={"user_id": "live-job-1", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["job_id"]

    # Poll until completed (or timeout)
    final = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await http_client.get(f"/v1/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()["data"]
        if body["status"] in {"completed", "failed"}:
            final = body
            break

    assert final is not None, "job did not finish in time"
    assert final["status"] == "completed"
    assert isinstance(final["result"], list)
    assert len(final["result"]) == 1
    assert final["result"][0]["summary"] == "x"


@pytest.mark.asyncio
async def test_async_job_failure_is_recorded_live(http_client, stub_llm):
    """If the LLM returns garbage, the job is marked failed with the error."""
    stub_llm.next_response = "not json at all"

    resp = await http_client.post(
        "/v1/reflection/session",
        json={"user_id": "live-job-2", "messages": [{"role": "user", "content": "x"}]},
    )
    job_id = resp.json()["data"]["job_id"]

    final = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await http_client.get(f"/v1/jobs/{job_id}")
        body = r.json()["data"]
        if body["status"] in {"completed", "failed"}:
            final = body
            break

    assert final is not None
    assert final["status"] == "failed"
    assert "json" in (final["error"] or "").lower() or "value" in (final["error"] or "").lower()


@pytest.mark.asyncio
async def test_get_unknown_job_404(http_client):
    r = await http_client.get("/v1/jobs/missing")
    assert r.status_code == 404
```

- [ ] **Step 11.3: Run all integration tests**

```bash
.venv/bin/python -m pytest tests/integration/ -v -m integration
```

Expected: ~21 PASS (12 prior from slice 1 + 4 episodes + 2 arcs + 3 jobs). Total runtime probably 30-60s on warm caches.

---

## Task 12: Verify and commit 4

- [ ] **Step 12.1: Run all suites + lint**

```bash
.venv/bin/python -m pytest                                            # default — should be ~37-40 PASS, integration tests deselected
.venv/bin/python -m pytest tests/integration/ -v -m integration       # ~21 PASS
cd palace_client && ../.venv/bin/python -m pytest && cd ..            # ~33 PASS
.venv/bin/ruff check palace tests palace_client/palace_client palace_client/tests
```

All green.

- [ ] **Step 12.2: Commit**

```bash
git add tests/integration/
git commit -m "$(cat <<'EOF'
test(integration): live episode/arc/job coverage with stubbed LLM

Slice 2 commit 4: opt-in TestContainers integration suite extended
to cover episodes, narrative arcs, and async job lifecycle.

Coverage:
- test_episodes_live.py (4 tests) — sync reflection creates episodes
  in Qdrant, semantic search returns them, /recent orders newest-first,
  min_significance filter is applied.
- test_arcs_live.py (2 tests) — synthesize creates arc rows;
  /active filters by status="active".
- test_jobs_live.py (3 tests) — async POST returns 202 + job_id,
  poll-until-completed shows status transition, LLM JSON parse
  failure marks the job failed with error text recorded, unknown
  job 404s.

LLM is stubbed via dependency injection (`stub_llm` fixture in
tests/integration/conftest.py) — no real LLM calls. _truncate_tables
extended to clear narrative_arcs, reflection_jobs, and the episodes
Qdrant collection between tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# COMMIT 5 — Router updates + README

## Task 13: Update mypalclara router

**Files:**
- Modify: `examples/mypalclara_router.py`

- [ ] **Step 13.1: Add a `RemoteEpisodeStore` proxy class**

In `examples/mypalclara_router.py`, after the imports and before `_REMOTE`, add:

```python
class RemoteEpisodeStore:
    """Proxy that exposes ClaraMemory.episode_store's surface (search, get_recent,
    get_active_arcs) but routes to a remote PalaceClient."""

    def __init__(self, client: PalaceClient) -> None:
        self._client = client

    async def search(self, query: str, user_id: str, limit: int = 5, min_significance: float = 0.0):
        return await self._client.search_episodes(
            query=query, user_id=user_id, limit=limit, min_significance=min_significance,
        )

    async def get_recent(self, user_id: str, limit: int = 5):
        return await self._client.get_recent_episodes(user_id=user_id, limit=limit)

    async def get_active_arcs(self, user_id: str, limit: int = 10):
        return await self._client.get_active_arcs(user_id=user_id, limit=limit)
```

- [ ] **Step 13.2: Route `episode_store` property in `RoutedPalace`**

Find the existing `episode_store` property in `RoutedPalace` (currently embedded-only) and replace it with:

```python
    @property
    def episode_store(self):
        if USE_PALACE_SERVICE:
            return RemoteEpisodeStore(_remote())
        return _EMBEDDED_PALACE.episode_store
```

- [ ] **Step 13.3: Route `reflect_on_session` and `run_narrative_synthesis` in `RoutedMemoryManager`**

Find the existing `reflect_on_session` method (currently a one-line embedded delegate) and replace with:

```python
    async def reflect_on_session(self, messages, user_id, session_id):
        if USE_PALACE_SERVICE:
            # Use sync mode so the call shape (returns list of episodes) matches
            # the embedded ClaraMemory contract. Async mode would change the
            # return type and break callers.
            return await _remote().reflect_session(
                messages=messages, user_id=user_id, session_id=session_id, mode="sync",
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().reflect_on_session(messages, user_id, session_id),
        )
```

Find `run_narrative_synthesis` and similarly replace with:

```python
    async def run_narrative_synthesis(self, user_id):
        if USE_PALACE_SERVICE:
            return await _remote().synthesize_narratives(user_id=user_id, mode="sync")
        return await _maybe_await(
            _EmbeddedMM.get_instance().run_narrative_synthesis(user_id),
        )
```

- [ ] **Step 13.4: Smoke check the example imports**

```bash
cd /tmp && /Volumes/Storage/Code/Palace/.venv/bin/python -c "import sys; sys.path.insert(0, '/Volumes/Storage/Code/Palace'); import examples.mypalclara_router as r; print('routes:', 'RemoteEpisodeStore' in dir(r))" && cd -
```

Expected: `routes: True`. (Run from `/tmp` to avoid the cwd-shadowing the root conftest.py handles for pytest.)

- [ ] **Step 13.5: Lint**

```bash
.venv/bin/ruff check examples
```

Clean.

---

## Task 14: README + commit 5

**Files:**
- Modify: `README.md`

- [ ] **Step 14.1: Append a slice 2 subsection**

In `README.md`, find the `## Drop-in mode for mypalclara (phase 2, slice 1)` heading. Replace it with `## Drop-in mode for mypalclara (phase 2)` (drop the slice qualifier) and append a slice 2 subsection right after the existing "Drop-in mode" body, before the "## Integration tests" heading:

```markdown
### Slice 2 additions: episodes + narrative arcs

Six more endpoints that mypalclara's `episode_store.*` and `MM.reflect_on_session` /
`MM.run_narrative_synthesis` callers can route to remote Palace:

- `POST /v1/reflection/session?mode={sync,async}` — extract episodes from a message list. Default async returns 202 + job id; sync returns the extracted episodes inline.
- `POST /v1/synthesis/narratives?mode={sync,async}` — roll recent episodes into narrative arcs.
- `POST /v1/episodes/search` — semantic search over episodes with `min_significance` filter.
- `GET /v1/users/{user_id}/episodes/recent?limit=5` — recent episodes, newest first.
- `GET /v1/users/{user_id}/arcs/active?limit=10` — active narrative arcs.
- `GET /v1/jobs/{job_id}` — poll async job status (`pending` / `completed` / `failed`) and retrieve the result.

Storage: episodes in a separate `palace_episodes` Qdrant collection; arcs in a `narrative_arcs` Postgres table with a JSONB `key_episode_ids` array. Async mode uses pure asyncio (no Celery/arq); jobs in flight don't survive process restarts (caller can re-POST).

LLM extraction uses `palace/llm.py`'s OpenAI-compatible chat-completion client (works against OpenRouter, OpenAI, Anthropic-via-OpenRouter, or any compatible endpoint). Set `LLM_API_KEY` in `.env`.

The `examples/mypalclara_router.py` reference now routes `episode_store`, `reflect_on_session`, and `run_narrative_synthesis` when `USE_PALACE_SERVICE=true`, falling back to embedded otherwise.
```

- [ ] **Step 14.2: Verify everything**

```bash
.venv/bin/python -m pytest                                            # default mock suite
cd palace_client && ../.venv/bin/python -m pytest && cd ..            # client mocks
.venv/bin/ruff check palace tests palace_client/palace_client palace_client/tests examples
```

All clean.

- [ ] **Step 14.3: Commit**

```bash
git add examples/mypalclara_router.py README.md
git commit -m "$(cat <<'EOF'
docs(examples): router routes episode_store + reflect/synthesize; README slice-2 section

Slice 2 commit 5 (final): mypalclara router and README updates.

- examples/mypalclara_router.py:
  * New RemoteEpisodeStore class proxies search/get_recent/get_active_arcs
    to PalaceClient.
  * RoutedPalace.episode_store routes to RemoteEpisodeStore when
    USE_PALACE_SERVICE=true; embedded otherwise.
  * RoutedMemoryManager.reflect_on_session and .run_narrative_synthesis
    graduate from one-line embedded delegates to USE_PALACE_SERVICE
    branches that call the client (sync mode for shape parity).
  * All other slice-1 explicit pass-throughs unchanged.

- README.md:
  * "Drop-in mode for mypalclara" header generalized (slice qualifier dropped).
  * New "Slice 2 additions" subsection lists the six new endpoints,
    storage layout, LLM provider, and async-mode caveats.

Slice 2 done. mypalclara can now route 9 of ~18 external callsites to
remote Palace (slice 1: 7; slice 2: episode_store.search/get_recent/
get_active_arcs, MM.reflect_on_session, MM.run_narrative_synthesis).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done criteria — verify before merging

- [ ] All six new endpoints implemented, mock-tested, integration-tested.
- [ ] `palace_client` exposes 6 new methods, all MockTransport-tested.
- [ ] Sync and async modes both work for reflection AND synthesis.
- [ ] `GET /v1/jobs/{id}` returns correct status transitions, 404 on unknown.
- [ ] Integration tests stub the LLM via `stub_llm` fixture — no real LLM calls.
- [ ] Router graduates `episode_store`, `reflect_on_session`, `run_narrative_synthesis` from embedded-only to routed.
- [ ] README has slice 2 subsection.
- [ ] Default `pytest` is green; `pytest -m integration` is green; `cd palace_client && pytest` is green.
- [ ] Branch `phase-2-slice-2-episodes` is ready to merge to `main` via `--no-ff`.

After merge: delete the branch (per the slice-1 precedent).

# Out of scope (slice 3+)

- EntityResolver — phase 3.
- Self-notes extraction — defer.
- Job retry semantics — caller re-POSTs.
- Real worker process (Celery/arq/RQ) — phase 3.
