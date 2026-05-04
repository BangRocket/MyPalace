# Palace Phase 2 Slice 3 — FSRS Memory Dynamics

**Branch:** `phase-2-slice-3-fsrs`
**Status:** Spec — implementation pending

## Background

Slice 1 (drop-in MVP) and slice 2 (episodes + arcs) shipped. Slice 3 ports mypalclara's FSRS-6-based memory dynamics: per-memory stability/difficulty/retrievability state, access logging, and composite ranking that combines semantic similarity with FSRS-derived retrievability.

## Surface area

mypalclara source confirmed at `/Volumes/Storage/Code/mypalclara/`:
- `MemoryDynamics` model: `mypalclara/db/models.py:401-449` — per-memory FSRS state (stability, difficulty, retrieval_strength, storage_strength, is_key, importance_weight, category, tags, last_accessed_at, access_count, created_at, updated_at). PK = memory_id; composite index `(user_id, last_accessed_at)`.
- `MemoryAccessLog` model: `:451-489` — audit trail (id, memory_id FK, user_id, grade, signal_type, retrievability_at_access, context, accessed_at). Composite index `(user_id, accessed_at)`.
- FSRS-6 algorithm: `mypalclara/core/memory/dynamics/fsrs.py` — pure functions over `MemoryState`/`Grade`/`FsrsParams`. `review`, `retrievability`, `initial_*`, `update_*`, `infer_grade_from_signal`, `calculate_memory_score`.
- `MemoryDynamicsManager`: `mypalclara/core/memory/dynamics/manager.py` — `get_memory_dynamics`, `ensure_memory_dynamics`, `promote_memory`, `demote_memory`, `calculate_memory_score`, `prune_old_access_logs`, `rank_results_with_fsrs_batch`.
- Composite formula: `composite = 0.6*semantic + 0.4*((0.7*retrievability + 0.3*storage_strength) * importance_weight)`.

External callers (already mapped in slice 1's recon):
- `MM.get_memory_dynamics(memory_id, user_id)` — `gateway/processor.py`
- `MM.promote_memory(memory_id, user_id, grade, signal_type)` — `gateway/processor.py:1080`
- `MM.demote_memory(memory_id, user_id, reason)` — embedded only
- `MM.calculate_memory_score(memory_id, user_id, semantic_score)` — internal to ranking
- `MM.get_last_retrieved_memory_ids(user_id)` — `gateway/processor.py:1072`
- `MM.prune_old_access_logs(db, retention_days)` — admin/cron
- `MM.ensure_memory_dynamics(memory_id, user_id, is_key)` — internal

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| **D1** | Port `fsrs.py` math character-for-character into `palace/dynamics/fsrs.py`. License: original is the same author/repo (no license complications). | Math is well-tested in mypalclara; rewriting risks subtle off-by-one errors. Keep the file isolated so it's easy to swap if FSRS-7 lands. |
| **D2** | Models go to `palace/models.py` (extends slice-1 + slice-2 additions). PK on `MemoryDynamics.memory_id` (one row per memory, not composite with user_id since memories belong to one user already). | Matches mypalclara. |
| **D3** | `MemoryAccessLog.memory_id` is FK to `MemoryDynamics.memory_id` with CASCADE delete (matches mypalclara). When the dynamics row is deleted, audit trail goes too. | mypalclara behavior. |
| **D4** | `get_last_retrieved_memory_ids` is **not** an endpoint. The HTTP service is stateless between requests; an in-process cache wouldn't survive across worker processes. Instead, the response from `POST /v1/memories/search` and the new `POST /v1/memories/{id}/score` includes a `last_retrieved_at` timestamp on each memory's dynamics, and the mypalclara router caches the IDs client-side. | Avoids server-side state that would be wrong under multi-worker uvicorn. Caller-side cache matches the in-memory pattern in mypalclara. |
| **D5** | All endpoints sync — no LLM, no async jobs needed. | Pure math + DB. |
| **D6** | Composite ranking endpoint takes `semantic_score` from caller rather than re-computing — keeps the endpoint stateless per memory and matches mypalclara's `calculate_memory_score(semantic_score)` signature. Caller already has the semantic score from a prior `/v1/memories/search`. | Avoids needing the search query on the score endpoint. |

## Wire contract

All responses use the existing `ApiResponse` envelope.

### `POST /v1/memories/{memory_id}/promote`

```json
{ "user_id": "u1", "grade": 3, "signal_type": "used_in_response" }

→ 200 { "data": MemoryDynamicsOut, "meta": {...} }
```

- `grade` defaults to `3` (GOOD). Valid: `1` (AGAIN/fail), `2` (HARD), `3` (GOOD), `4` (EASY).
- `signal_type` defaults to `"used_in_response"`. Free-form string; passed to access log.
- Auto-creates the dynamics row if missing.

### `POST /v1/memories/{memory_id}/demote`

```json
{ "user_id": "u1", "reason": "user_correction" }

→ 200 { "data": MemoryDynamicsOut, "meta": {...} }
```

- Calls `promote(grade=1, signal_type=reason)` internally — fail signal.

### `GET /v1/memories/{memory_id}/dynamics?user_id=u1`

```
→ 200 { "data": MemoryDynamicsOut, "meta": {...} }
→ 404 if no dynamics row exists for that (memory_id, user_id)
```

### `POST /v1/memories/{memory_id}/score`

```json
{ "user_id": "u1", "semantic_score": 0.87 }

→ 200 { "data": { "composite_score": 0.79, "fsrs_score": 0.65, "retrievability": 0.82, "storage_strength": 0.50 }, "meta": {...} }
```

- Returns the composite breakdown so callers can debug ranking.
- Auto-creates the dynamics row if missing (with default stability/difficulty).

### `POST /v1/maintenance/prune-access-logs?retention_days=90`

```
→ 200 { "data": { "deleted": N }, "meta": {...} }
```

- Admin operation. Defaults to 90 days. No per-user filter.

## Data model additions to `palace/models.py`

```python
class MemoryDynamics(SQLModel, table=True):
    __tablename__ = "memory_dynamics"

    memory_id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    stability: float = Field(default=1.0)
    difficulty: float = Field(default=5.0)
    retrieval_strength: float = Field(default=1.0)
    storage_strength: float = Field(default=0.5)
    is_key: bool = Field(default=False)
    importance_weight: float = Field(default=1.0)
    category: str | None = Field(default=None, max_length=50)
    tags: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    last_accessed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    access_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class MemoryAccessLog(SQLModel, table=True):
    __tablename__ = "memory_access_logs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    memory_id: str = Field(index=True, foreign_key="memory_dynamics.memory_id", ondelete="CASCADE")
    user_id: str = Field(index=True)
    grade: int
    signal_type: str
    retrievability_at_access: float
    context: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    accessed_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
```

(SQLModel composite indexes on `(user_id, last_accessed_at)` and `(user_id, accessed_at)` via `sa_column_kwargs` — see implementation.)

## Service layer

```
palace/
├── dynamics/
│   ├── __init__.py
│   ├── fsrs.py              # ported math (pure functions)
│   └── service.py           # DynamicsService (DB-touching wrapper)
└── api/
    ├── dynamics.py          # routes (mounted under /v1)
    └── maintenance.py       # prune-access-logs route
```

`DynamicsService` mirrors `MemoryDynamicsManager`:
- `get_dynamics(memory_id, user_id) -> MemoryDynamics | None`
- `ensure_dynamics(memory_id, user_id, is_key=False) -> MemoryDynamics`
- `promote(memory_id, user_id, grade=3, signal_type="used_in_response") -> MemoryDynamics`
- `demote(memory_id, user_id, reason="user_correction") -> MemoryDynamics`
- `score(memory_id, user_id, semantic_score: float) -> dict`
- `prune_access_logs(retention_days: int = 90) -> int`

## Client + router

`PalaceClient` gains:
- `promote_memory(memory_id, user_id, grade=3, signal_type="used_in_response") -> MemoryDynamics`
- `demote_memory(memory_id, user_id, reason="user_correction") -> MemoryDynamics`
- `get_dynamics(memory_id, user_id) -> MemoryDynamics`
- `score_memory(memory_id, user_id, semantic_score) -> ScoreBreakdown`
- `prune_access_logs(retention_days=90) -> int`

Wire types: `MemoryDynamics`, `ScoreBreakdown`.

`examples/mypalclara_router.py`: graduate `MM.promote_memory`, `MM.demote_memory`, `MM.get_memory_dynamics`, `MM.calculate_memory_score`, `MM.prune_old_access_logs` from embedded one-liners to `if USE_PALACE_SERVICE` branches.

`MM.get_last_retrieved_memory_ids` stays embedded (D4 — caller-side cache).

## Test plan

- Mock unit tests: 4-5 endpoints, service tests for promote/demote/score/prune. ~10 tests.
- FSRS math tests: deterministic — 5-6 tests pinning the algorithm against known inputs (verifies no porting drift). Exact same test inputs as mypalclara if possible.
- Integration: 2-3 live tests covering promote → score → prune cycle.

## Commit plan

5-commit shape, mirrors slice 2:
1. `feat(models): MemoryDynamics + MemoryAccessLog tables`
2. `feat(dynamics): FSRS-6 algorithm port + service + endpoints`
3. `feat(client): dynamics methods + wire types`
4. `test(integration): live FSRS coverage`
5. `docs(examples): router updates + README slice-3 section`
