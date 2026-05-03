# Palace Phase 2 Design — Feature Parity with mypalclara, in Slices

**Date:** 2026-05-03
**Branch:** `phase-2`
**Status:** Spec — slice 1 implementation pending user review of this doc

---

## Background

Phase 1 (shipped on `main` as commits `e2941b0..12ba86d`) delivered a standalone Palace memory service: memory CRUD, semantic search over Qdrant, session/message persistence, context assembly. Verified end-to-end against live postgres + qdrant via podman.

Phase 2 brings Palace toward feature parity with mypalclara's embedded `ClaraMemory` + `MemoryManager`, in slices, while preserving two simultaneous use cases:

1. **Standalone.** Any application — not just mypalclara — can use Palace as a generic memory service over HTTP.
2. **Drop-in replacement.** mypalclara can route its existing memory calls to a remote Palace instance instead of running embedded, with bounded changes to mypalclara itself.

---

## Surface area mapped

A reconnaissance pass across `mypalclara/core/memory/`, `mypalclara/core/memory_manager.py`, and all *external* callers (gateway, prompt_builder, mcp integration, game adapter) identified:

- ~47 public methods total across `ClaraMemory` + `MemoryManager`.
- **~18 of those are actually called from outside the memory module.** Phase 1 already covers ~7. The remaining ~11 are what slices 2-5 deliver.
- Three external call patterns reach into Palace via *sub-objects*: `PALACE.embedding_model.embed(...)`, `PALACE.graph.search(...)`, and `episode_store.x` access. These shape the drop-in design — see decision D1.

The full surface map is in the conversation transcript and is the basis for the slice ordering below. Anything not surfaced there is treated as internal to mypalclara's memory subsystem and not in scope.

---

## Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| **D1** | Pragmatic drop-in (B), then true drop-in (A) later if needed. | A's sub-object proxies (`.embedding_model.embed`, `.graph.search`) would force synchronous Python wrappers around HTTP, which is awkward and slow. B forces those direct-access patterns to be cleaned up in mypalclara — a net win for both codebases. |
| **D2** | Slice 1 first; slices 2-5 queued (see roadmap). | Smallest unit of value; forces the client adapter ergonomics to surface early; de-risks the mypalclara integration story before investing in episode/FSRS/reflection ports. |
| **D3** | Per-method delegation (B), not all-or-nothing toggle. | Slice 1 ships shippable AND usable on day one — `add`/`search`/`get_all`/`delete_all` flip to remote, everything else stays embedded. Adapter shrinks as more slices land. |
| **D4** | Opt-in integration tests via TestContainers (C), mocks stay default. | Preserves phase 1's 2-second test loop. Real-backend coverage is gated behind `pytest -m integration`. CI predictability stays high. |
| **D5** | Client lives in this repo as a path-installable subpackage (C). | Single source of truth (server + client change in one PR). Defers PyPI publishing until phase 3 when there's a second consumer. |
| **D6** | Explicit pass-throughs in the mypalclara router (no `__getattr__` fallthrough). | "Method missing from router" becomes an import-test failure, not a silent embedded-forever bug. Verbose but obvious. |
| **D7** | `infer=True` defaults to `False` on the wire. | mypalclara's adapter passes `infer=True` explicitly when LLM extraction is wanted; standalone callers get predictable verbatim storage. |
| **D8** | `Memory.metadata_json` column promoted to JSONB. | `/v1/memories/list` filters by metadata key/value containment; needs JSONB, not opaque string. Phase 1 has no real data; one-time drop-and-recreate is acceptable. |

---

## Scope of slice 1

### What ships

1. **Three new Palace HTTP endpoints:**
   - `POST /v1/memories/batch` — accept a list of message dicts (`[{role, content}]`) and create N memories. No LLM extraction in slice 1; messages stored verbatim.
   - `POST /v1/memories/list` — list with rich filters (user_id, agent_id, run_id, memory_type, metadata containment).
   - `DELETE /v1/users/{user_id}/memories` — purge by user (with optional `agent_id`, `run_id` query params).

2. **A `palace_client/` Python subpackage** in this repo, installable via path/git, async-first, exposing `PalaceClient` with the methods listed in section "PalaceClient interface" below.

3. **A reference router** at `examples/mypalclara_router.py` showing the per-method delegation pattern with **explicit pass-throughs** for every ClaraMemory + MemoryManager method.

4. **Integration tests** under `tests/integration/`, opt-in via `pytest -m integration`, using TestContainers for postgres + qdrant.

### What does not ship in slice 1

Episodes, FSRS dynamics, reflection, intentions, layered retrieval, smart-ingest dedup, graph memory (FalkorDB), Redis cache, batch operations beyond `add`, gRPC, auth. These are slices 2-5 and phase 3.

### What does not ship from this repo at all in slice 1

Changes inside the mypalclara repository. mypalclara is separate version control; the slice 1 deliverable is the *capability* (server + client + recipe). The mypalclara PR is a follow-on and lives in that repo's own branch.

---

## Wire contract — slice 1 endpoints

All responses use the existing `ApiResponse` envelope: `{ "data": ..., "meta": { "count": N, "took_ms": N } }`. Errors return 4xx/5xx with FastAPI default body.

### `POST /v1/memories/batch`

```json
{
  "user_id": "u1",
  "agent_id": "clara",
  "messages": [
    {"role": "user", "content": "I love dark mode"},
    {"role": "assistant", "content": "Got it, I'll remember that"}
  ],
  "memory_type": "episodic",
  "metadata": {"session_id": "s1"},
  "source": "chat",
  "infer": false
}

→ 200 { "data": [Memory, Memory], "meta": {"count": 2, "took_ms": ...} }
```

- One input message → one Memory row, content = message content. Role + any other message keys go into `metadata_json` as `{"role": "...", ...metadata}`.
- `infer` is accepted but ignored in slice 1. Forward-compatible no-op for the future smart-ingest path.
- All created memories share `agent_id`, `memory_type`, `metadata` (with role merged in), and `source` from the request.

### `POST /v1/memories/list`

```json
{
  "user_id": "u1",
  "agent_id": "clara",
  "run_id": "session-123",
  "memory_type": "preference",
  "metadata": {"category": "ui"},
  "limit": 50,
  "offset": 0
}

→ 200 { "data": [Memory, ...], "meta": {"count": 50, "took_ms": ...} }
```

- All filter fields optional; absence means no filter on that field.
- Metadata matching is JSONB containment (`metadata_json::jsonb @> ?::jsonb`).
- `run_id` is shorthand for `metadata.run_id` containment, mirroring mypalclara's `ClaraMemory.get_all` semantics.
- Default `limit=50`, max `limit=500` (server-clamped). Default `offset=0`.
- Results ordered by `created_at DESC`.

### `DELETE /v1/users/{user_id}/memories`

```
DELETE /v1/users/u1/memories?agent_id=clara&run_id=session-123

→ 200 { "data": {"deleted": 47}, "meta": {"count": 47, "took_ms": ...} }
```

- Always succeeds with `deleted: 0` if nothing matched (not 404).
- Deletes corresponding Qdrant points in batches of up to 500 ids.
- Filters: `user_id` (path, required), `agent_id` (query, optional), `run_id` (query, optional, matches `metadata.run_id`).

### Backward compatibility

All phase-1 endpoints, request/response shapes, and the `ApiResponse` envelope are unchanged. The simple `GET /v1/users/{user_id}/memories?limit=50` stays for ergonomics; `POST /v1/memories/list` is the richer-filter variant.

---

## `palace_client` library

### Repo location

```
palace-memory/
├── palace/                 (existing service)
└── palace_client/          (NEW sibling Python package)
    ├── pyproject.toml      separate package metadata, name "palace-client"
    ├── palace_client/
    │   ├── __init__.py     re-exports PalaceClient + types + exceptions
    │   ├── client.py       PalaceClient class
    │   ├── exceptions.py   PalaceError, PalaceNotFound, PalaceTransport
    │   └── models.py       Pydantic wire types
    └── tests/
        └── test_client.py  unit tests with httpx.MockTransport
```

Dependencies: `httpx` and `pydantic` only. No sqlalchemy/qdrant/torch. Importable in any Python ≥3.10 project.

### `PalaceClient` interface (slice 1)

```python
class PalaceClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,           # forward-compat; auth lands later
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,  # for test injection
    ) -> None: ...

    async def __aenter__(self) -> "PalaceClient": ...
    async def __aexit__(self, *exc) -> None: ...
    async def aclose(self) -> None: ...

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
    ) -> list[Memory]: ...

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
        source: str | None = None,
    ) -> Memory: ...

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[ScoredMemory]: ...

    async def get(self, memory_id: str) -> Memory: ...
    async def update(self, memory_id: str, **fields) -> Memory: ...
    async def delete(self, memory_id: str) -> None: ...

    async def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        metadata: dict | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]: ...

    async def delete_all(
        self,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> int: ...   # returns count deleted

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[Memory]: ...

    # ---- sessions ----
    async def create_session(self, user_id: str, title: str | None = None) -> Session: ...
    async def get_session(self, session_id: str) -> SessionWithMessages: ...
    async def add_message(self, session_id: str, user_id: str, role: str, content: str) -> Message: ...
    async def update_session(self, session_id: str, **fields) -> Session: ...
    async def delete_session(self, session_id: str) -> None: ...

    # ---- context ----
    async def assemble_context(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        max_memories: int = 10,
        max_messages: int = 20,
    ) -> Context: ...

    # ---- health ----
    async def health(self) -> dict: ...
```

### Errors

```python
# palace_client/exceptions.py
class PalaceError(Exception):
    status_code: int | None
    message: str
    payload: dict | None

class PalaceNotFound(PalaceError):    # 404
    pass

class PalaceTransport(PalaceError):   # network/timeout, no HTTP status reached
    pass
```

Any other 4xx/5xx raises `PalaceError`. The client never silently swallows errors.

### Wire types

`palace_client.models` defines `Memory`, `Session`, `Message`, `ScoredMemory`, `Context`, `SessionWithMessages` as Pydantic models that mirror Palace's responses 1:1. Datetimes parsed to tz-aware `datetime`. No field renaming, no enum coercion.

### Client tests

Unit tests use `httpx.MockTransport` — no live server. Each test asserts: (a) the request URL/body matches the wire contract, (b) the response parses into the right model, (c) error paths raise the right exception class. ~10 tests, ~1s.

---

## mypalclara integration recipe (reference)

`examples/mypalclara_router.py` is committed to this repo as the canonical reference. mypalclara's eventual PR copies it into `mypalclara/core/memory/routed.py`, adapts the imports, and replaces every `from mypalclara.core.memory import PALACE` call site.

### Shape — explicit pass-throughs (per D6)

Every method on the embedded `ClaraMemory` and `MemoryManager` gets an explicit entry in the router. Slice-1 routable methods branch on `USE_PALACE_SERVICE`; everything else delegates to the embedded singleton with a one-line `return getattr(_EMBEDDED, ...)(...)`. No `__getattr__` fallthrough.

```python
# examples/mypalclara_router.py
"""
Reference router for mypalclara: per-method delegation between remote
Palace (HTTP) and the embedded ClaraMemory + MemoryManager.

Slice 1 routes: add, search, get_all, delete_all, get, delete, update.
Everything else listed below as explicit pass-through to the embedded
implementation; future slices replace those one-liners with branches.
"""

import os
import asyncio
from palace_client import PalaceClient

USE_PALACE_SERVICE = os.getenv("USE_PALACE_SERVICE", "false").lower() == "true"
PALACE_SERVICE_URL = os.getenv("PALACE_SERVICE_URL", "http://localhost:8000")
PALACE_API_KEY     = os.getenv("PALACE_API_KEY")

# Embedded fallbacks (existing in-process singletons)
from mypalclara.core.memory import PALACE as _EMBEDDED_PALACE
from mypalclara.core.memory_manager import MemoryManager as _EmbeddedMM

_REMOTE: PalaceClient | None = None

def _remote() -> PalaceClient:
    global _REMOTE
    if _REMOTE is None:
        _REMOTE = PalaceClient(base_url=PALACE_SERVICE_URL, api_key=PALACE_API_KEY)
    return _REMOTE


async def _maybe_await(value):
    """ClaraMemory is sync; PalaceClient is async. This adapter is async, so
    callers always `await` the router. We awaitify sync results."""
    if asyncio.iscoroutine(value):
        return await value
    return value


class RoutedPalace:
    """Looks like ClaraMemory; explicit per-method routing."""

    # ---- Slice 1: remote-eligible ----
    async def add(self, messages, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().add(messages, user_id, **kw)
        return await _maybe_await(_EMBEDDED_PALACE.add(messages, user_id=user_id, **kw))

    async def search(self, query, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().search(query, user_id=user_id, **kw)
        return await _maybe_await(_EMBEDDED_PALACE.search(query, user_id=user_id, **kw))

    async def get_all(self, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().get_all(user_id=user_id, **kw)
        return await _maybe_await(_EMBEDDED_PALACE.get_all(user_id=user_id, **kw))

    async def delete_all(self, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().delete_all(user_id, **kw)
        return await _maybe_await(_EMBEDDED_PALACE.delete_all(user_id=user_id, **kw))

    async def get(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().get(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.get(memory_id))

    async def delete(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().delete(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.delete(memory_id))

    async def update_memory_visibility(self, memory_id, visibility):
        # Slice 2+ candidate; embedded for now.
        return await _maybe_await(_EMBEDDED_PALACE.update_memory_visibility(memory_id, visibility))

    async def history(self, memory_id):
        # Slice 2+ candidate; embedded for now.
        return await _maybe_await(_EMBEDDED_PALACE.history(memory_id))

    # ---- Sub-objects: embedded only in slice 1 ----
    @property
    def episode_store(self):
        return _EMBEDDED_PALACE.episode_store

    @property
    def graph(self):
        return _EMBEDDED_PALACE.graph

    @property
    def embedding_model(self):
        # Slice 2 may add POST /v1/embeddings to enable a remote proxy here.
        return _EMBEDDED_PALACE.embedding_model


class RoutedMemoryManager:
    """Looks like MemoryManager; every method explicit pass-through to embedded
    in slice 1. Branches added in slices 3-5 as endpoints land."""

    @classmethod
    def get_instance(cls):
        return _EmbeddedMM.get_instance()

    # Session methods — phase 1 already exposes equivalents on Palace; keeping
    # embedded for now to avoid touching mypalclara's DB session lifecycle.
    async def get_or_create_session(self, db, *args, **kw):
        return _EmbeddedMM.get_instance().get_or_create_session(db, *args, **kw)

    async def get_thread(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_thread(db, thread_id)

    async def get_recent_messages(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_recent_messages(db, thread_id)

    async def store_message(self, db, *args, **kw):
        return _EmbeddedMM.get_instance().store_message(db, *args, **kw)

    async def update_thread_summary(self, db, thread):
        return _EmbeddedMM.get_instance().update_thread_summary(db, thread)

    # Memory retrieval & writing
    async def fetch_context(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_context(*args, **kw)

    async def add_to_palace(self, *args, **kw):
        return _EmbeddedMM.get_instance().add_to_palace(*args, **kw)

    # Prompt building
    def build_prompt(self, *args, **kw):
        return _EmbeddedMM.get_instance().build_prompt(*args, **kw)

    def build_prompt_layered(self, *args, **kw):
        # Slice 5 candidate.
        return _EmbeddedMM.get_instance().build_prompt_layered(*args, **kw)

    # FSRS dynamics — slice 3
    def get_memory_dynamics(self, memory_id, user_id):
        return _EmbeddedMM.get_instance().get_memory_dynamics(memory_id, user_id)

    def promote_memory(self, memory_id, user_id, grade, signal_type):
        return _EmbeddedMM.get_instance().promote_memory(memory_id, user_id, grade, signal_type)

    def demote_memory(self, memory_id, user_id, reason):
        return _EmbeddedMM.get_instance().demote_memory(memory_id, user_id, reason)

    # Reflection — slice 4
    async def reflect_on_session(self, messages, user_id, session_id):
        return _EmbeddedMM.get_instance().reflect_on_session(messages, user_id, session_id)

    # Intentions — slice 4
    def set_intention(self, *args, **kw):
        return _EmbeddedMM.get_instance().set_intention(*args, **kw)

    def check_intentions(self, *args, **kw):
        return _EmbeddedMM.get_instance().check_intentions(*args, **kw)

    # ... (every public MemoryManager method gets an explicit one-line entry)


PALACE = RoutedPalace()
MM = RoutedMemoryManager
```

The full method list comes from the surface map. The implementation plan will enumerate every method explicitly.

### Consumption pattern for mypalclara

```bash
# In mypalclara repo:
pip install git+https://github.com/BangRocket/palace-memory.git@<sha>#subdirectory=palace_client
# Copy examples/mypalclara_router.py → mypalclara/core/memory/routed.py
# Replace `from mypalclara.core.memory import PALACE` with the routed version
# at every call site (one-time mechanical PR).

# Then runtime toggle:
export USE_PALACE_SERVICE=true
export PALACE_SERVICE_URL=http://palace.local:8000
```

---

## Repo layout after slice 1

```
palace-memory/
├── palace/                    (mostly unchanged)
│   ├── api/memories.py        + batch, list, delete-all routes
│   ├── memory_service.py      + create_batch, list_filtered, delete_for_user
│   ├── models.py              metadata column promoted to JSONB
│   └── ...
├── palace_client/             NEW
├── examples/
│   └── mypalclara_router.py   NEW
├── tests/
│   ├── (existing mock tests, untouched)
│   └── integration/           NEW
│       ├── conftest.py        TestContainers fixtures
│       ├── test_memories_live.py
│       ├── test_sessions_live.py
│       └── test_client_e2e.py palace_client → live Palace
├── pyproject.toml             + pytest marker "integration"
├── docs/
│   ├── SPEC.md                (unchanged)
│   ├── plan.md                (unchanged)
│   └── superpowers/specs/
│       └── 2026-05-03-palace-phase-2-design.md   THIS DOC
└── README.md                  + drop-in mode + integration tests sections
```

---

## Testing layers after slice 1

| Layer | Command | Expected speed | Coverage |
|-------|---------|----------------|----------|
| Mocks (existing phase 1) | `pytest` | ~2s | Routes wired, response shapes |
| `palace_client` unit tests | `pytest palace_client/` | ~1s | MockTransport — request bodies + response parsing + error mapping |
| Integration (new, opt-in) | `pytest -m integration` | ~30-60s | Live postgres+qdrant per session via TestContainers; CRUD/search/list/delete-all + client-vs-server e2e |

CI is out of scope for slice 1.

---

## Slice 1 commit plan

The implementation plan refines this; here's the rough shape:

1. `feat(models): promote Memory.metadata_json to JSONB`
   - Schema-only. PR description and commit message both flag the destructive recreate-table requirement for any live DB.
2. `feat(api): batch create, filtered list, delete-by-user endpoints`
   - Three routes + service methods + mock tests for each.
3. `feat(client): introduce palace_client package`
   - Full async client + exceptions + Pydantic wire models + MockTransport unit tests.
4. `test(integration): TestContainers-backed end-to-end suite`
   - `pytest -m integration` opt-in marker, postgres+qdrant container fixtures, initial e2e tests covering all phase-1 + slice-1 endpoints.
5. `docs(examples): mypalclara router reference + README updates`
   - `examples/mypalclara_router.py` with explicit pass-throughs for every ClaraMemory + MemoryManager method, plus README "Drop-in mode" and "Integration tests" sections.

Each commit is independently reviewable. #1 is the only schema change.

---

## Phase 2 roadmap (slices 2-5)

Captured here because "we want them all eventually" — but each slice gets its own design doc and implementation plan when its turn comes.

| Slice | Scope | Approx size | Depends on |
|-------|-------|-------------|------------|
| **2 — Episodes** | `Episode` model, `POST /v1/episodes` (LLM extraction), `GET /v1/episodes/recent`, `GET /v1/episodes/search`, `GET /v1/episodes/active-arcs`. Adds LLM client to the request path. | 5-7 days | Slice 1 (client, integration test infra) |
| **3 — FSRS dynamics** | `MemoryDynamics` + `MemoryAccessLog` models, FSRS-6 scoring port, `POST /v1/memories/{id}/promote`, `POST /v1/memories/{id}/demote`, `GET /v1/memories/{id}/dynamics`. Self-contained math, no LLM. | 4-5 days | Slice 1 |
| **4 — Reflection + intentions** | `POST /v1/reflection/session`, intention CRUD, `POST /v1/intentions/check`. LLM-heavy. | 5-6 days | Slices 2 + 3 (episodes + dynamics) |
| **5 — Layered retrieval + smart ingestion** | Merge `key → semantic → episodic → graph` retrieval; dedup/supersedence on `add`. Replaces the slice-1 "verbatim" behavior of `infer=True`. | 4-5 days | Slices 2 + 3 (needs episodic + dynamics to be meaningful) |

Held for **phase 3**: graph memory (FalkorDB container), Redis embedding cache, gRPC, auth, multi-tenancy, Helm chart, PyPI publishing of `palace_client`.

---

## Risks tracked

| Risk | Mitigation |
|------|------------|
| **JSONB migration on a populated DB.** Phase 1 has no Alembic; slice 1 introduces JSONB. | Slice 1 has no live data; PR description and migration commit both flag "back up first." Alembic added in a later slice when schema changes start mattering. |
| **httpx + asyncio resource leaks in integration tests.** TestContainers + httpx + pytest-asyncio teardown is fragile. | Integration `conftest.py` explicitly `await client.aclose()` and `addfinalizer` for every container. Test with a deliberate leak check (e.g. `gc.collect()` + open-fd count) once. |
| **`palace_client` versioning drift.** No PyPI yet; mypalclara pins by git SHA. | Slice 1 README documents the pin pattern explicitly. Phase 3 adds PyPI release flow. |
| **`infer=True` semantics changing under callers' feet.** Slice 1 ignores `infer`; slice 5 makes it meaningful. | D7: `infer` defaults to `False` on the wire so behavior change is opt-in by callers, not silent. |
| **Sync/async boundary in the mypalclara router.** ClaraMemory is sync; PalaceClient is async; the router is async. | `_maybe_await` helper handles both; all router methods are `async def` so callers always `await`. The mypalclara mechanical-PR step makes every existing call site `await`-aware. |

---

## Out of scope for this spec

- The mypalclara PR itself (lives in mypalclara repo).
- gRPC API (phase 3).
- Authentication and authorization (phase 3).
- Multi-tenancy (phase 3).
- PyPI publishing of `palace_client` (phase 3, when there's a second consumer).
- Migration of existing mypalclara data into Palace's postgres (phase 3, follows graph + episode parity).
- Kubernetes/Helm (phase 3).

---

## Done criteria for slice 1

- [ ] All three new endpoints implemented, mock-tested, and integration-tested against live postgres + qdrant.
- [ ] `palace_client` package installable via `pip install -e ./palace_client` and via `pip install git+...#subdirectory=palace_client`.
- [ ] All `palace_client` methods covered by MockTransport unit tests.
- [ ] `tests/integration/test_client_e2e.py` round-trips every slice-1 method against a live Palace.
- [ ] `examples/mypalclara_router.py` lists every public ClaraMemory + MemoryManager method explicitly (per D6).
- [ ] README updated with "Drop-in mode for mypalclara" and "Integration tests" sections.
- [ ] Phase-2 branch merged to main with all five commits from the slice-1 commit plan.
