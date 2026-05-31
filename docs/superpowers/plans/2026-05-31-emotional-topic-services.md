# Emotional Context + Topic Recurrence Services — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two first-class, consumer-facing MyPalace services — emotional context and topic recurrence — that own VADER sentiment/arc scoring and LLM topic extraction + recurrence aggregation server-side, with HTTP routes and `PalaceClient` methods.

**Architecture:** Two Postgres-backed services following the `personality_service`/`episode_service` precedent: SQLModel tables + Alembic migrations, async service classes using `async_session`, LLM via `mypalace.llm`, topic extraction routed through the worker queue (sync arc scoring), consumer-facing `/v1/*` routes returning the `ApiResponse` envelope, and matching async `PalaceClient` methods.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy (async), Alembic, Pydantic v2, httpx, vaderSentiment, pytest + pytest-asyncio. Repo: `/Volumes/Storage/Code/MyPalace`, branch `feat/emotional-topic-services`.

**Scope:** MyPalace service + client only. The mypalclara wiring (client-pin bump + routed branches) is a **separate follow-up plan** — see "Follow-up" at the end.

**Ported source:** `mypalclara/core/memory/context/emotional.py`, `.../context/topics.py`, `mypalclara/core/sentiment.py`.

**Toolchain (verified):** `uv` 0.11.x. The server (repo root) and the client (`mypalace_client/`) are **separate uv projects**. Run server tests from the root after `uv sync --extra dev`; run client tests from inside `mypalace_client/` via `uv run --extra dev pytest`. `mypalace_client` is NOT importable from the server venv.

---

## File Structure

**Create:**
- `mypalace/_sentiment.py` — VADER compound-score helper (mirror of mypalclara's `core/sentiment.py`)
- `mypalace/emotional_service.py` — `EmotionalService` + `compute_emotional_arc`
- `mypalace/topic_service.py` — `TopicService` + topic extraction/validation/pattern helpers
- `mypalace/api/emotional.py` — `/v1/emotional/*` + `/v1/users/{id}/emotional-context`
- `mypalace/api/topics.py` — `/v1/topics/*` + `/v1/users/{id}/topic-recurrence`
- `alembic/versions/2026_05_31_0011_emotional_contexts.py`
- `alembic/versions/2026_05_31_0012_topic_mentions.py`
- Tests: `tests/test_sentiment.py`, `tests/test_emotional_service.py`, `tests/test_emotional_api.py`, `tests/test_topic_service.py`, `tests/test_topics_api.py`, `tests/test_topic_worker.py`, plus client tests under the client package.

**Modify:**
- `mypalace/models.py` — add `EmotionalContext`, `TopicMention`
- `mypalace/tenancy.py` — add `emotional_contexts` + `topic_mentions` to `PER_TENANT_TABLES` (a tripwire test, `test_tenant_schema_lifecycle.py`, fails if any new table is unclassified)
- `mypalace/api/common.py` — add request/response models
- `mypalace/main.py` — register four routers
- `mypalace/workers/handlers.py` — add `topic_extract` handler
- `tests/conftest.py` — add service mocks + patches to the `client` fixture
- `mypalace_client/mypalace_client/client.py` + `models.py` — add 4 methods + 2 models
- `pyproject.toml`, `mypalace_client/pyproject.toml`, `CHANGELOG.md` — dep + version bump

---

### Task 1: Add vaderSentiment dependency + sentiment helper

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `mypalace/_sentiment.py`
- Test: `tests/test_sentiment.py`

- [ ] **Step 0: Ensure the server test env is synced**

Run: `cd /Volumes/Storage/Code/MyPalace && uv sync --extra dev`
Expected: pytest, ruff, etc. installed. (`uv run pytest` fails with "Failed to spawn: pytest" without this.)

- [ ] **Step 1: Add the dependency**

Run: `cd /Volumes/Storage/Code/MyPalace && uv add vaderSentiment`
Expected: `pyproject.toml` gains `vaderSentiment>=3.3` under `[project].dependencies` and `uv.lock` updates.

- [ ] **Step 2: Write the failing test**

Create `tests/test_sentiment.py`:

```python
"""Tests for the VADER compound-score helper."""
from __future__ import annotations

from mypalace._sentiment import compound_score


def test_positive_text_scores_positive():
    assert compound_score("I love this, it's wonderful!") > 0.3


def test_negative_text_scores_negative():
    assert compound_score("This is terrible and I hate it.") < -0.3


def test_empty_text_is_neutral():
    assert compound_score("") == 0.0
    assert compound_score("   ") == 0.0


def test_score_in_range():
    assert -1.0 <= compound_score("meh, okay I guess") <= 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_sentiment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mypalace._sentiment'`

- [ ] **Step 4: Write minimal implementation**

Create `mypalace/_sentiment.py`:

```python
"""VADER sentiment helper — fast rule-based compound scoring.

Mirrors mypalclara/core/sentiment.py. Only the compound score is needed
by the emotional-context service, so the surface is intentionally tiny.
"""
from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def compound_score(text: str) -> float:
    """Return the VADER compound score (-1..+1). Empty text → 0.0."""
    if not text or not text.strip():
        return 0.0
    return _get_analyzer().polarity_scores(text)["compound"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_sentiment.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add pyproject.toml uv.lock mypalace/_sentiment.py tests/test_sentiment.py
git commit -m "feat: add vaderSentiment dep + compound-score helper"
```

---

### Task 2: EmotionalContext model + migration

**Files:**
- Modify: `mypalace/models.py` (add class near `PersonalityTrait`, ~line 348)
- Create: `alembic/versions/2026_05_31_0011_emotional_contexts.py`
- Test: `tests/test_emotional_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_emotional_model.py`:

```python
"""Schema-shape assertions for the EmotionalContext table."""
from __future__ import annotations

from mypalace.models import EmotionalContext


def test_tablename():
    assert EmotionalContext.__tablename__ == "emotional_contexts"


def test_columns_present():
    cols = set(EmotionalContext.__table__.columns.keys())
    assert {
        "id", "tenant_id", "user_id", "agent_id", "channel_id", "channel_name",
        "is_dm", "starting_sentiment", "ending_sentiment", "emotional_arc",
        "energy_level", "topic_summary", "created_at",
    } <= cols


def test_recurrence_index_exists():
    names = {ix.name for ix in EmotionalContext.__table__.indexes}
    assert "ix_emotional_contexts_tenant_user_created" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'EmotionalContext'`

- [ ] **Step 3: Add the model**

In `mypalace/models.py`, after the `EntityAlias` class (ends ~line 347), add:

```python
class EmotionalContext(SQLModel, table=True):
    """Per-conversation emotional summary (arc over a sentiment timeline).

    Source mypalclara/core/memory/context/emotional.py. mypalclara sends the
    finalized conversation; the service scores it with VADER and stores the arc.
    """

    __tablename__ = "emotional_contexts"
    __table_args__ = (
        Index(
            "ix_emotional_contexts_tenant_user_created",
            "tenant_id", "user_id", "created_at",
        ),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, max_length=32)
    user_id: str = Field(index=True)
    agent_id: str = Field(default="default", max_length=64)
    channel_id: str = Field(default="", max_length=200)
    channel_name: str = Field(default="", max_length=200)
    is_dm: bool = Field(default=False)
    starting_sentiment: float = Field(default=0.0)
    ending_sentiment: float = Field(default=0.0)
    emotional_arc: str = Field(default="stable", max_length=20)
    energy_level: str = Field(default="neutral", max_length=50)
    topic_summary: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Create the migration**

Create `alembic/versions/2026_05_31_0011_emotional_contexts.py`:

```python
"""emotional_contexts table — per-conversation emotional summaries.

Source: mypalclara/core/memory/context/emotional.py.

Revision ID: 2026_05_31_0011_emotional_contexts
Revises: 2026_05_05_0010_per_tenant_shadow_copy
Create Date: 2026-05-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_31_0011_emotional_contexts"
down_revision: str | None = "2026_05_05_0010_per_tenant_shadow_copy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emotional_contexts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=200), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("is_dm", sa.Boolean(), nullable=False),
        sa.Column("starting_sentiment", sa.Float(), nullable=False),
        sa.Column("ending_sentiment", sa.Float(), nullable=False),
        sa.Column("emotional_arc", sa.String(length=20), nullable=False),
        sa.Column("energy_level", sa.String(length=50), nullable=False),
        sa.Column("topic_summary", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_emotional_contexts_tenant_user_created",
        "emotional_contexts",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_emotional_contexts_user_id", "emotional_contexts", ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_emotional_contexts_user_id", table_name="emotional_contexts")
    op.drop_index(
        "ix_emotional_contexts_tenant_user_created",
        table_name="emotional_contexts",
    )
    op.drop_table("emotional_contexts")
```

- [ ] **Step 6: Verify the migration chain is linear**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run alembic heads`
Expected: a single head `2026_05_31_0011_emotional_contexts` (no "multiple heads").

- [ ] **Step 7: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/models.py alembic/versions/2026_05_31_0011_emotional_contexts.py tests/test_emotional_model.py
git commit -m "feat: EmotionalContext model + migration"
```

---

### Task 3: EmotionalService (arc scoring + record + get_recent)

**Files:**
- Create: `mypalace/emotional_service.py`
- Test: `tests/test_emotional_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_emotional_service.py`:

```python
"""EmotionalService — pure arc logic + DB-backed record/get_recent (mocked session)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mypalace import emotional_service as em_mod
from mypalace.emotional_service import EmotionalService, compute_emotional_arc


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


class TestComputeArc:
    def test_too_few_messages_is_stable(self):
        assert compute_emotional_arc([0.9, -0.9]) == "stable"

    def test_high_variance_is_volatile(self):
        assert compute_emotional_arc([0.9, -0.9, 0.9, -0.9, 0.9]) == "volatile"

    def test_rising_trend_is_improving(self):
        assert compute_emotional_arc([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]) == "improving"

    def test_falling_trend_is_declining(self):
        assert compute_emotional_arc([0.5, 0.5, 0.5, -0.5, -0.5, -0.5]) == "declining"

    def test_flat_is_stable(self):
        assert compute_emotional_arc([0.1, 0.1, 0.1, 0.1]) == "stable"


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_computes_arc_and_persists(self, monkeypatch):
        svc = EmotionalService()
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        row = await svc.record(
            user_id="u1",
            messages=["I'm so frustrated", "still annoyed", "ok", "feeling better", "great now", "wonderful"],
            energy="focused", summary="job search", channel_name="#dm", is_dm=True,
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert row.user_id == "u1"
        assert row.emotional_arc in {"stable", "improving", "declining", "volatile"}
        assert row.energy_level == "focused"
        assert row.topic_summary == "job search"

    @pytest.mark.asyncio
    async def test_record_with_no_messages_defaults_zero(self, monkeypatch):
        svc = EmotionalService()
        db = MagicMock(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))
        row = await svc.record(user_id="u1", messages=[])
        assert row.starting_sentiment == 0.0
        assert row.ending_sentiment == 0.0
        assert row.emotional_arc == "stable"


class TestGetRecent:
    @pytest.mark.asyncio
    async def test_get_recent_queries_and_returns_rows(self, monkeypatch):
        svc = EmotionalService()
        now = datetime(2026, 5, 31, tzinfo=UTC)
        sentinel = ["row-a", "row-b"]
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=sentinel)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        out = await svc.get_recent(user_id="u1", limit=2, max_age_days=7)
        assert out == sentinel
        db.execute.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mypalace.emotional_service'`

- [ ] **Step 3: Write the implementation**

Create `mypalace/emotional_service.py`:

```python
"""Emotional-context service — VADER arc scoring + storage.

Source: mypalclara/core/memory/context/emotional.py. The service scores a
finalized conversation server-side and stores one EmotionalContext row.
"""
from __future__ import annotations

import logging
import statistics
from datetime import timedelta

from sqlalchemy import select

from mypalace._sentiment import compound_score
from mypalace.database import async_session
from mypalace.models import DEFAULT_TENANT_ID, EmotionalContext, utcnow

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"
MIN_MESSAGES_FOR_ARC = 3


def compute_emotional_arc(timeline: list[float]) -> str:
    """Classify a sentiment trajectory. Ported verbatim from mypalclara."""
    if len(timeline) < MIN_MESSAGES_FOR_ARC:
        return "stable"
    start_avg = sum(timeline[:3]) / 3
    end_avg = sum(timeline[-3:]) / 3
    variance = statistics.variance(timeline) if len(timeline) > 1 else 0
    if variance > 0.3:
        return "volatile"
    if end_avg - start_avg > 0.2:
        return "improving"
    if start_avg - end_avg > 0.2:
        return "declining"
    return "stable"


class EmotionalService:
    """Server-side scoring + storage for per-conversation emotional context."""

    async def record(
        self,
        *,
        user_id: str,
        messages: list[str],
        agent_id: str = DEFAULT_AGENT_ID,
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
        energy: str = "neutral",
        summary: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> EmotionalContext:
        timeline = [compound_score(m) for m in messages if m and m.strip()]
        arc = compute_emotional_arc(timeline)
        starting = timeline[0] if timeline else 0.0
        ending = timeline[-1] if timeline else 0.0
        row = EmotionalContext(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            channel_id=channel_id,
            channel_name=channel_name,
            is_dm=is_dm,
            starting_sentiment=starting,
            ending_sentiment=ending,
            emotional_arc=arc,
            energy_level=energy,
            topic_summary=summary,
            created_at=utcnow(),
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
            await db.refresh(row)
        logger.info(
            "emotional context recorded tenant=%s user=%s arc=%s energy=%s",
            tenant_id, user_id, arc, energy,
        )
        return row

    async def get_recent(
        self,
        *,
        user_id: str,
        agent_id: str = DEFAULT_AGENT_ID,
        limit: int = 3,
        max_age_days: int = 7,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[EmotionalContext]:
        cutoff = utcnow() - timedelta(days=max_age_days)
        async with async_session() as db:
            result = await db.execute(
                select(EmotionalContext)
                .where(EmotionalContext.tenant_id == tenant_id)
                .where(EmotionalContext.user_id == user_id)
                .where(EmotionalContext.agent_id == agent_id)
                .where(EmotionalContext.created_at >= cutoff)
                .order_by(EmotionalContext.created_at.desc())
                .limit(limit),
            )
            return list(result.scalars().all())


emotional_service = EmotionalService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_service.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/emotional_service.py tests/test_emotional_service.py
git commit -m "feat: EmotionalService — arc scoring + record/get_recent"
```

---

### Task 4: Emotional API routes + registration + conftest mocks

**Files:**
- Modify: `mypalace/api/common.py` (add models at end of each section)
- Create: `mypalace/api/emotional.py`
- Modify: `mypalace/main.py` (register routers, after the vch line ~198)
- Modify: `tests/conftest.py` (add fixture + patches)
- Test: `tests/test_emotional_api.py`

- [ ] **Step 1: Add request/response models to `api/common.py`**

In the "Request models" section of `mypalace/api/common.py`, add:

```python
class RecordEmotionalRequest(BaseModel):
    user_id: str
    messages: list[str] = Field(default_factory=list)
    agent_id: str = "default"
    channel_id: str = ""
    channel_name: str = ""
    is_dm: bool = False
    energy: str = "neutral"
    summary: str = ""
```

In the "Response models" section, add:

```python
class EmotionalContextOut(BaseModel):
    id: str
    user_id: str
    agent_id: str
    channel_id: str
    channel_name: str
    is_dm: bool
    starting_sentiment: float
    ending_sentiment: float
    emotional_arc: str
    energy_level: str
    topic_summary: str
    created_at: str | None

    @classmethod
    def from_row(cls, r: Any) -> "EmotionalContextOut":
        return cls(
            id=r.id,
            user_id=r.user_id,
            agent_id=r.agent_id,
            channel_id=r.channel_id,
            channel_name=r.channel_name,
            is_dm=r.is_dm,
            starting_sentiment=r.starting_sentiment,
            ending_sentiment=r.ending_sentiment,
            emotional_arc=r.emotional_arc,
            energy_level=r.energy_level,
            topic_summary=r.topic_summary,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_emotional_api.py`:

```python
"""Contract tests for /v1/emotional routes (service mocked via conftest)."""
from __future__ import annotations

from datetime import UTC, datetime

from mypalace.models import EmotionalContext


def test_record_returns_200_and_calls_service(client, mock_emotional_service):
    mock_emotional_service.record.return_value = EmotionalContext(
        id="ec1", tenant_id="test", user_id="u1", agent_id="default",
        channel_id="", channel_name="#dm", is_dm=True,
        starting_sentiment=-0.4, ending_sentiment=0.5, emotional_arc="improving",
        energy_level="focused", topic_summary="job search",
        created_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    resp = client.post("/v1/emotional/record", json={
        "user_id": "u1", "messages": ["bad", "ok", "good"],
        "energy": "focused", "summary": "job search", "is_dm": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["emotional_arc"] == "improving"
    mock_emotional_service.record.assert_awaited_once()


def test_get_emotional_context_returns_list(client, mock_emotional_service):
    mock_emotional_service.get_recent.return_value = []
    resp = client.get("/v1/users/u1/emotional-context", params={"limit": 3, "max_age_days": 7})
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    mock_emotional_service.get_recent.assert_awaited_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_api.py -v`
Expected: FAIL — `fixture 'mock_emotional_service' not found` (and the route doesn't exist yet)

- [ ] **Step 4: Create the API module**

Create `mypalace/api/emotional.py`:

```python
"""Emotional-context routes — record (sync) + per-user recent fetch."""
from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mypalace.api.common import (
    ApiResponse,
    EmotionalContextOut,
    Meta,
    RecordEmotionalRequest,
)
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.emotional_service import DEFAULT_AGENT_ID, emotional_service

router = APIRouter()         # /v1/emotional/...
users_router = APIRouter()   # /v1/users/{user_id}/emotional-context


@router.post("/record", response_model=ApiResponse[EmotionalContextOut])
async def record_emotional(
    req: RecordEmotionalRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    row = await emotional_service.record(
        user_id=req.user_id,
        messages=req.messages,
        agent_id=req.agent_id,
        channel_id=req.channel_id,
        channel_name=req.channel_name,
        is_dm=req.is_dm,
        energy=req.energy,
        summary=req.summary,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(data=EmotionalContextOut.from_row(row), meta=Meta(count=1, took_ms=took))


@users_router.get(
    "/{user_id}/emotional-context",
    response_model=ApiResponse[list[EmotionalContextOut]],
)
async def emotional_context(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 3,
    max_age_days: int = 7,
    agent_id: str = DEFAULT_AGENT_ID,
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    rows = await emotional_service.get_recent(
        user_id=user_id, agent_id=agent_id,
        limit=limit, max_age_days=max_age_days, tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EmotionalContextOut.from_row(r) for r in rows],
        meta=Meta(count=len(rows), took_ms=took),
    )
```

- [ ] **Step 5: Register the routers in `main.py`**

In `mypalace/main.py`, immediately after the line `app.include_router(vch.router, prefix="/v1/context", tags=["retrieval"])` (~line 198), add:

```python
    app.include_router(emotional.router, prefix="/v1/emotional", tags=["emotional"])
    app.include_router(emotional.users_router, prefix="/v1/users", tags=["emotional"])
```

And add `emotional` to the `from mypalace.api import (...)` import block at the top of `main.py` (alongside `vch`, `episodes`, etc.).

- [ ] **Step 6: Add the conftest fixture + patch**

In `tests/conftest.py`, add a fixture after `mock_intention_service` (~line 150):

```python
@pytest.fixture
def mock_emotional_service():
    mock = MagicMock()
    mock.record = AsyncMock()
    mock.get_recent = AsyncMock(return_value=[])
    return mock
```

Add `mock_emotional_service` to the `client` fixture's parameter list, and add these two patches to the `patches = [...]` list:

```python
        patch("mypalace.api.emotional.emotional_service", mock_emotional_service),
        patch("mypalace.emotional_service.emotional_service", mock_emotional_service),
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_emotional_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/api/common.py mypalace/api/emotional.py mypalace/main.py tests/conftest.py tests/test_emotional_api.py
git commit -m "feat: /v1/emotional routes + record/get_recent endpoints"
```

---

### Task 5: Emotional client methods + model

**Files:**
- Modify: `mypalace_client/mypalace_client/models.py` (add `EmotionalContext`)
- Modify: `mypalace_client/mypalace_client/client.py` (add 2 methods + import)
- Test: `mypalace_client/tests/test_client_emotional.py`

- [ ] **Step 1: Write the failing test**

Create `mypalace_client/tests/test_client_emotional.py`:

```python
"""Client tests for emotional-context endpoints using an httpx MockTransport."""
from __future__ import annotations

import json

import httpx
import pytest

from mypalace_client import PalaceClient
from mypalace_client.models import EmotionalContext


def _client(handler) -> PalaceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://palace.test")
    return PalaceClient(base_url="http://palace.test", api_key="k", client=http)


@pytest.mark.asyncio
async def test_record_emotional_context():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {
            "id": "ec1", "user_id": "u1", "agent_id": "default",
            "channel_id": "", "channel_name": "#dm", "is_dm": True,
            "starting_sentiment": -0.4, "ending_sentiment": 0.5,
            "emotional_arc": "improving", "energy_level": "focused",
            "topic_summary": "job search", "created_at": "2026-05-31T00:00:00+00:00",
        }, "meta": {"count": 1}})

    pc = _client(handler)
    out = await pc.record_emotional_context(
        user_id="u1", messages=["bad", "ok", "good"], energy="focused", summary="job search", is_dm=True,
    )
    assert isinstance(out, EmotionalContext)
    assert out.emotional_arc == "improving"
    assert captured["path"] == "/v1/emotional/record"
    assert captured["body"]["messages"] == ["bad", "ok", "good"]


@pytest.mark.asyncio
async def test_get_emotional_context():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/emotional-context"
        return httpx.Response(200, json={"data": [], "meta": {"count": 0}})

    pc = _client(handler)
    out = await pc.get_emotional_context(user_id="u1", limit=3, max_age_days=7)
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace/mypalace_client && uv run --extra dev pytest tests/test_client_emotional.py -v`
Expected: FAIL — `ImportError: cannot import name 'EmotionalContext'` from `mypalace_client.models`

- [ ] **Step 3: Add the client model**

In `mypalace_client/mypalace_client/models.py`, add:

```python
class EmotionalContext(BaseModel):
    id: str
    user_id: str
    agent_id: str
    channel_id: str
    channel_name: str
    is_dm: bool
    starting_sentiment: float
    ending_sentiment: float
    emotional_arc: str
    energy_level: str
    topic_summary: str
    created_at: datetime | None = None
```

(If `datetime` is not already imported in that file, add `from datetime import datetime` at the top.)

- [ ] **Step 4: Add the client methods**

In `mypalace_client/mypalace_client/client.py`, add `EmotionalContext` to the models import line, then add a section after `get_recent_episodes` (~line 350):

```python
    # ---- emotional context ----

    async def record_emotional_context(
        self,
        user_id: str,
        messages: list[str],
        agent_id: str = "default",
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
        energy: str = "neutral",
        summary: str = "",
    ) -> EmotionalContext:
        body = {
            "user_id": user_id,
            "messages": messages,
            "agent_id": agent_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "is_dm": is_dm,
            "energy": energy,
            "summary": summary,
        }
        envelope = await self._request("POST", "/v1/emotional/record", json=body)
        return EmotionalContext.model_validate(self._data(envelope))

    async def get_emotional_context(
        self, user_id: str, limit: int = 3, max_age_days: int = 7,
        agent_id: str = "default",
    ) -> list[EmotionalContext]:
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/emotional-context",
            params={"limit": limit, "max_age_days": max_age_days, "agent_id": agent_id},
        )
        return [EmotionalContext.model_validate(e) for e in self._data(envelope) or []]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace/mypalace_client && uv run --extra dev pytest tests/test_client_emotional.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace_client/mypalace_client/models.py mypalace_client/mypalace_client/client.py mypalace_client/tests/test_client_emotional.py
git commit -m "feat(client): record_emotional_context + get_emotional_context"
```

---

### Task 6: TopicMention model + migration

**Files:**
- Modify: `mypalace/models.py`
- Create: `alembic/versions/2026_05_31_0012_topic_mentions.py`
- Test: `tests/test_topic_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_topic_model.py`:

```python
"""Schema-shape assertions for the TopicMention table."""
from __future__ import annotations

from mypalace.models import TopicMention


def test_tablename():
    assert TopicMention.__tablename__ == "topic_mentions"


def test_columns_present():
    cols = set(TopicMention.__table__.columns.keys())
    assert {
        "id", "tenant_id", "user_id", "agent_id", "topic", "topic_type",
        "context_snippet", "emotional_weight", "sentiment", "channel_id",
        "channel_name", "is_dm", "created_at",
    } <= cols


def test_recurrence_index_exists():
    names = {ix.name for ix in TopicMention.__table__.indexes}
    assert "ix_topic_mentions_tenant_user_topic_created" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'TopicMention'`

- [ ] **Step 3: Add the model**

In `mypalace/models.py`, after `EmotionalContext`, add:

```python
class TopicMention(SQLModel, table=True):
    """A single topic mention extracted from a conversation.

    Source mypalclara/core/memory/context/topics.py. Recurrence patterns are
    computed server-side by aggregating these rows over a lookback window.
    """

    __tablename__ = "topic_mentions"
    __table_args__ = (
        Index(
            "ix_topic_mentions_tenant_user_topic_created",
            "tenant_id", "user_id", "topic", "created_at",
        ),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, max_length=32)
    user_id: str = Field(index=True)
    agent_id: str = Field(default="default", max_length=64)
    topic: str = Field(max_length=200)
    topic_type: str = Field(default="theme", max_length=20)
    context_snippet: str = Field(default="", max_length=200)
    emotional_weight: str = Field(default="moderate", max_length=20)
    sentiment: float = Field(default=0.0)
    channel_id: str = Field(default="", max_length=200)
    channel_name: str = Field(default="", max_length=200)
    is_dm: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Create the migration**

Create `alembic/versions/2026_05_31_0012_topic_mentions.py`:

```python
"""topic_mentions table — extracted topic mentions for recurrence tracking.

Source: mypalclara/core/memory/context/topics.py.

Revision ID: 2026_05_31_0012_topic_mentions
Revises: 2026_05_31_0011_emotional_contexts
Create Date: 2026-05-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_31_0012_topic_mentions"
down_revision: str | None = "2026_05_31_0011_emotional_contexts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topic_mentions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("topic_type", sa.String(length=20), nullable=False),
        sa.Column("context_snippet", sa.String(length=200), nullable=False),
        sa.Column("emotional_weight", sa.String(length=20), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=False),
        sa.Column("channel_id", sa.String(length=200), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("is_dm", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topic_mentions_tenant_user_topic_created",
        "topic_mentions",
        ["tenant_id", "user_id", "topic", "created_at"],
    )
    op.create_index("ix_topic_mentions_user_id", "topic_mentions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_topic_mentions_user_id", table_name="topic_mentions")
    op.drop_index(
        "ix_topic_mentions_tenant_user_topic_created", table_name="topic_mentions",
    )
    op.drop_table("topic_mentions")
```

- [ ] **Step 6: Verify single head**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run alembic heads`
Expected: single head `2026_05_31_0012_topic_mentions`.

- [ ] **Step 7: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/models.py alembic/versions/2026_05_31_0012_topic_mentions.py tests/test_topic_model.py
git commit -m "feat: TopicMention model + migration"
```

---

### Task 7: TopicService (extraction helpers + extract_and_store + get_recurrence)

**Files:**
- Create: `mypalace/topic_service.py`
- Test: `tests/test_topic_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_topic_service.py`:

```python
"""TopicService — pure helpers + DB/LLM-mocked extract/recurrence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace import topic_service as tp_mod
from mypalace.models import TopicMention
from mypalace.topic_service import (
    TopicService,
    _dedupe_topics,
    _parse_llm_json,
    _validate_topics,
    compute_topic_pattern,
)


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _mention(topic, sentiment, weight, when):
    return TopicMention(
        id=f"id-{when.isoformat()}", tenant_id="test", user_id="u1", agent_id="default",
        topic=topic, topic_type="theme", context_snippet="", emotional_weight=weight,
        sentiment=sentiment, channel_id="", channel_name="#dm", is_dm=True, created_at=when,
    )


class TestValidate:
    def test_drops_invalid_and_normalizes(self):
        raw = [
            {"topic": "Job Search", "topic_type": "bogus", "emotional_weight": "x"},
            {"topic": "", "topic_type": "theme"},
        ]
        out = _validate_topics(raw)
        assert out == [{
            "topic": "job search", "topic_type": "theme",
            "context_snippet": "", "emotional_weight": "moderate",
        }]


class TestDedupe:
    def test_keeps_heaviest_weight(self):
        out = _dedupe_topics([
            {"topic": "mom", "topic_type": "entity", "context_snippet": "", "emotional_weight": "light"},
            {"topic": "mom", "topic_type": "entity", "context_snippet": "", "emotional_weight": "heavy"},
        ])
        assert len(out) == 1
        assert out[0]["emotional_weight"] == "heavy"


class TestPattern:
    def test_declining_and_recurring(self):
        p = compute_topic_pattern([
            {"sentiment": 0.5, "emotional_weight": "moderate"},
            {"sentiment": 0.0, "emotional_weight": "moderate"},
            {"sentiment": -0.5, "emotional_weight": "heavy"},
        ])
        assert p["mention_count"] == 3
        assert p["sentiment_trend"] == "declining"
        assert "getting heavier" in p["pattern_note"] or "recurring" in p["pattern_note"]


class TestExtractAndStore:
    @pytest.mark.asyncio
    async def test_short_text_skips_llm(self):
        svc = TopicService()
        assert await svc.extract_and_store(user_id="u1", conversation_text="hi") == []

    @pytest.mark.asyncio
    async def test_extracts_dedupes_and_persists(self, monkeypatch):
        svc = TopicService()
        db = MagicMock(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(db)))
        llm_json = '{"topics": [{"topic": "Job Search", "topic_type": "theme", "context_snippet": "interviews", "emotional_weight": "heavy"}]}'
        with patch.object(tp_mod.llm, "complete", new=AsyncMock(return_value=llm_json)):
            rows = await svc.extract_and_store(
                user_id="u1",
                conversation_text="we talked at length about the job search and interviews not going well " * 2,
                conversation_sentiment=-0.3,
            )
        assert len(rows) == 1
        assert rows[0].topic == "job search"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, monkeypatch):
        svc = TopicService()
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(MagicMock())))
        with patch.object(tp_mod.llm, "complete", new=AsyncMock(side_effect=RuntimeError("boom"))):
            assert await svc.extract_and_store(
                user_id="u1", conversation_text="x" * 60,
            ) == []


class TestRecurrence:
    @pytest.mark.asyncio
    async def test_groups_and_filters_min_mentions(self, monkeypatch):
        svc = TopicService()
        now = datetime(2026, 5, 31, tzinfo=UTC)
        rows = [
            _mention("job search", -0.2, "heavy", now - timedelta(days=2)),
            _mention("job search", -0.5, "heavy", now - timedelta(days=1)),
            _mention("weather", 0.1, "light", now - timedelta(days=1)),
        ]
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db = MagicMock(execute=AsyncMock(return_value=result))
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        out = await svc.get_recurrence(user_id="u1", min_mentions=2)
        assert len(out) == 1
        assert out[0]["topic"] == "job search"
        assert out[0]["mention_count"] == 2


class TestParseLlmJson:
    def test_plain_and_fenced(self):
        assert _parse_llm_json('{"a": 1}') == {"a": 1}
        assert _parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_garbage_is_none(self):
        assert _parse_llm_json("not json") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mypalace.topic_service'`

- [ ] **Step 3: Write the implementation**

Create `mypalace/topic_service.py`:

```python
"""Topic-recurrence service — LLM topic extraction + recurrence aggregation.

Source: mypalclara/core/memory/context/topics.py. Topic extraction is an LLM
call run via the worker queue; recurrence patterns are computed server-side by
aggregating TopicMention rows over a lookback window.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from mypalace.database import async_session
from mypalace.llm import llm
from mypalace.models import DEFAULT_TENANT_ID, TopicMention, utcnow

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"
_WEIGHT_ORDER = {"light": 1, "moderate": 2, "heavy": 3}
_VALID_WEIGHTS = {"light", "moderate", "heavy"}
_VALID_TYPES = {"entity", "theme"}

TOPIC_EXTRACTION_PROMPT = """Extract key topics from this conversation that might recur in future conversations.

**The conversation:**
{conversation}

**Conversation sentiment:** {sentiment:.2f} (scale: -1 negative to +1 positive)

**What to extract:**
For each topic, provide:
- topic: Normalized name using consistent, lowercase, singular forms. Prefer common phrasing (e.g., "job search" not "employment hunt" or "the job hunt", "mom" not "my mother")
- topic_type: "entity" (person, place, project, company) or "theme" (ongoing concern, interest, goal)
- context_snippet: Brief summary of how it came up (10-20 words)
- emotional_weight: "light" (casual mention), "moderate" (some feeling), "heavy" (significant emotion)

**Rules:**
1. Only extract topics with emotional significance OR specific enough to recur
2. Skip generic topics like "work", "life", "stuff", "things"
3. Use consistent normalization - same topic should always have the same name
4. Max 3 unique topics per conversation

**Respond in JSON:**
{{
    "topics": [
        {{
            "topic": "job search",
            "topic_type": "theme",
            "context_snippet": "frustrated about not hearing back from interviews",
            "emotional_weight": "heavy"
        }}
    ]
}}

If no significant topics, return: {{"topics": []}}"""


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Fall back to the first {...} block (the prompt may add prose).
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("topic LLM non-JSON response: %.200s", text)
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_topics(raw_topics: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in raw_topics:
        name = (t.get("topic", "") or "").strip().lower()
        if not name or len(name) < 2:
            continue
        topic_type = t.get("topic_type", "theme")
        if topic_type not in _VALID_TYPES:
            topic_type = "theme"
        weight = t.get("emotional_weight", "moderate")
        if weight not in _VALID_WEIGHTS:
            weight = "moderate"
        out.append({
            "topic": name,
            "topic_type": topic_type,
            "context_snippet": (t.get("context_snippet", "") or "")[:100],
            "emotional_weight": weight,
        })
    return out


def _dedupe_topics(topics: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in topics:
        name = t["topic"]
        if name not in seen:
            seen[name] = t
            continue
        if _WEIGHT_ORDER.get(t["emotional_weight"], 0) > _WEIGHT_ORDER.get(
            seen[name]["emotional_weight"], 0,
        ):
            seen[name] = t
    return list(seen.values())


def compute_topic_pattern(mentions: list[dict]) -> dict:
    """Analyze recurrence for one topic's mentions. Ported from mypalclara."""
    if not mentions:
        return {"mention_count": 0, "sentiment_trend": "stable",
                "avg_emotional_weight": "light", "pattern_note": ""}
    count = len(mentions)
    sentiments = [m.get("sentiment", 0.0) for m in mentions]
    if len(sentiments) >= 2 and sentiments[-1] - sentiments[0] < -0.2:
        trend = "declining"
    elif len(sentiments) >= 2 and sentiments[-1] - sentiments[0] > 0.2:
        trend = "improving"
    else:
        trend = "stable"
    weight_scores = [_WEIGHT_ORDER.get(m.get("emotional_weight", "moderate"), 2) for m in mentions]
    avg = sum(weight_scores) / len(weight_scores)
    avg_weight = "heavy" if avg >= 2.5 else "moderate" if avg >= 1.5 else "light"
    weight_increasing = len(weight_scores) >= 2 and weight_scores[-1] > weight_scores[0]
    if count >= 3 and (trend == "declining" or weight_increasing):
        note = f"brought up {count} times, getting heavier"
    elif count >= 3 and avg_weight == "heavy":
        note = f"recurring concern ({count} mentions)"
    elif count >= 2:
        note = f"mentioned {count} times recently"
    else:
        note = "mentioned recently"
    return {"mention_count": count, "sentiment_trend": trend,
            "avg_emotional_weight": avg_weight, "pattern_note": note}


def _format_relative_time(ts: datetime | None) -> str:
    if ts is None:
        return ""
    delta = utcnow() - ts
    if delta.days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            minutes = delta.seconds // 60
            return f"{minutes}m ago" if minutes > 0 else "just now"
        return f"{hours}h ago"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    weeks = delta.days // 7
    return f"{weeks} week{'s' if weeks > 1 else ''} ago"


class TopicService:
    async def extract_and_store(
        self,
        *,
        user_id: str,
        conversation_text: str,
        conversation_sentiment: float = 0.0,
        agent_id: str = DEFAULT_AGENT_ID,
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[TopicMention]:
        if not conversation_text or len(conversation_text.strip()) < 50:
            return []
        prompt = TOPIC_EXTRACTION_PROMPT.format(
            conversation=conversation_text[:4000], sentiment=conversation_sentiment,
        )
        try:
            raw = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=500,
            )
        except Exception:
            logger.exception("topic extraction LLM call failed")
            return []
        data = _parse_llm_json(raw) or {}
        topics = _dedupe_topics(_validate_topics(data.get("topics", [])))[:3]
        if not topics:
            return []
        now = utcnow()
        rows = [
            TopicMention(
                tenant_id=tenant_id, user_id=user_id, agent_id=agent_id,
                topic=t["topic"], topic_type=t["topic_type"],
                context_snippet=t["context_snippet"], emotional_weight=t["emotional_weight"],
                sentiment=conversation_sentiment, channel_id=channel_id,
                channel_name=channel_name, is_dm=is_dm, created_at=now,
            )
            for t in topics
        ]
        async with async_session() as db:
            for row in rows:
                db.add(row)
            await db.commit()
            for row in rows:
                await db.refresh(row)
        logger.info("topic mentions stored tenant=%s user=%s count=%d", tenant_id, user_id, len(rows))
        return rows

    async def get_recurrence(
        self,
        *,
        user_id: str,
        agent_id: str = DEFAULT_AGENT_ID,
        lookback_days: int = 14,
        min_mentions: int = 2,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        cutoff = utcnow() - timedelta(days=lookback_days)
        async with async_session() as db:
            result = await db.execute(
                select(TopicMention)
                .where(TopicMention.tenant_id == tenant_id)
                .where(TopicMention.user_id == user_id)
                .where(TopicMention.agent_id == agent_id)
                .where(TopicMention.created_at >= cutoff)
                .order_by(TopicMention.created_at),
            )
            rows = list(result.scalars().all())

        groups: dict[str, list[TopicMention]] = defaultdict(list)
        for r in rows:
            groups[r.topic].append(r)

        recurring: list[dict] = []
        for topic, items in groups.items():
            if len(items) < min_mentions:
                continue
            items.sort(key=lambda x: x.created_at)
            mention_dicts = [
                {"sentiment": i.sentiment, "emotional_weight": i.emotional_weight}
                for i in items
            ]
            pattern = compute_topic_pattern(mention_dicts)
            types = [i.topic_type for i in items]
            channels = sorted({i.channel_name for i in items if i.channel_name})
            recurring.append({
                "topic": topic,
                "topic_type": max(set(types), key=types.count),
                "mention_count": pattern["mention_count"],
                "first_mentioned": _format_relative_time(items[0].created_at),
                "last_mentioned": _format_relative_time(items[-1].created_at),
                "sentiment_trend": pattern["sentiment_trend"],
                "avg_emotional_weight": pattern["avg_emotional_weight"],
                "pattern_note": pattern["pattern_note"],
                "channels": channels,
            })
        recurring.sort(key=lambda x: x["mention_count"], reverse=True)
        return recurring


topic_service = TopicService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_service.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/topic_service.py tests/test_topic_service.py
git commit -m "feat: TopicService — extraction + recurrence aggregation"
```

---

### Task 8: Topic worker handler

**Files:**
- Modify: `mypalace/workers/handlers.py`
- Test: `tests/test_topic_worker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_topic_worker.py`:

```python
"""The topic_extract worker handler dispatches to TopicService."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mypalace.workers.handlers import HANDLER_REGISTRY


@pytest.mark.asyncio
async def test_topic_extract_handler_registered_and_dispatches():
    assert "topic_extract" in HANDLER_REGISTRY
    handler = HANDLER_REGISTRY["topic_extract"]
    with patch("mypalace.topic_service.topic_service.extract_and_store",
               new=AsyncMock(return_value=[])) as m:
        await handler(
            {"user_id": "u1", "conversation_text": "x" * 60, "conversation_sentiment": -0.2,
             "agent_id": "default", "channel_id": "", "channel_name": "#dm", "is_dm": True},
            "test",
        )
    m.assert_awaited_once()
    assert m.call_args.kwargs["user_id"] == "u1"
    assert m.call_args.kwargs["tenant_id"] == "test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_worker.py -v`
Expected: FAIL — `assert 'topic_extract' in HANDLER_REGISTRY`

- [ ] **Step 3: Add the handler**

In `mypalace/workers/handlers.py`, add after `_personality_evolve_handler` (~line 155):

```python
async def _topic_extract_handler(payload: dict, tenant_id: str) -> Any:
    """LLM topic extraction + storage from a serialized payload."""
    from mypalace.topic_service import DEFAULT_AGENT_ID, topic_service
    rows = await topic_service.extract_and_store(
        user_id=payload["user_id"],
        conversation_text=payload["conversation_text"],
        conversation_sentiment=payload.get("conversation_sentiment", 0.0),
        agent_id=payload.get("agent_id", DEFAULT_AGENT_ID),
        channel_id=payload.get("channel_id", ""),
        channel_name=payload.get("channel_name", ""),
        is_dm=payload.get("is_dm", False),
        tenant_id=tenant_id,
    )
    return {"stored": len(rows), "topics": [r.topic for r in rows]}
```

And add to the registration block at the bottom:

```python
register_handler("topic_extract", _topic_extract_handler)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topic_worker.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/workers/handlers.py tests/test_topic_worker.py
git commit -m "feat: topic_extract worker handler"
```

---

### Task 9: Topic API routes + registration + conftest mocks

**Files:**
- Modify: `mypalace/api/common.py`
- Create: `mypalace/api/topics.py`
- Modify: `mypalace/main.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_topics_api.py`

- [ ] **Step 1: Add request/response models to `api/common.py`**

Add to the request section:

```python
class ExtractTopicsRequest(BaseModel):
    user_id: str
    conversation_text: str
    conversation_sentiment: float = 0.0
    agent_id: str = "default"
    channel_id: str = ""
    channel_name: str = ""
    is_dm: bool = False
```

Add to the response section:

```python
class TopicRecurrenceOut(BaseModel):
    topic: str
    topic_type: str
    mention_count: int
    first_mentioned: str
    last_mentioned: str
    sentiment_trend: str
    avg_emotional_weight: str
    pattern_note: str
    channels: list[str]
```

(`JobPendingOut` already exists in `common.py` — reuse it for the async response.)

- [ ] **Step 2: Write the failing test**

Create `tests/test_topics_api.py`:

```python
"""Contract tests for /v1/topics routes (service + job mocked via conftest)."""
from __future__ import annotations


def test_extract_returns_202_with_job(client, mock_job_service):
    job = type("J", (), {"id": "job-1"})()
    mock_job_service.run_async.return_value = job
    resp = client.post("/v1/topics/extract", json={
        "user_id": "u1", "conversation_text": "x" * 60, "conversation_sentiment": -0.2,
    })
    assert resp.status_code == 202
    assert resp.json()["data"]["job_id"] == "job-1"


def test_topic_recurrence_returns_list(client, mock_topic_service):
    mock_topic_service.get_recurrence.return_value = [{
        "topic": "job search", "topic_type": "theme", "mention_count": 3,
        "first_mentioned": "3 days ago", "last_mentioned": "yesterday",
        "sentiment_trend": "declining", "avg_emotional_weight": "heavy",
        "pattern_note": "recurring concern (3 mentions)", "channels": ["#dm"],
    }]
    resp = client.get("/v1/users/u1/topic-recurrence", params={"lookback_days": 14, "min_mentions": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["topic"] == "job search"
    mock_topic_service.get_recurrence.assert_awaited_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topics_api.py -v`
Expected: FAIL — `fixture 'mock_topic_service' not found` / route missing.

- [ ] **Step 4: Create the API module**

Create `mypalace/api/topics.py`:

```python
"""Topic routes — async extraction (worker) + per-user recurrence fetch."""
from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from mypalace.api.common import (
    ApiResponse,
    ExtractTopicsRequest,
    JobPendingOut,
    Meta,
    TopicRecurrenceOut,
)
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.config import settings
from mypalace.job_service import job_service
from mypalace.topic_service import DEFAULT_AGENT_ID, topic_service
from mypalace.workers.queue import enqueue as enqueue_job

router = APIRouter()         # /v1/topics/...
users_router = APIRouter()   # /v1/users/{user_id}/topic-recurrence


@router.post("/extract")
async def extract_topics(
    req: ExtractTopicsRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    payload = {
        "user_id": req.user_id,
        "conversation_text": req.conversation_text,
        "conversation_sentiment": req.conversation_sentiment,
        "agent_id": req.agent_id,
        "channel_id": req.channel_id,
        "channel_name": req.channel_name,
        "is_dm": req.is_dm,
    }
    if settings.worker_queue_enabled:
        job = await enqueue_job(
            kind="topic_extract", user_id=req.user_id, payload=payload, tenant_id=tenant_id,
        )
    else:
        async def coro():
            return await topic_service.extract_and_store(
                user_id=req.user_id,
                conversation_text=req.conversation_text,
                conversation_sentiment=req.conversation_sentiment,
                agent_id=req.agent_id,
                channel_id=req.channel_id,
                channel_name=req.channel_name,
                is_dm=req.is_dm,
                tenant_id=tenant_id,
            )

        job = await job_service.run_async(
            kind="topic_extract", user_id=req.user_id, coro_factory=coro, tenant_id=tenant_id,
        )
    took = int((time.time() - start) * 1000)
    response = ApiResponse(data=JobPendingOut(job_id=job.id), meta=Meta(count=1, took_ms=took))
    return JSONResponse(content=response.model_dump(), status_code=202)


@users_router.get(
    "/{user_id}/topic-recurrence",
    response_model=ApiResponse[list[TopicRecurrenceOut]],
)
async def topic_recurrence(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    lookback_days: int = 14,
    min_mentions: int = 2,
    agent_id: str = DEFAULT_AGENT_ID,
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    items = await topic_service.get_recurrence(
        user_id=user_id, agent_id=agent_id,
        lookback_days=lookback_days, min_mentions=min_mentions, tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[TopicRecurrenceOut(**i) for i in items],
        meta=Meta(count=len(items), took_ms=took),
    )
```

- [ ] **Step 5: Register routers in `main.py`**

After the emotional routers added in Task 4, add:

```python
    app.include_router(topics.router, prefix="/v1/topics", tags=["topics"])
    app.include_router(topics.users_router, prefix="/v1/users", tags=["topics"])
```

Add `topics` to the `from mypalace.api import (...)` import block.

- [ ] **Step 6: Add conftest fixture + patches**

In `tests/conftest.py`, add:

```python
@pytest.fixture
def mock_topic_service():
    mock = MagicMock()
    mock.extract_and_store = AsyncMock(return_value=[])
    mock.get_recurrence = AsyncMock(return_value=[])
    return mock
```

Add `mock_topic_service` to the `client` fixture params, and add to `patches`:

```python
        patch("mypalace.api.topics.topic_service", mock_topic_service),
        patch("mypalace.api.topics.job_service", mock_job_service),
        patch("mypalace.topic_service.topic_service", mock_topic_service),
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/test_topics_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace/api/common.py mypalace/api/topics.py mypalace/main.py tests/conftest.py tests/test_topics_api.py
git commit -m "feat: /v1/topics routes — async extract + recurrence"
```

---

### Task 10: Topic client methods + model

**Files:**
- Modify: `mypalace_client/mypalace_client/models.py` (add `TopicRecurrence`)
- Modify: `mypalace_client/mypalace_client/client.py` (add 2 methods)
- Test: `mypalace_client/tests/test_client_topics.py`

- [ ] **Step 1: Write the failing test**

Create `mypalace_client/tests/test_client_topics.py`:

```python
"""Client tests for topic endpoints using an httpx MockTransport."""
from __future__ import annotations

import httpx
import pytest

from mypalace_client import PalaceClient
from mypalace_client.models import JobPending, TopicRecurrence


def _client(handler) -> PalaceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://palace.test")
    return PalaceClient(base_url="http://palace.test", api_key="k", client=http)


@pytest.mark.asyncio
async def test_extract_topics_returns_job():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/topics/extract"
        return httpx.Response(202, json={"data": {"job_id": "job-1"}, "meta": {"count": 1}})

    pc = _client(handler)
    out = await pc.extract_topics(user_id="u1", conversation_text="x" * 60, conversation_sentiment=-0.2)
    assert isinstance(out, JobPending)
    assert out.job_id == "job-1"


@pytest.mark.asyncio
async def test_get_topic_recurrence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/topic-recurrence"
        return httpx.Response(200, json={"data": [{
            "topic": "job search", "topic_type": "theme", "mention_count": 3,
            "first_mentioned": "3 days ago", "last_mentioned": "yesterday",
            "sentiment_trend": "declining", "avg_emotional_weight": "heavy",
            "pattern_note": "recurring concern (3 mentions)", "channels": ["#dm"],
        }], "meta": {"count": 1}})

    pc = _client(handler)
    out = await pc.get_topic_recurrence(user_id="u1", lookback_days=14, min_mentions=2)
    assert len(out) == 1
    assert isinstance(out[0], TopicRecurrence)
    assert out[0].topic == "job search"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Storage/Code/MyPalace/mypalace_client && uv run --extra dev pytest tests/test_client_topics.py -v`
Expected: FAIL — `ImportError: cannot import name 'TopicRecurrence'`

- [ ] **Step 3: Add the client model**

In `mypalace_client/mypalace_client/models.py`, add:

```python
class TopicRecurrence(BaseModel):
    topic: str
    topic_type: str
    mention_count: int
    first_mentioned: str
    last_mentioned: str
    sentiment_trend: str
    avg_emotional_weight: str
    pattern_note: str
    channels: list[str] = []
```

- [ ] **Step 4: Add the client methods**

Add `TopicRecurrence` to the models import in `client.py`, then after the emotional methods (Task 5) add:

```python
    # ---- topics ----

    async def extract_topics(
        self,
        user_id: str,
        conversation_text: str,
        conversation_sentiment: float = 0.0,
        agent_id: str = "default",
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
    ) -> JobPending:
        body = {
            "user_id": user_id,
            "conversation_text": conversation_text,
            "conversation_sentiment": conversation_sentiment,
            "agent_id": agent_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "is_dm": is_dm,
        }
        envelope = await self._request("POST", "/v1/topics/extract", json=body)
        return JobPending.model_validate(self._data(envelope))

    async def get_topic_recurrence(
        self, user_id: str, lookback_days: int = 14, min_mentions: int = 2,
        agent_id: str = "default",
    ) -> list[TopicRecurrence]:
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/topic-recurrence",
            params={"lookback_days": lookback_days, "min_mentions": min_mentions, "agent_id": agent_id},
        )
        return [TopicRecurrence.model_validate(t) for t in self._data(envelope) or []]
```

(`JobPending` is already imported in `client.py` — it's used by `reflect_session`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Volumes/Storage/Code/MyPalace/mypalace_client && uv run --extra dev pytest tests/test_client_topics.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add mypalace_client/mypalace_client/models.py mypalace_client/mypalace_client/client.py mypalace_client/tests/test_client_topics.py
git commit -m "feat(client): extract_topics + get_topic_recurrence"
```

---

### Task 11: Version bump, CHANGELOG, full test + lint sweep

**Files:**
- Modify: `pyproject.toml`, `mypalace_client/pyproject.toml`, `CHANGELOG.md`

> **NOTE:** `0.12.0` was earmarked in CHANGELOG 0.11.0 for the breaking per-tenant-schema flip. This feature is purely additive. Use `0.12.0` only if the tenancy change hasn't claimed it; otherwise use `0.11.3`. Confirm with the maintainer before tagging.

- [ ] **Step 1: Bump versions**

Set `version = "0.12.0"` in both `pyproject.toml` (line 3) and `mypalace_client/pyproject.toml` (line 3), per the NOTE above.

- [ ] **Step 2: Add CHANGELOG entry**

Prepend a new section to `CHANGELOG.md` under the title:

```markdown
## [0.12.0] — 2026-05-31

Strictly additive — new tables, routes, and client methods; no behavior
change for existing callers.

### Added

- **Emotional-context service** (`emotional_service.py`): server-side VADER
  arc scoring + storage. `POST /v1/emotional/record`,
  `GET /v1/users/{id}/emotional-context`. New `emotional_contexts` table.
- **Topic-recurrence service** (`topic_service.py`): LLM topic extraction via
  the worker queue (`kind="topic_extract"`) + server-side recurrence
  aggregation. `POST /v1/topics/extract` (202 + job_id),
  `GET /v1/users/{id}/topic-recurrence`. New `topic_mentions` table.
- `PalaceClient.record_emotional_context` / `get_emotional_context` /
  `extract_topics` / `get_topic_recurrence`, with `EmotionalContext` and
  `TopicRecurrence` models.
- `vaderSentiment` dependency.

### Migrations

- `2026_05_31_0011_emotional_contexts`, `2026_05_31_0012_topic_mentions`.
```

- [ ] **Step 3: Run the full test suite (both projects)**

Run (server): `cd /Volumes/Storage/Code/MyPalace && uv run pytest tests/ -q`
Run (client): `cd /Volumes/Storage/Code/MyPalace/mypalace_client && uv run --extra dev pytest -q`
Expected: all pass (the server `client` fixture changes must not break other API tests). Note: some server `tests/integration/` cases may require Docker (testcontainers); if those fail purely for environment reasons, report it rather than treat as a code regression.

- [ ] **Step 4: Lint**

Run: `cd /Volumes/Storage/Code/MyPalace && uv run ruff check . && uv run ruff format --check .`
Expected: no errors. Fix any reported issues and re-run.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/Storage/Code/MyPalace
git add pyproject.toml mypalace_client/pyproject.toml CHANGELOG.md
git commit -m "chore: bump to 0.12.0 — emotional + topic services"
```

---

## Self-Review

**Spec coverage:** Data model (Tasks 2, 6) ✓; EmotionalService scoring/record/get_recent (Task 3) ✓; TopicService extraction/aggregation (Task 7) + worker (Task 8) ✓; consumer `/v1` routes (Tasks 4, 9) ✓; client methods (Tasks 5, 10) ✓; VADER dep + server-side scoring (Tasks 1, 3) ✓; worker-queue async for topics, sync for emotional (Tasks 8, 9, 3) ✓; error handling — LLM/VADER failure → `[]`/`stable` (Tasks 3, 7) ✓; testing across unit/service/api/client ✓; version bump (Task 11) ✓. Deferred per spec: gRPC parity, backfill, mypalclara wiring (Follow-up).

**Type consistency:** `EmotionalContext` columns identical across model (Task 2), migration (Task 2), `EmotionalContextOut` (Task 4), and client model (Task 5). `TopicMention`/`TopicRecurrenceOut`/`TopicRecurrence` keys identical across Tasks 6, 7, 9, 10. `compute_emotional_arc` / `compute_topic_pattern` signatures match their tests. `topic_extract` payload keys match between route (Task 9), worker (Task 8), and service (Task 7). `JobPendingOut` (server) ↔ `JobPending` (client) reused, not redefined.

**Placeholder scan:** none — every code step is complete.

## Follow-up (separate plan, mypalclara repo)

On `feat/palace-service-migration`: bump `mypalace-client` from `^0.7.1` to `^0.12.0`; add `USE_PALACE_SERVICE` branches in `context/emotional.py`, `context/topics.py`, and `prompt_builder.fetch_emotional_context`/`fetch_topic_recurrence` to call the new client methods (embedded path unchanged for reversibility). gRPC parity + backfill of legacy `emotional_context`/`topic_mention` memories are optional later slices.
