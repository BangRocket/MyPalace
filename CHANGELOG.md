# Changelog

All notable changes to Palace are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and Palace adheres to
[Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-05-04

Operational maturity release. Six slices since 0.2.

### Added — phase 4 (operational maturity)

- **Alembic migrations (slice 1)** — `alembic/` directory wired with
  async env.py reading `PALACE_DATABASE_URL`. Baseline migration captures
  the entire post-phase-3 schema; 0002 adds composite `(tenant_id, user_id)`
  indexes for hot read paths. `init_db()` auto-stamps fresh DBs at the
  latest revision so future `alembic upgrade head` calls have a known
  starting point. Pre-Alembic upgrades run `alembic stamp` once.
- **Observability (slice 2)** — Prometheus `/metrics` endpoint (always
  on, public, low-cardinality route normalization). Optional OpenTelemetry
  via `[otel]` extra + `PALACE_OTLP_ENDPOINT` (auto-instruments FastAPI +
  httpx). Structlog with `pretty` (dev) and `json` (prod) formats; every
  request gets a `request_id` (read from header or generated) bound to
  log contextvars and echoed in the response.
- **Background workers (slice 3)** — Postgres-backed job queue using
  `SELECT ... FOR UPDATE SKIP LOCKED`. New columns: `leased_until`,
  `attempts`, `payload_json`. Built-in handlers: `reflection`, `synthesis`.
  Custom handlers via `register_handler`. `python -m palace.workers.runner`
  starts the worker; multiple workers safely share the queue.
- **Per-user rate limits (slice 4)** — Optional Redis sliding-window
  limiter scoped to (tenant, key, user). Separate buckets for `default`
  (120/min) and `search`/`context` (60/min). New `unlimited` scope opts
  out for trusted server-to-server keys. 429 response includes
  `Retry-After` header. Fails open if Redis is unreachable.
- **WebSocket subscriptions (slice 5)** — `/v1/events?api_key=...&topics=...`.
  Per-tenant Redis pub/sub channels (in-process fallback when Redis
  unset). At-most-once delivery; slow subscribers drop events. Memory
  create/update/delete/supersede publish events; episode/intention/arc
  publishers wire in slice 6.
- **Graph → retrieval (slice 6)** — `LayeredContextRequest` grows
  `include_graph: bool = False`. When true and the graph layer is
  configured, `/v1/context/layered` returns an additional
  `l3_graph_context` slot with 1-hop neighbors of the L2 memories
  (deduped, capped at `graph_max_neighbors=50`). Defaults preserve
  backwards compatibility — existing callers see the old shape.

### Notes

- gRPC mirror of remaining surfaces (sessions, episodes, etc.) and
  cross-tenant analytics are deliberately deferred — neither has a
  concrete consumer yet.

## [0.2.0] — 2026-05-04

First production-readiness release. Five major feature slices since 0.1.

### Added — phase 3 (production readiness)

- **Auth (slice 1)** — API key middleware on every `/v1/*`. Three explicit
  scopes: `read` / `write` / `admin` (admin does NOT auto-grant lower).
  `/v1/admin/keys` for issuance; `PALACE_BOOTSTRAP_ADMIN_KEY` env mints
  the first admin key on startup. `PALACE_AUTH_DISABLED=true` for tests.
- **Multi-tenancy (slice 2)** — `tenant_id` column on every user-data table;
  per-tenant Qdrant collections (`palace_memories_<tenant>`); API keys
  bound to a tenant on creation; cross-tenant admin keys for support /
  migration. `/v1/admin/tenants` CRUD.
- **Graph (slice 3)** — Optional FalkorDB layer. Memory / Episode / Arc
  creates write nodes asynchronously; supersessions write `SUPERSEDES`
  edges. `GET /v1/graph/neighbors` for n-hop traversal.
  `PALACE_FALKORDB_URL` unset = no-op.
- **Cache (slice 4)** — Optional Redis read-through cache for
  `/v1/context/layered` and `/v1/memories/search`. Tenant-prefixed keys,
  TTL 60s default. Invalidation on memory writes.
  `PALACE_REDIS_URL` unset = no-op.
- **gRPC (slice 5)** — Optional second transport on `PALACE_GRPC_PORT`.
  Scope: `MemoryService` (Create / Get / Delete / Search / List). Auth
  via `x-palace-key` metadata, scope rules mirror HTTP. Other surfaces
  ride HTTP for now.
- **PyPI publishing (slice 6)** — `palace-memory` and `palace-client` on
  PyPI; Docker image `bangrocket/palace:0.2.0`. GitHub Actions release
  workflow.

### Added — phase 2 (feature parity with mypalclara)

- **Episodes + reflection** — Episode storage in Qdrant; LLM-driven
  session reflection. Async via `job_service` or sync via `?mode=sync`.
- **Narrative arcs** — Arc synthesis from episode history; `/v1/synthesis/narratives`.
- **FSRS-6 dynamics** — Promote / demote / score memories with FSRS-6
  spaced-repetition state. `/v1/memories/{id}/promote|demote|score`.
- **Intentions** — Future-trigger reminders with 4 deterministic matchers
  (keyword / topic / time / context). `/v1/intentions` CRUD;
  `/v1/intentions/check`.
- **Layered context** — `/v1/context/layered` returns L1 (user profile)
  and L2 (relevant context) slots, FSRS-reranked.
- **Smart ingestion** — `POST /v1/memories/batch?infer=true` runs LLM
  extraction + vector dedup + auto-supersede on contradictions.
- **Manual supersede** — `POST /v1/memories/{id}/supersede` with audit
  history at `/v1/memories/{id}/supersedes`.
- **palace-client subpackage** — Standalone async HTTP client mirroring
  the full Palace surface.

### Changed

- `MemoryService.search` now filters by tenant_id (defense in depth even
  with per-tenant Qdrant collections).
- `palace_client.PalaceClient` constructor switched API-key header from
  `Authorization: Bearer` to `X-Palace-Key`.

### Notes

- **Alembic** is deferred to a follow-up. v0.2.0 deployments to fresh
  databases work via `init_db()` on lifespan startup. Upgrades from a
  pre-0.2.0 deployment with data require manual schema migration —
  contact the maintainers for the migration plan.

## [0.1.0] — 2026-05-03

Initial standalone release. Memory CRUD + semantic search + sessions +
context assembly. Postgres + Qdrant. No auth, no multi-tenancy, no
graph, no cache.
