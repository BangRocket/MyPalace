# Palace Phase 4 — Master Plan

**Date:** 2026-05-04
**Branch:** `phase-4`
**Goal:** Operational maturity. Make Palace something you can run as a real service: real migrations, real telemetry, real workers, real rate limits, real push events, and the graph layer actually wired into retrieval.

Six slices. Each slice → its own branch off `phase-4`, PR, merge. End of phase 4 → tag `v0.3.0`.

## Scope decisions

**In:** alembic, observability, background workers, rate limits, websockets, graph→retrieval wire-up.

**Cut:**
- **Cross-tenant stats** — vague without a real ops consumer asking. Add when there's a question someone's actually trying to answer.
- **gRPC full surface mirror** — still no consumer. Phase 5 if a real client appears.

Cadence: phase-3 pattern (design upfront, then power through). I stop only on real blockers.

---

## Slice ordering

```
1. alembic           — first real migration story; touches every table
2. observability     — /metrics, OpenTelemetry traces, structured logs
3. workers           — real worker process (not asyncio.create_task)
4. rate-limits       — per-(key, user) req/min middleware
5. websockets        — /v1/events subscription + broker
6. graph-retrieval   — populate l3_graph_context in layered retrieval
```

Why this order: alembic first because schema is load-bearing for every later slice. Observability second so subsequent slices ship with metrics from day one. Workers before rate limits because rate limits live in a layer that depends on observability counters. Websockets before graph-retrieval because graph-retrieval is enrichment-only and doesn't block anything.

---

## Slice 1 — Alembic migrations

**Surface:**
- `alembic.ini` at repo root
- `alembic/env.py` wired to `palace.config.settings.database_url` (uses async engine via `connection.run_sync`)
- `alembic/versions/2026_05_04_0001_baseline.py` — captures the entire current schema (post-phase-3) as the baseline; existing fresh installs run this once.
- `alembic/versions/2026_05_04_0002_indexes.py` — adds `(tenant_id, user_id)` composite indexes and `(tenant_id, accessed_at DESC)` for memory_dynamics; sets the precedent for future migrations.

**Bootstrap behavior:**
- `init_db()` keeps creating tables for first-run convenience. **Plus** an Alembic `stamp head` is invoked on a fresh DB so future `upgrade head` runs find a known starting point.
- `palace alembic upgrade head` (new CLI subcommand or just docs pointing at `alembic upgrade head`) for ongoing migrations.

**Decisions:**
- D1.1 — Single baseline migration (not per-table). Reflects current schema. Safer than backfilling phase-by-phase fictional history.
- D1.2 — `init_db` stamps Alembic on first run. Fresh deploys get both schema and version table together.
- D1.3 — Async engine in `env.py` via `run_sync` (Alembic doesn't natively support async).
- D1.4 — `alembic_version` table is the source of truth; future migrations go in `alembic/versions/` chronologically.

**Tests:**
- `tests/test_alembic.py` — programmatically run `upgrade head` against a TestContainers Postgres, assert all phase-3 tables + `alembic_version` exist.
- Existing live integration tests keep working (they create schema via `init_db`; alembic stamp doesn't break that).

---

## Slice 2 — Observability

**Surface:**
- `palace/observability/__init__.py`
- `palace/observability/metrics.py` — Prometheus counters/histograms; `/metrics` endpoint via `prometheus-client`. Counters: `palace_requests_total{method,path,status}`, `palace_request_duration_seconds{method,path}`, `palace_cache_hits_total{namespace}`, `palace_cache_misses_total{namespace}`, `palace_graph_writes_total{kind}`, `palace_graph_failures_total`, `palace_jobs_total{kind,status}`.
- `palace/observability/tracing.py` — OpenTelemetry SDK setup. OTLP exporter pointed at `PALACE_OTLP_ENDPOINT`; auto-instrument FastAPI + httpx + asyncpg + Redis. No-op if env unset.
- `palace/observability/logging.py` — structlog config. JSON output in production, pretty in dev. Every request gets a request_id; structlog binds tenant_id + key_id from the auth context.

**Wiring:**
- `main.py` mounts `/metrics` (no auth — k8s scraper friendly; or add HTTP basic via env if Joshua wants)
- `AuthMiddleware` records request metric and binds request_id + auth context to structlog
- `cache_call`, `graph_service.schedule`, `job_service.run_async` increment relevant counters

**Decisions:**
- D2.1 — `/metrics` is public by default (most k8s setups need this; can be locked down via env later)
- D2.2 — OpenTelemetry is optional (env var gates it)
- D2.3 — structlog over stdlib logging now that we're touching every entry point anyway
- D2.4 — Request ID is `X-Request-ID` header if present, else uuid4

**Tests:**
- Metrics counters increment correctly under simulated traffic
- /metrics endpoint returns valid Prometheus exposition format
- Logger correctly binds and emits JSON

---

## Slice 3 — Background workers

**Surface:**
- `palace/workers/__init__.py`
- `palace/workers/runner.py` — `palace-worker` CLI. Spins up an asyncio event loop, polls `reflection_jobs` for pending rows, runs them, marks status. Single-process (no Celery).
- `palace/workers/job_queue.py` — Postgres-backed queue using `SELECT … FOR UPDATE SKIP LOCKED`. Workers poll every 1s, lease for 60s, complete or extend.
- `palace/job_service.py` — change `run_async` to **enqueue** (insert pending row) rather than `asyncio.create_task`. The web process no longer runs jobs itself.

**Migration:**
- `reflection_jobs` gains `leased_until: timestamptz | None` and `attempts: int = 0` columns. New alembic migration in this slice.
- Existing tests that mock `job_service.run_async` keep passing because the mock surface doesn't change.

**Failure semantics:**
- A failed job (`attempts >= 3`) is marked `status="failed"` with `error` populated. Manual retry via `POST /v1/admin/jobs/{id}/retry` (admin-only).

**Decisions:**
- D3.1 — Postgres queue, not Redis/Celery. We already have Postgres; one fewer moving piece.
- D3.2 — Worker is a separate process (`python -m palace.workers.runner`). Web no longer runs jobs.
- D3.3 — 3 retry attempts before permanent fail
- D3.4 — Lease 60s; worker extends if still running

**Tests:**
- Worker picks up pending job, marks completed
- Two workers don't double-process the same row (skip-locked semantics)
- Job fails after 3 retries; admin retry resets attempts

---

## Slice 4 — Per-user rate limits

**Surface:**
- `palace/ratelimit/__init__.py`
- `palace/ratelimit/limiter.py` — sliding-window counter in Redis (lazy connect; required for rate limits unlike the cache which is optional). Window: 1 minute. Limit per (tenant_id, key_id, user_id).
- `palace/ratelimit/middleware.py` — runs **after** AuthMiddleware. On 429, returns `{"error": {"code": "rate_limited", "message": "...", "retry_after_seconds": N}}` with `Retry-After` header.

**Limits (configurable via env):**
- `PALACE_RATE_LIMIT_DEFAULT=120/min` — applies to all (tenant_id, key_id, user_id) tuples
- `PALACE_RATE_LIMIT_SEARCH=60/min` — separate bucket for /search and /context endpoints
- Bypass via key scope `unlimited` — admins can mint these for trusted server-to-server keys

**Decisions:**
- D4.1 — Redis is required when rate limits are enabled (set `PALACE_RATE_LIMIT_ENABLED=false` to no-op)
- D4.2 — Sliding window over fixed window (avoids edge spikes)
- D4.3 — `unlimited` scope opt-out for trusted callers
- D4.4 — 429 with Retry-After header, not 503

**Tests:**
- 121 requests in 1 minute → 121st returns 429
- Different (tenant, user) tuples have independent buckets
- `unlimited` scope skips the check

---

## Slice 5 — WebSocket subscriptions

**Surface:**
- `palace/api/events.py` — `WS /v1/events?topics=memory.created,intention.fired`
- `palace/events/__init__.py`
- `palace/events/broker.py` — pub/sub over Redis (reuse the cache Redis). Publishes events with shape `{type, tenant_id, payload, occurred_at}`.
- `palace/events/types.py` — event constants: `memory.created`, `memory.updated`, `memory.deleted`, `memory.superseded`, `episode.created`, `intention.fired`, `arc.synthesized`.

**Auth:**
- WebSocket handshake reads X-Palace-Key from query string `?api_key=...` (Sec-WebSocket-Protocol auth is awkward across browsers). Tenant binding still enforced — subscriber only receives events for their tenant.

**Wire-up:**
- Memory create/update/delete/supersede publish to broker
- Episode reflection completion publishes `episode.created`
- Intention firing in `IntentionService.check` publishes `intention.fired`
- Arc synthesis completion publishes `arc.synthesized`

**Decisions:**
- D5.1 — Redis pub/sub (already a dep; no new infra)
- D5.2 — At-most-once delivery; clients that need replay can re-query state
- D5.3 — One topic = one event type; clients filter via `?topics=...`
- D5.4 — Per-tenant isolation enforced server-side

**Tests:**
- Subscribed client receives event published in their tenant
- Subscribed client does NOT receive events from other tenants
- Disconnected clients don't crash the broker

---

## Slice 6 — Graph → retrieval wire-up

**Surface:**
- `palace/retrieval/layered.py` — populate the `l3_graph_context` slot when `include_graph=True` in `LayeredContextRequest`. For each L2 memory, fetch 1-hop neighbors via `graph_service.neighbors`, dedupe, attach as `l3_graph_context.related_memories: [{id, content, edge_type, hop_distance}, ...]`.
- `palace/api/common.py` — extend `LayeredContextOut` with optional `l3_graph_context`.
- `palace/api/retrieval.py` — accept `include_graph: bool = False` on `LayeredContextRequest`.
- `palace_client/palace_client/client.py` — pass `include_graph` through.
- `palace_client/palace_client/models.py` — extend `LayeredContext` model.

**Decisions:**
- D6.1 — `include_graph` defaults False; backwards compatible
- D6.2 — 1-hop only by default; cap at 2 if `graph_depth=2` requested
- D6.3 — Graph misses (disabled, empty, or query failure) → `l3_graph_context: null` (not an error)
- D6.4 — Neighbors capped at 50 per query to bound payload size

**Tests:**
- include_graph=False → l3 is null
- include_graph=True with graph disabled → l3 is null (no error)
- include_graph=True populates related_memories from graph neighbors
- Cap at 50 enforced

---

## Cross-slice testing

- Each slice ships unit tests + integration tests against real backends as needed.
- Integration tests stay opt-in via `-m integration`.
- New container deps (alembic uses Postgres which is already there) added to `tests/integration/conftest.py` per-slice.

## New env vars introduced (cumulative)

- Slice 2: `PALACE_OTLP_ENDPOINT`
- Slice 3: `PALACE_WORKER_POLL_INTERVAL`, `PALACE_WORKER_LEASE_SECONDS`
- Slice 4: `PALACE_RATE_LIMIT_ENABLED`, `PALACE_RATE_LIMIT_DEFAULT`, `PALACE_RATE_LIMIT_SEARCH`
- Slice 5: (none — reuses `PALACE_REDIS_URL`)
- Slice 6: (none)

## Done criteria

- All 6 slices merged to `phase-4`
- 290+ mock tests, 53+ client tests green
- New live integration tests for alembic upgrade, worker queue, rate limits, websocket events
- `phase-4` merged to `main` and tagged `v0.3.0`
- CHANGELOG updated; both packages bumped to 0.3.0
- Same release.yml from phase 3 publishes the new version
