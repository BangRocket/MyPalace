# Palace Memory Service

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

No graph memory, no FSRS spaced-repetition, no reflection workers, no gRPC, no multi-tenancy, no auth. See `docs/SPEC.md` for the v1 scope and `docs/plan.md` for the long-range vision.

---

## Quick start

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

## License

PolyForm Noncommercial 1.0.0
