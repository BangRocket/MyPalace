# Palace Memory Service

[![PyPI version](https://img.shields.io/pypi/v/palace-memory)](https://pypi.org/project/palace-memory/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A standalone, lightweight memory service for AI assistants. Stores facts, preferences, and conversation history; serves them back via semantic search and LLM-ready context blocks.

Extracted from [mypalclara](https://github.com/BangRocket/mypalclara)'s Palace memory system as an independent microservice with no `mypalclara` dependency.

---

## What it does

- **Memory CRUD + semantic search** — embed text, store in Qdrant, retrieve by similarity
- **Session/message persistence** — conversation threads with PostgreSQL
- **Context assembly** — combine relevant memories + recent messages into a single payload for LLM prompts
- **Pluggable embeddings** — HuggingFace (local) or OpenAI (API)
- **Pluggable LLM backend** — any OpenAI-compatible chat completion endpoint (OpenRouter, OpenAI, etc.)

### What it does *not* do (v1, by design)

No graph memory, no FSRS spaced-repetition, no reflection workers, no gRPC, no multi-tenancy. See `docs/SPEC.md` for the v1 scope and `docs/plan.md` for the long-range vision.

Phase 2 added: episodes + reflection, narrative arcs, FSRS-6 dynamics, intentions, layered context, smart ingestion, supersede.

Phase 3 in progress: API-key auth (slice 1, done) → multi-tenancy → graph (FalkorDB) → Redis cache → gRPC → PyPI publish.

---

## Auth (phase 3 slice 1)

Every `/v1/*` endpoint requires a valid API key in the `X-Palace-Key` header. `/health`, `/docs`, `/redoc`, `/openapi.json` remain public.

**Three scopes:**
- `read` — `GET /v1/*`, `POST /v1/memories/search`, `/list`, `/episodes/search`, `/intentions/check`, `/intentions/format`, `/context/*`
- `write` — everything else under `/v1/*`
- `admin` — `/v1/admin/*` and `/v1/maintenance/*`

Scopes are explicit: `admin` does **not** auto-grant `write` or `read`. When you mint a key, list every scope it should have.

### Bootstrap an admin key

Set `PALACE_BOOTSTRAP_ADMIN_KEY` to a value of the form `pk_live_<32 alphanumeric chars>`. On lifespan startup, if no admin key exists, Palace inserts a row with `read+write+admin` scopes. Idempotent.

```bash
export PALACE_BOOTSTRAP_ADMIN_KEY=pk_live_$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)
echo "$PALACE_BOOTSTRAP_ADMIN_KEY"   # save this — Palace doesn't log it
```

### Mint additional keys

```bash
curl -X POST http://localhost:8000/v1/admin/keys \
  -H "X-Palace-Key: $PALACE_BOOTSTRAP_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label": "mypalclara-prod", "scopes": ["read", "write"]}'
# response: {"data": {"key_id": "...", "plaintext_key": "pk_live_...", ...}}
```

The plaintext is returned **once**. Palace stores only a bcrypt hash plus an 8-char prefix index for lookup.

### Disable auth (development / tests only)

```bash
export PALACE_AUTH_DISABLED=true
```

The mock test suite sets this automatically; live integration tests opt back in per-test.

---

## Multi-tenancy (phase 3 slice 2)

Every row in every user-data table carries a `tenant_id`. API keys are bound to a tenant on creation; the middleware sets `request.state.auth.tenant_id` from the key, and every service query filters by it. Qdrant collections are per-tenant: `palace_memories_<tenant_id>`, `palace_episodes_<tenant_id>`.

A `default` tenant is created on first boot (`PALACE_DEFAULT_TENANT_ID` to override). Single-tenant deployments work zero-config.

### Tenant ID format

`^[a-z0-9_]{1,32}$` — lowercase alphanumeric + underscore, max 32 chars. Anything else → 400.

### Mint a tenant-bound key

```bash
# Create a tenant
curl -X POST http://localhost:8000/v1/admin/tenants \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"id": "acme", "label": "Acme Corp"}'

# Issue a key bound to that tenant
curl -X POST http://localhost:8000/v1/admin/keys \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"label": "acme-prod", "scopes": ["read","write"], "tenant_id": "acme"}'
```

### Cross-tenant admin keys

For migrations or support, mint a key with `cross_tenant: true`:

```bash
curl -X POST http://localhost:8000/v1/admin/keys \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"label": "support", "scopes": ["read","write","admin"], "cross_tenant": true}'
```

The bootstrap admin key (from `PALACE_BOOTSTRAP_ADMIN_KEY`) is a cross-tenant key by default.

### Migrations (phase 4 slice 1)

Alembic now manages schema. `init_db()` still creates tables on first boot for zero-config dev, AND stamps the latest revision so future `alembic upgrade head` calls know where to start.

```bash
# Fresh install — nothing to do; lifespan startup handles it.
.venv/bin/uvicorn palace.main:app

# Pre-phase-4 install with existing data — stamp once, then upgrade as usual:
.venv/bin/alembic stamp 2026_05_04_0001_baseline
.venv/bin/alembic upgrade head

# Day-to-day after a new migration lands:
.venv/bin/alembic upgrade head

# Generate a new migration from model changes:
.venv/bin/alembic revision --autogenerate -m "add foo column"
```

DB URL is read from `PALACE_DATABASE_URL` (no need to set `sqlalchemy.url` in `alembic.ini`).

---

## Observability (phase 4 slice 2)

### Prometheus metrics

`/metrics` exposes Prometheus exposition format. Always on, always public (k8s scrapers need that — lock down via your ingress if necessary).

Counters:
- `palace_http_requests_total{method, route, status_class}`
- `palace_http_request_duration_seconds{method, route}` (histogram)
- `palace_cache_hits_total{namespace}`, `palace_cache_misses_total{namespace}`
- `palace_graph_writes_total{kind}`, `palace_graph_failures_total`
- `palace_jobs_total{kind, outcome}` (populated by phase-4 slice 3)

Routes are normalized — UUIDs and long IDs become `{id}` so Prometheus label cardinality stays bounded.

### OpenTelemetry traces

Optional. Set `PALACE_OTLP_ENDPOINT=http://otel-collector:4317` and install the optional extra:

```bash
pip install "palace-memory[otel]"
```

Auto-instruments FastAPI + httpx. Service name defaults to `palace-memory` (override via `PALACE_OTLP_SERVICE_NAME`). No-op if either the env var is unset or the SDK isn't installed.

### Structured logs

`structlog` configured at lifespan startup. Two modes via `PALACE_LOG_FORMAT`:
- `pretty` (default) — colored console output, dev-friendly
- `json` — newline-delimited JSON, production-ready

Every request gets a `request_id` (read from `X-Request-ID` header if present, else a fresh uuid4). It's bound to structlog's contextvars so every log line in the request scope carries it. The same `X-Request-ID` is echoed back on the response.

---

## Background workers (phase 4 slice 3)

Postgres-backed job queue using `SELECT ... FOR UPDATE SKIP LOCKED`. Built-in handlers cover `reflection` (episode reflection from a session) and `synthesis` (narrative arc rollup). The web process can opt to enqueue jobs and let a separate worker process pick them up.

```bash
# In one terminal: the web server
.venv/bin/uvicorn palace.main:app --port 8000

# In another: one or more workers
.venv/bin/python -m palace.workers.runner
# (Run multiple — SKIP LOCKED gives them safe concurrency)
```

### Knobs

- `PALACE_WORKER_POLL_INTERVAL=1.0` — seconds between polls when idle
- `PALACE_WORKER_LEASE_SECONDS=60` — max time a worker holds a claim before another can re-take it
- `PALACE_WORKER_MAX_ATTEMPTS=3` — failures past this mark `status=failed`

### Custom handlers

```python
from palace.workers import register_handler

async def my_handler(payload: dict, tenant_id: str) -> dict:
    return {"processed": payload}

register_handler("my_kind", my_handler)
# Then enqueue:
from palace.workers import enqueue
await enqueue(kind="my_kind", user_id="u1", payload={"x": 1}, tenant_id="default")
```

The runner picks up `my_kind` automatically once the registry is populated.

---

## Rate limits (phase 4 slice 4)

Optional sliding-window rate limiter, scoped to (tenant, key, user). Requires Redis.

```bash
export PALACE_RATE_LIMIT_ENABLED=true
export PALACE_REDIS_URL=redis://localhost:6379
export PALACE_RATE_LIMIT_DEFAULT=120     # req/min for most endpoints
export PALACE_RATE_LIMIT_SEARCH=60       # tighter bucket for /search + /context
```

Disabled by default. When disabled, the middleware is a fast no-op. When enabled but Redis is unreachable, it **fails open** (logs a warning, lets the request through) — Palace stays available even when the limiter can't.

### Bypass with `unlimited` scope

Trusted server-to-server keys can opt out by adding the `unlimited` scope at issuance time:

```bash
curl -X POST http://localhost:8000/v1/admin/keys \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"label":"trusted-svc","scopes":["read","write","unlimited"]}'
```

### Response shape on 429

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{"error": {"code": "rate_limited", "message": "Too many requests in 60s window: 121/120", "retry_after_seconds": 60}}
```

---

## Graph layer (phase 3 slice 3)

Optional FalkorDB integration. When `PALACE_FALKORDB_URL` is set, every memory / episode / arc create writes a node into the per-tenant graph (`palace_<tenant_id>`), and every supersession writes a `SUPERSEDES` edge. Writes are fire-and-forget — graph failures never break the primary write.

```bash
# FalkorDB ships as a Redis module:
podman run -d --name palace-falkor -p 6379:6379 docker.io/falkordb/falkordb:latest
export PALACE_FALKORDB_URL=redis://localhost:6379
```

Without the env var, the graph layer is a no-op and `/v1/graph/*` returns 503.

### Schema

```
(:Memory {id, user_id, agent_id, content, memory_type, importance})
(:Episode {id, user_id, summary, significance, timestamp})
(:Arc {id, user_id, title, status})

(Memory)-[:SUPERSEDES]->(Memory)
(Episode)-[:PARTICIPATES_IN]->(Arc)
```

### Querying neighbors

```bash
curl "http://localhost:8000/v1/graph/neighbors?node_id=<memory_id>&depth=2&edge_type=SUPERSEDES" \
  -H "X-Palace-Key: $KEY"
# → {"data": {"nodes": [...], "edges": [...]}, "meta": {...}}
```

Depth is capped at 3 hops; edge_type filter is optional. No raw Cypher passthrough — the only graph API surface is `/v1/graph/neighbors`.

---

## Cache (phase 3 slice 4)

Optional Redis read-through cache for `/v1/context/layered` and `/v1/memories/search`. Keys are hashed `(tenant_id, namespace, params)`; TTL defaults to 60s. On memory create/update/delete, all matching tenant cache entries are invalidated.

```bash
# FalkorDB and the cache can share the same Redis instance:
export PALACE_REDIS_URL=redis://localhost:6379
# Optional knobs:
export PALACE_CACHE_TTL_SEARCH=60   # seconds
export PALACE_CACHE_TTL_GET=300
# Disable without unsetting URL (e.g. tests):
export PALACE_CACHE_DISABLED=true
```

Without `PALACE_REDIS_URL`, every read goes straight to Postgres + Qdrant.

Cache failures degrade to misses — Palace stays correct, just slower.

---

## gRPC transport (phase 3 slice 5)

Optional second transport alongside REST. **Scope this release: MemoryService only** — Create / Get / Delete / Search / List. Other surfaces (sessions, episodes, arcs, etc.) ride HTTP via `PalaceClient`. Full mirror is a phase 4 follow-up.

```bash
export PALACE_GRPC_PORT=50051
.venv/bin/uvicorn palace.main:app --port 8000
# → starts FastAPI on :8000 AND gRPC on :50051
```

Auth uses the same X-Palace-Key, sent as gRPC metadata `x-palace-key`. Scope rules are identical to HTTP.

```python
from palace_client.grpc import PalaceGrpcClient

async with PalaceGrpcClient("localhost:50051", api_key="pk_live_...") as client:
    mem = await client.create(user_id="u1", content="hello via gRPC")
    results = await client.search(query="hello", limit=5)
```

### Regenerating stubs

```bash
python -m grpc_tools.protoc -I=proto \
    --python_out=palace/grpc/_generated \
    --grpc_python_out=palace/grpc/_generated \
    proto/palace.proto
# Then re-apply the local import fix in palace_pb2_grpc.py:
#   sed -i '' 's/^import palace_pb2/from palace.grpc._generated import palace_pb2/' \
#     palace/grpc/_generated/palace_pb2_grpc.py
```

---

## Install

### From PyPI (server)

```bash
pip install palace-memory
```

### From PyPI (client only — for AI apps that talk to a remote Palace)

```bash
pip install palace-client
# Optional gRPC transport:
pip install "palace-client[grpc]"
```

### Docker

```bash
docker pull bangrocket/palace:latest
docker run -p 8000:8000 \
  -e PALACE_DATABASE_URL=postgresql+asyncpg://palace:palace@host/palace \
  -e QDRANT_URL=http://host:6333 \
  -e PALACE_BOOTSTRAP_ADMIN_KEY=pk_live_$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32) \
  bangrocket/palace:latest
```

## Quick start (development)

```bash
# 1. Start postgres + qdrant (docker or podman)
docker-compose up -d postgres qdrant
# or:  podman run -d --name palace-postgres -p 5442:5432 \
#         -e POSTGRES_USER=palace -e POSTGRES_PASSWORD=palace -e POSTGRES_DB=palace \
#         docker.io/library/postgres:16-alpine
#      podman run -d --name palace-qdrant -p 6333:6333 docker.io/qdrant/qdrant:latest

# 2. Install (Python 3.12)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 3. Configure
cp .env.example .env

# 4. Run
.venv/bin/uvicorn palace.main:app --reload --port 8000
```

Or fully containerized: `docker-compose up --build`.

API docs at <http://localhost:8000/docs>.

### Smoke test

```bash
# Store a memory
curl -X POST http://localhost:8000/v1/memories \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","content":"User loves dark mode and uses Vim daily","memory_type":"preference"}'

# Semantic search
curl -X POST http://localhost:8000/v1/memories/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"editor preferences","user_id":"u1","limit":5}'

# Assemble context for an LLM prompt
curl -X POST http://localhost:8000/v1/context \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","query":"what does the user prefer?","max_memories":5}'
```

---

## API

All responses use the envelope `{ "data": ..., "meta": { "count": N, "took_ms": N } }`. Errors return HTTP 4xx/5xx with FastAPI's default body.

### Memories

| Method | Path | Body |
|---|---|---|
| `POST` | `/v1/memories` | `{ user_id, content, memory_type?, agent_id?, source?, importance?, metadata? }` |
| `POST` | `/v1/memories/search` | `{ query, user_id?, agent_id?, memory_type?, limit?, min_score? }` |
| `GET`  | `/v1/memories/{id}` | — |
| `PATCH`| `/v1/memories/{id}` | `{ content?, memory_type?, importance?, metadata? }` |
| `DELETE`| `/v1/memories/{id}` | — |
| `GET`  | `/v1/users/{user_id}/memories?limit=50` | — |

`memory_type` is a free-form string; conventional values: `semantic`, `episodic`, `preference`, `fact`.

### Sessions

| Method | Path | Body |
|---|---|---|
| `POST` | `/v1/sessions` | `{ user_id, title? }` |
| `GET`  | `/v1/sessions/{id}` | — (returns session + ordered messages) |
| `POST` | `/v1/sessions/{id}/messages` | `{ user_id, role, content }` |
| `PATCH`| `/v1/sessions/{id}` | `{ title?, summary? }` |
| `DELETE`| `/v1/sessions/{id}` | — (cascades to messages) |

### Context

| Method | Path | Body |
|---|---|---|
| `POST` | `/v1/context` | `{ user_id, query, session_id?, max_memories?, max_messages? }` |

### Health

| Method | Path |
|---|---|
| `GET` | `/health` |

---

## Configuration

All settings come from environment variables (or `.env`).

| Variable | Default | Notes |
|---|---|---|
| `PALACE_DATABASE_URL` | `postgresql+asyncpg://palace:palace@localhost/palace` | asyncpg driver required |
| `QDRANT_URL` | `http://localhost:6333` | |
| `QDRANT_COLLECTION` | `palace_memories` | created on startup if missing |
| `EMBEDDING_PROVIDER` | `huggingface` | `huggingface` or `openai` |
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | for HF; pass an OpenAI model name when provider is openai |
| `HF_TOKEN` | — | optional, for gated models |
| `OPENAI_API_KEY` | — | required if `EMBEDDING_PROVIDER=openai` |
| `LLM_PROVIDER` | `openrouter` | `openrouter` or `openai` |
| `LLM_API_KEY` | — | required for any LLM call |
| `LLM_MODEL` | `openai/gpt-4o-mini` | OpenRouter-style or OpenAI model id |
| `LOG_LEVEL` | `INFO` | |

---

## Architecture

```
palace/
├── main.py              FastAPI app + lifespan (creates tables, ensures Qdrant collection)
├── config.py            Pydantic Settings (.env aware)
├── models.py            SQLModel tables: Memory, Session, Message
├── database.py          Async SQLAlchemy engine + session factory
├── embeddings.py        EmbeddingProvider protocol + HF and OpenAI impls
├── vector.py            Async Qdrant wrapper (ensure/upsert/query/delete)
├── llm.py               Async chat-completion client (OpenAI-compatible)
├── memory_service.py    CRUD + semantic search; lazy embedder
├── session_service.py   Session + message lifecycle
├── context_service.py   Memory search + recent messages → prompt context
└── api/
    ├── common.py        Pydantic request/response models, ApiResponse envelope
    ├── memories.py      memory routes + users-router for /v1/users/{id}/memories
    ├── sessions.py      session routes
    └── context.py       context route
```

### Behavior notes

- **Create memory** → INSERT into postgres, then embed + UPSERT into Qdrant. Embedding happens *outside* the DB transaction so a slow embedder doesn't hold a row lock.
- **Search** → embed query, Qdrant `query_points` with `user_id`/`agent_id`/`memory_type` filters, then fetch full rows from postgres in one IN-clause. Search bumps `access_count` and `accessed_at` on the returned rows.
- **Update content** → re-embeds and UPSERTs (Qdrant point id == memory id).
- **Delete** → removes the postgres row, then deletes the Qdrant point.

---

## Running tests

```bash
.venv/bin/python -m pytest
```

The test suite uses mocks (no postgres or qdrant required) and covers all 13 routes.

For end-to-end verification, the smoke commands above exercise the whole stack against a live DB + Qdrant.

---

## Platform notes

### macOS x86_64

`torch` is capped at `2.2.2` on macOS x86_64 (Apple deprecated x86 wheels for newer torch). `pyproject.toml` therefore pins `numpy<2` and `transformers<5` to stay ABI-compatible with that torch. If you are on Apple Silicon (`arm64`) or Linux, those pins are still safe — just not strictly required.

If you'd rather avoid the torch dependency entirely, set:

```bash
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

The embedder is loaded lazily, so importing the app no longer triggers a model download.

### Container engines

`docker-compose.yml` works under both Docker Desktop and `podman compose`. With plain `podman run`, see the Quick start above for the equivalent commands.

---

## Drop-in mode for mypalclara (phase 2)

**Phase 2 complete:** 5 slices, ~25 endpoints + 18 client methods. The
mypalclara router routes ~12 of ~18 external callsites; the remaining are
DB-bound or graph (phase 3).

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

### Slice 3 additions: FSRS dynamics

Five more endpoints port mypalclara's FSRS-6 spaced-repetition memory dynamics (per-memory stability/difficulty/retrievability state, access logging, and composite ranking) to remote Palace:

- `POST /v1/memories/{id}/promote` — apply an FSRS review (default `grade=3` / GOOD, `signal_type="used_in_response"`). Auto-creates the dynamics row on first call.
- `POST /v1/memories/{id}/demote` — failure signal (equivalent to `promote(grade=1)`); default `reason="user_correction"`.
- `GET  /v1/memories/{id}/dynamics?user_id=u1` — read the current FSRS state. 404 if no dynamics row.
- `POST /v1/memories/{id}/score` — composite ranking breakdown given the caller's semantic score. Returns `{composite_score, fsrs_score, retrievability, storage_strength}`. Composite formula: `composite = 0.6 * semantic + 0.4 * fsrs_score`, where `fsrs_score = (0.7 * retrievability + 0.3 * storage_strength) * importance_weight`.
- `POST /v1/maintenance/prune-access-logs?retention_days=90` — admin op; deletes old access log rows.

The FSRS-6 math (`palace/dynamics/fsrs.py`) is ported character-for-character from mypalclara, with a deterministic regression net (`tests/test_dynamics.py`) pinning known input -> output values to catch porting drift.

`MM.get_last_retrieved_memory_ids` stays embedded (slice-3 design D4): the HTTP service is stateless between requests, so an in-process cache wouldn't survive across worker processes. The mypalclara router caches retrieved IDs client-side instead.

### Slice 4 additions: intentions

Six endpoints port mypalclara's intentions subsystem — deterministic-trigger reminders that fire when matching keywords, topics, times, or context conditions are detected. **No LLM** in this slice; all matching is purely structural (keyword regex, time comparison, context dict matching, word-overlap fallback for topic).

- `POST   /v1/intentions` — set a new intention (`{user_id, content, trigger_conditions, ...}`).
- `POST   /v1/intentions/check` — evaluate all unfired intentions for a user against a message + context. Returns the fired list (sorted by priority); marks fired and deletes any with `fire_once=true`.
- `POST   /v1/intentions/format` — render fired intentions as a markdown bullet list for system-prompt injection.
- `DELETE /v1/intentions/{id}` — delete a single intention. 404 if not found.
- `GET    /v1/users/{user_id}/intentions?fired={true|false|all}&limit=50` — list intentions for a user.
- `POST   /v1/maintenance/cleanup-intentions` — admin op; deletes intentions whose `expires_at` has passed.

Four trigger types (set via `trigger_conditions["type"]`):

- `keyword` — substring match against `keywords`; optional `regex` and `case_sensitive`.
- `topic` — word-overlap fraction vs. `topic` >= `threshold`; optional `quick_keywords` pre-filter.
- `time` — fires when current UTC time has reached `at` (specific) or `after` (open-ended).
- `context` — matches a dict of `{channel_name, is_dm, time_of_day, day_of_week}`; all configured keys must match.

The `mypalclara_router.py` reference now routes `MM.set_intention`, `MM.check_intentions`, and `MM.format_intentions_for_prompt` when `USE_PALACE_SERVICE=true`.

### Slice 5 additions: layered retrieval + smart ingestion

Three endpoints + an activated flag close out phase 2: multi-tier context assembly, LLM-driven memory extraction with vector dedup + heuristic supersede, and a manual supersede record:

- `POST /v1/context/layered` — multi-tier context assembly. Parallel-fetches L1 (top semantic memories + recent episodes + active arcs) and L2 (query-filtered memories optionally FSRS-reranked + query-filtered episodes), char-budgets each layer, and optionally pulls `recent_messages` from a session. Returns a structured dict (caller composes into prompts; Palace stays generic).
- `POST /v1/memories/{id}/supersede` — manually replace a memory. Creates a new memory and an audit row; demotes the old memory's FSRS state.
- `GET  /v1/memories/{id}/supersedes` — supersession history involving this memory id (either side).
- **Activated:** `infer=true` on `POST /v1/memories/batch` now runs the smart-ingestion pipeline: LLM extracts factual memories from the conversation block; for each candidate, embed + Qdrant-search the nearest existing memory; `score > 0.95` skip as duplicate, `score > 0.75` heuristic contradiction check (auto-supersede when confidence > 0.7, else skip as similar), else write fresh. Response `meta` carries `supersessions` and `skipped` arrays.

The contradiction heuristic is intentionally simple (no LLM in the hot ingestion path): negation-asymmetry plus stemmed token overlap. The LLM extraction is the only LLM call.

`MM.build_prompt_layered`, `MM.smart_ingest`, and `MM.supersede_memory` graduate to remote in `examples/mypalclara_router.py` when `USE_PALACE_SERVICE=true`. Note: the routed `build_prompt_layered` returns a structured `LayeredContext` dict instead of typed Messages — mypalclara's caller must adapt (the routed path drops Discord-specific persona/channel layers per phase-2 design D1).

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

## License

PolyForm Noncommercial 1.0.0
