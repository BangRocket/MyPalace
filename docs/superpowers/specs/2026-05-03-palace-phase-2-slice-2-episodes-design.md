# Palace Phase 2 Slice 2 — Episodes + Narrative Arcs

**Date:** 2026-05-03
**Branch:** `phase-2-slice-2-episodes`
**Status:** Spec — implementation pending

---

## Background

Slice 1 (merged to `main` as PR #1) shipped the drop-in foundations: three new memory endpoints, the `palace_client` async subpackage, opt-in TestContainers integration tests, and the per-method router reference. mypalclara can now route `add`/`search`/`get_all`/`delete_all`/`get`/`delete`/`update` to a remote Palace.

Slice 2 ports the **episodic memory subsystem** — the part of mypalclara that turns conversations into structured Episodes and rolls Episodes into NarrativeArcs. After slice 2, mypalclara's `episode_store.*` callers and `MM.reflect_on_session` / `MM.run_narrative_synthesis` callers can flip to remote Palace.

---

## Surface area mapped

mypalclara's episode subsystem (verified against `/Volumes/Storage/Code/mypalclara/`):

- **Episode**: dataclass with `id`, `user_id`, `agent_id`, `content`, `summary`, `participants[]`, `topics[]`, `emotional_tone`, `significance` (0.0-1.0), `timestamp`, `session_id`, `message_count`. Stored Qdrant-only in `clara_episodes` collection (no Postgres table). Embedded text = `content` (verbatim conversation slice).
- **NarrativeArc**: dataclass with `id`, `user_id`, `agent_id`, `title`, `summary`, `status` (active/resolved/dormant), `key_episode_ids[]`, `emotional_trajectory`, `created_at`, `updated_at`. Stored in the same `clara_episodes` Qdrant collection with a `type: "narrative_arc"` discriminator.
- **Extraction**: `MM.reflect_on_session(messages, user_id, session_id)` calls an LLM with `SESSION_REFLECTION_PROMPT`, parses JSON containing 1-5 episodes per session. Wrapped in `asyncio.run_in_executor` at callsites — fire-and-forget after session end.
- **Synthesis**: `MM.run_narrative_synthesis(user_id)` fetches recent 20 episodes + active arcs, calls an LLM with `NARRATIVE_SYNTHESIS_PROMPT`, creates new arcs.
- **Retrieval (the slice-1-deferred external callers)**: `episode_store.search(query, user_id, limit, min_significance)`, `.get_recent(user_id, limit)`, `.get_active_arcs(user_id, limit)` — all called from `mypalclara/core/prompt_builder.py:436-484`.
- **Significance threshold** `EPISODE_MIN_SIGNIFICANCE=0.3` (default) is applied at *retrieval* time (`search` filter), not at write time — episodes are stored regardless of significance.
- **Dependencies in slice scope**: LLM client, embedding model, Qdrant. Out of scope: EntityResolver, FSRS, FalkorDB.

---

## Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| **D1** | Both sync and async modes via query param `?mode=sync\|async`, default async. | Sync gives tests a clean path with no flaky polling. Async gives mypalclara the fire-and-forget shape it expects. Cost is one if-statement and a job table. |
| **D2** | Endpoint takes `messages` in the request body, not a `session_id`. | Mechanical match to mypalclara's `reflect_on_session(messages, ...)` signature. Lets callers reflect on partial conversations and works for callers who don't use Palace's session subsystem at all. |
| **D3** | Episodes in Qdrant, narrative arcs in Postgres JSONB (NOT a shared Qdrant collection per mypalclara's pattern). | Arcs are queried by `status="active"` + `user_id`, never semantically — embedding them is dead weight. `key_episode_ids` is a natural JSONB array. Postgres handles the query natively, no Qdrant point-id juggling. The wire shape stays identical to mypalclara, so the router is unaffected. |
| **D4** | Narrative synthesis ships in slice 2 alongside reflection. | Synthesis is mechanically the same shape as reflection (LLM call → structured rows). Splitting it across slices duplicates the prompt/parse pattern. Slice 4 cleanly becomes intentions-only. `get_active_arcs` actually works after slice 2. |
| **D5** | Pure-asyncio jobs (no Celery/arq) for async mode. New `reflection_jobs` table tracks status; `GET /v1/jobs/{job_id}` polling endpoint. | Smallest infrastructure that gives observability + retry-via-re-POST. Worker process can be added in phase 3 if jobs need to survive process restarts. |
| **D6** | LLM extraction uses phase 1's existing `palace/llm.py` httpx client (OpenAI-compatible chat completions). | mypalclara uses an Anthropic-flavored LangChain wrapper, but most providers (including Anthropic via OpenRouter) speak the OpenAI chat-completion shape. Avoids adding a second LLM SDK to slice 2. |
| **D7** | EntityResolver, self-notes extraction, and job retry are out of scope. | EntityResolver is a separate subsystem with its own SQLite table — phase 3. Self-notes are a nice-to-have. Failed jobs stay failed; caller re-POSTs. Keeps slice 2 to ~5 commits. |

---

## Wire contract — slice 2 endpoints

All responses use the existing `ApiResponse` envelope.

### `POST /v1/reflection/session?mode={sync,async}` (default async)

```json
POST /v1/reflection/session?mode=sync
{
  "user_id": "u1",
  "agent_id": "clara",                 // optional, default null
  "session_id": "s-123",               // optional, stored on each episode for traceability
  "messages": [
    {"role": "user", "content": "I think I'm going to leave my job."},
    {"role": "assistant", "content": "What's driving that?"},
    {"role": "user", "content": "I haven't grown in two years."}
  ]
}

→ 200 (sync mode) { "data": [Episode, Episode, ...], "meta": {"count": N, "took_ms": N} }
→ 202 (async mode) { "data": {"job_id": "uuid", "status": "pending"}, "meta": {...} }
```

- Sync mode: handler awaits the LLM extraction, returns the Episode list directly. Latency 2-5s.
- Async mode: creates a `reflection_jobs` row, spawns `asyncio.create_task(...)`, returns 202 + job id. Background task updates the row when done.
- Episodes are stored before being returned (sync) or before the job completes (async).

### `POST /v1/synthesis/narratives?mode={sync,async}` (default async)

```json
POST /v1/synthesis/narratives?mode=sync
{
  "user_id": "u1",
  "agent_id": "clara",            // optional
  "lookback_episodes": 20         // optional, default 20
}

→ 200 (sync) { "data": [NarrativeArc, ...], "meta": {...} }
→ 202 (async) { "data": {"job_id": "uuid", "status": "pending"}, "meta": {...} }
```

- Fetches recent N episodes for the user, plus existing active arcs, calls the synthesis LLM, creates new arc rows or updates existing ones (status transitions only — never overwrites titles/summaries; LLM is supposed to preserve them).
- New arcs land in the `narrative_arcs` Postgres table; existing arcs may transition `active` → `resolved` or `dormant` based on the LLM's reading.

### `POST /v1/episodes/search`

```json
{
  "query": "career uncertainty",
  "user_id": "u1",                    // required
  "limit": 5,                         // default 5
  "min_significance": 0.3             // default 0.0
}

→ 200 { "data": [Episode, ...], "meta": {...} }
```

- Semantic search via Qdrant. Filter: `user_id` (mandatory), `significance >= min_significance`.
- Ordered by Qdrant similarity score descending.

### `GET /v1/users/{user_id}/episodes/recent?limit=5`

```
GET /v1/users/u1/episodes/recent?limit=10

→ 200 { "data": [Episode, ...], "meta": {...} }
```

- Recent episodes ordered by `timestamp DESC`. No semantic search.
- Implementation: Qdrant scroll with payload filter + client-side sort (Qdrant's order-by-payload support is uneven across versions).

### `GET /v1/users/{user_id}/arcs/active?limit=10`

```
GET /v1/users/u1/arcs/active?limit=5

→ 200 { "data": [NarrativeArc, ...], "meta": {...} }
```

- SQL `SELECT * FROM narrative_arcs WHERE user_id=? AND status='active' ORDER BY updated_at DESC LIMIT ?`.

### `GET /v1/jobs/{job_id}`

```
GET /v1/jobs/abc-123

→ 200 {
  "data": {
    "id": "abc-123",
    "kind": "reflection" | "synthesis",
    "user_id": "u1",
    "status": "pending" | "completed" | "failed",
    "created_at": "2026-...",
    "completed_at": "2026-..." | null,
    "result": [Episode, ...] | [NarrativeArc, ...] | null,
    "error": "stack trace string" | null
  },
  "meta": {...}
}
```

- 404 if job_id unknown.
- `result` is the JSON-serialized Episode/NarrativeArc list (whatever the sync mode would have returned).

### Backward compatibility

All slice-1 endpoints unchanged.

---

## Data model

### Episode (Qdrant payload — no Postgres table)

Collection: `palace_episodes` (separate from `palace_memories`). Vector size = embedder dim. Payload schema:

```python
class Episode(BaseModel):
    id: str                          # Qdrant point id (UUID)
    user_id: str
    agent_id: str | None = None
    content: str                     # the verbatim conversation slice (also what's embedded)
    summary: str                     # one-line LLM summary
    participants: list[str] = []
    topics: list[str] = []
    emotional_tone: str = "neutral"
    significance: float = 0.5        # 0.0 - 1.0
    timestamp: datetime              # tz-aware UTC
    session_id: str | None = None
    message_count: int = 0
```

Indexed payload fields (for filtering): `user_id`, `agent_id`, `significance`, `timestamp`.

### NarrativeArc (Postgres `narrative_arcs` table)

```python
class NarrativeArc(SQLModel, table=True):
    __tablename__ = "narrative_arcs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    title: str
    summary: str
    status: str = Field(default="active", index=True)   # active | resolved | dormant
    key_episode_ids: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    emotional_trajectory: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
```

### ReflectionJob (Postgres `reflection_jobs` table)

```python
class ReflectionJob(SQLModel, table=True):
    __tablename__ = "reflection_jobs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    kind: str = Field(index=True)                   # "reflection" | "synthesis"
    user_id: str = Field(index=True)
    status: str = Field(default="pending", index=True)  # pending | completed | failed
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    completed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    result_json: list | dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    error: str | None = None
```

---

## Service layer

```
palace/
├── episode_service.py         # EpisodeService — Qdrant CRUD + search + LLM-driven reflect_session
├── arc_service.py             # ArcService — Postgres CRUD + LLM-driven synthesize_narratives
├── job_service.py             # JobService — reflection_jobs CRUD + asyncio.create_task wrapper
└── prompts/
    ├── __init__.py
    ├── reflection.py          # SESSION_REFLECTION_PROMPT constant
    └── synthesis.py           # NARRATIVE_SYNTHESIS_PROMPT constant
```

### `EpisodeService`

```python
class EpisodeService:
    async def init(self) -> None: ...                 # ensure Qdrant collection + payload indexes

    async def reflect_session(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> list[Episode]: ...                            # LLM call + write episodes; sync path

    async def search(
        self, query: str, user_id: str,
        limit: int = 5, min_significance: float = 0.0,
    ) -> list[Episode]: ...

    async def get_recent(self, user_id: str, limit: int = 5) -> list[Episode]: ...
```

### `ArcService`

```python
class ArcService:
    async def synthesize_narratives(
        self, user_id: str, agent_id: str | None = None,
        lookback_episodes: int = 20,
    ) -> list[NarrativeArc]: ...                       # LLM call + create/update arc rows

    async def get_active(self, user_id: str, limit: int = 10) -> list[NarrativeArc]: ...

    async def create(self, **fields) -> NarrativeArc: ...
    async def update(self, arc_id: str, **fields) -> NarrativeArc | None: ...
```

### `JobService`

```python
class JobService:
    async def create(self, kind: str, user_id: str) -> ReflectionJob: ...
    async def get(self, job_id: str) -> ReflectionJob | None: ...
    async def complete(self, job_id: str, result: list | dict) -> None: ...
    async def fail(self, job_id: str, error: str) -> None: ...

    async def run_async(
        self,
        kind: str, user_id: str,
        coro_factory: Callable[[], Awaitable[list | dict]],
    ) -> ReflectionJob: ...
        """Create job row, spawn asyncio.create_task that calls coro_factory()
        and writes result/error back to the row. Returns the pending job."""
```

---

## Prompts

### `palace/prompts/reflection.py`

```python
SESSION_REFLECTION_PROMPT = """You are analyzing a conversation to extract meaningful episodes.

Conversation:
{conversation_text}

Extract 1-5 distinct episodes from this conversation. For each episode, provide:
- summary: one sentence describing what happened
- topics: list of 1-5 topic tags
- emotional_tone: one of [happy, sad, anxious, frustrated, curious, neutral, excited, contemplative]
- significance: float 0.0-1.0 indicating how meaningful this exchange was
- start_index, end_index: integer indices into the message list (inclusive)

Return ONLY valid JSON in this shape:
{{"episodes": [{{"summary": "...", "topics": [...], "emotional_tone": "...", "significance": 0.7, "start_index": 0, "end_index": 4}}, ...]}}
"""
```

### `palace/prompts/synthesis.py`

```python
NARRATIVE_SYNTHESIS_PROMPT = """You are identifying narrative arcs across a user's recent episodes.

Recent episodes (most recent first):
{episodes_text}

Existing active arcs (do not duplicate or rename these — only update status if needed):
{existing_arcs_text}

Identify ongoing storylines. For each arc, return:
- title: short name (e.g., "Job search", "Move to Berlin")
- summary: 2-3 sentences describing the trajectory
- status: "active" | "resolved" | "dormant"
- key_episode_ids: list of episode IDs that belong to this arc
- emotional_trajectory: brief description of how feelings have evolved
- existing_id: if this updates an existing arc, its ID; otherwise null

Return ONLY valid JSON:
{{"arcs": [{{"title": "...", "summary": "...", "status": "active", "key_episode_ids": [...], "emotional_trajectory": "...", "existing_id": null}}, ...]}}
"""
```

Both prompts are constants in `.py` files (not Jinja templates) — small, easy to tweak, no template engine needed for slice 2.

---

## Client + router updates

### `palace_client.PalaceClient` (slice 2 additions)

```python
# ---- episodes ----
async def reflect_session(
    self, messages: list[dict], user_id: str,
    agent_id: str | None = None, session_id: str | None = None,
    mode: str = "async",
) -> list[Episode] | Job: ...

async def search_episodes(
    self, query: str, user_id: str,
    limit: int = 5, min_significance: float = 0.0,
) -> list[Episode]: ...

async def get_recent_episodes(self, user_id: str, limit: int = 5) -> list[Episode]: ...

# ---- arcs ----
async def synthesize_narratives(
    self, user_id: str, agent_id: str | None = None,
    lookback_episodes: int = 20, mode: str = "async",
) -> list[NarrativeArc] | Job: ...

async def get_active_arcs(self, user_id: str, limit: int = 10) -> list[NarrativeArc]: ...

# ---- jobs ----
async def get_job(self, job_id: str) -> Job: ...
```

`reflect_session` and `synthesize_narratives` return either the result list (sync mode) or a `Job` (async mode) — typed as a union. Caller checks `isinstance(result, Job)` to know which.

### Wire types (additions to `palace_client/models.py`)

`Episode`, `NarrativeArc`, `Job` — Pydantic v2, mirror server response shapes 1:1.

### `examples/mypalclara_router.py` updates

- `RoutedPalace.episode_store` becomes a routed property:
  ```python
  @property
  def episode_store(self):
      if USE_PALACE_SERVICE:
          return RemoteEpisodeStore(_remote())
      return _EMBEDDED_PALACE.episode_store
  ```
  Where `RemoteEpisodeStore` is a small wrapper exposing `search`, `get_recent`, `get_active_arcs` that delegate to the client.
- `RoutedMemoryManager.reflect_on_session` and `.run_narrative_synthesis` graduate from one-line embedded delegates to `if USE_PALACE_SERVICE` branches that call the client.
- All other methods unchanged.

---

## Test plan

### Mock unit tests (~12-15 new)

- `tests/test_episodes.py` — POST /v1/reflection/session (sync + async modes), POST /v1/episodes/search, GET /v1/users/{id}/episodes/recent. EpisodeService.reflect_session with mocked LLM.
- `tests/test_arcs.py` — POST /v1/synthesis/narratives, GET /v1/users/{id}/arcs/active.
- `tests/test_jobs.py` — GET /v1/jobs/{id} happy + 404.
- `palace_client/tests/test_client.py` additions — MockTransport tests for the 6 new client methods.

### Integration tests (~5 new)

The LLM is **stubbed via dependency injection** in integration tests — we don't want testcontainers + a real LLM provider. Pattern: a fixture overrides `palace.llm.llm.complete` with a stub returning canned JSON.

- `tests/integration/test_episodes_live.py`:
  - `test_reflect_creates_episodes_live` — sync mode + stub LLM, verify episodes land in Qdrant
  - `test_search_episodes_live` — seed via reflect, search by query, verify results
  - `test_recent_episodes_live` — seed multiple, verify timestamp ordering
- `tests/integration/test_arcs_live.py`:
  - `test_synthesize_creates_arcs_live` — seed episodes via reflect, synthesize, verify arc rows
  - `test_active_arcs_filter_live` — create active + resolved arcs, verify only active returned
- `tests/integration/test_jobs_live.py`:
  - `test_async_job_lifecycle_live` — POST async, poll job, verify completed status + result

---

## Repo layout after slice 2

```
palace/
├── (slice 1 files unchanged)
├── episode_service.py         NEW
├── arc_service.py             NEW
├── job_service.py             NEW
├── models.py                  + NarrativeArc + ReflectionJob
├── api/
│   ├── episodes.py            NEW — episode + reflection routes
│   ├── arcs.py                NEW — arc + synthesis routes
│   ├── jobs.py                NEW — job status route
│   └── common.py              + new request/response models
└── prompts/
    ├── __init__.py            NEW
    ├── reflection.py          NEW
    └── synthesis.py           NEW

palace_client/
└── palace_client/
    ├── client.py              + 6 new methods
    └── models.py              + Episode, NarrativeArc, Job

tests/
├── test_episodes.py           NEW
├── test_arcs.py               NEW
├── test_jobs.py               NEW
└── integration/
    ├── test_episodes_live.py  NEW
    ├── test_arcs_live.py      NEW
    └── test_jobs_live.py      NEW

examples/mypalclara_router.py  updated (RoutedPalace.episode_store routes; reflect/synthesize branch)
docs/superpowers/specs/2026-05-03-palace-phase-2-slice-2-episodes-design.md  THIS DOC
```

---

## Commit plan

5 commits, same shape as slice 1:

1. `feat(models): episode storage (Qdrant collection + narrative_arcs + reflection_jobs)` — schema only, no behavior. Includes `EpisodeService.init()` for Qdrant collection + payload indexes. Mock tests for the new SQLModel tables.
2. `feat(api): reflection, synthesis, episode/arc/job endpoints` — all 6 new routes + service implementations + prompt constants + mock tests with stubbed LLM.
3. `feat(client): episode/arc/job methods + wire types` — palace_client additions with MockTransport tests.
4. `test(integration): live episodes/arcs/reflection/jobs coverage with stubbed LLM` — TestContainers e2e + the LLM stub pattern.
5. `docs(examples): router updates + README slice-2 section` — RoutedPalace.episode_store, MM.reflect_on_session / .run_narrative_synthesis branches, README update.

---

## Risks tracked

| Risk | Mitigation |
|------|------------|
| **LLM JSON parse failures.** The reflection/synthesis prompts ask for JSON; a flaky LLM might return prose, code fences, or malformed JSON. | Wrap parse in `try/except`; on failure write `error` to the job row (async) or raise `LLMParseError` mapped to 502 (sync). Tests pin the failure path. |
| **`asyncio.create_task` doesn't survive process restart.** Async jobs in flight are lost if uvicorn restarts. | Documented in spec; phase 3 swaps in a real worker (Celery/arq). For slice 2, jobs that are still `pending` after server restart are effectively orphaned — caller can re-POST. |
| **Qdrant payload-index version skew.** Older Qdrant versions don't support OrderBy on payload fields; `get_recent` falls back to client-side sort. | Implementation does the client-side sort by default — no version sniffing needed. |
| **LLM provider auth in integration tests.** Real OpenRouter calls would slow tests + cost money + be flaky. | Hard requirement: integration tests must override `palace.llm.llm.complete` with a stub. The conftest provides a fixture. Failing to inject the stub = test fails with "no API key" — loud, not silent. |
| **`narrative_arcs.key_episode_ids` JSONB array drift.** If episode UUIDs change (e.g., re-extracting), the arc's `key_episode_ids` references go stale. | Out of scope — mypalclara has the same issue. Arcs are best-effort references. Document in spec. |

---

## Out of scope (later slices / phase 3)

- **EntityResolver** — registers human names from conversations into a SQLite `entity_aliases` table. Phase 3.
- **Self-notes extraction** — mypalclara's reflection prompt also pulls "what worked in this conversation." Drop in slice 2; can add later.
- **Job retry semantics** — failed jobs stay failed; caller re-POSTs.
- **Real worker process** (Celery/arq/RQ) — phase 3 if jobs need to survive restarts.
- **gRPC, auth, multi-tenancy** — phase 3.

---

## Done criteria for slice 2

- [ ] All six new endpoints implemented, mock-tested, integration-tested.
- [ ] `palace_client` exposes all six new methods, all covered by MockTransport unit tests.
- [ ] Sync and async modes both work for reflection and synthesis.
- [ ] Job polling endpoint returns correct status transitions (pending → completed | failed).
- [ ] Integration tests stub the LLM via dependency injection — no real LLM calls.
- [ ] `examples/mypalclara_router.py` graduates `episode_store`, `reflect_on_session`, and `run_narrative_synthesis` from embedded-only to routed-when-`USE_PALACE_SERVICE`.
- [ ] README has a "Slice 2: episodes + narrative arcs" subsection.
- [ ] Branch `phase-2-slice-2-episodes` merged to `main` (no-ff merge per slice-1 precedent).
