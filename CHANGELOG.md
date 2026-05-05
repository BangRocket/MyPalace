# Changelog

All notable changes to MyPalace are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and MyPalace adheres to
[Semantic Versioning](https://semver.org/).

## [0.8.1] — 2026-05-05

Three post-tag fixes surfaced when bringing v0.8.0 up against a real
deploy. v0.8.0's PyPI publish never landed (CI failure on the first
fix below), so 0.8.1 is effectively the first 0.8 release to ship.

### Fixed

- **`aiosqlite` missing from dev extras.** Phase 8 slice 2's
  `tests/test_db_observability.py` uses an in-memory aiosqlite engine
  to drive the SQLAlchemy event hooks. The dep was added to the local
  venv via `uv pip install` but never to `pyproject.toml`, so CI's
  `pip install -e ".[dev]"` left it absent and v0.8.0's release
  workflow failed at test collection.
- **Qdrant healthcheck used `wget`, which the slim qdrant image no
  longer ships.** Both `docker-compose.yml` and
  `docker-compose.prod.yml` switched to a bash `/dev/tcp` probe that
  works on every recent qdrant image (bash IS still bundled).
- **`_ensure_default_tenant()` lifespan startup raised
  `NotNullViolationError` on first boot.** `pg_insert(...).values(...)`
  bypasses SQLModel's `default_factory=utcnow`, so `created_at`
  arrived as null. Fix: pass `created_at=utcnow()` explicitly. Bug
  was latent since phase 3 slice 2 because mock tests stub
  `_ensure_default_tenant` and the integration conftest creates
  tenants via the ORM constructor (which DOES apply defaults).

### Changed

- **Dev compose default ports moved off mypalclara collisions.**
  Postgres now binds 5443→5432 (was 5442), Qdrant binds 6334→6333.
  Mypalclara owns 5442/6333 in its own compose, so running both
  side-by-side now works without env overrides.

## [0.8.0] — 2026-05-04

Production hardening. Three slices since 0.7.1.

### Added — phase 8

- **Deep health check (slice 1)** — `GET /health/deep` pings every
  configured backend (Postgres, Qdrant, optional FalkorDB, optional
  Redis) in parallel with per-check 2s timeout. Returns
  `{"status": "ok"|"degraded", "backends": [...]}` with per-backend
  latency + detail. 200 if all configured backends answered, 503 if
  any failed. Optional backends (FalkorDB, Redis) are tagged
  `configured=False` when their env vars are unset and excluded from
  the overall verdict. Wired into the production compose container
  healthcheck so `depends_on:condition:service_healthy` actually
  means the backend is reachable.
- **Boot-time config validation (slice 1)** — lifespan startup runs
  `validate_config()` BEFORE `init_db()` and refuses to start the
  service if any required env var is malformed (default tenant id,
  bootstrap admin key format, async DB driver, rate-limit-without-redis,
  log format, cache TTLs). Soft issues become structlog warnings
  instead of crashes. Operators see a clean fatal message in the logs
  rather than a confusing first-request traceback.
- **DB query observability (slice 2)** — SQLAlchemy
  `before_cursor_execute` / `after_cursor_execute` hooks emit per-query
  timing into `palace_db_query_duration_seconds` (histogram), bump
  `palace_db_queries_total` (counter), and gate a slow-query log line
  + `palace_db_slow_queries_total` counter at the configurable
  `PALACE_DB_SLOW_QUERY_MS` threshold (default 200ms). Operation
  labels capped to a known set (SELECT/INSERT/UPDATE/DELETE/WITH/
  BEGIN/COMMIT/ROLLBACK/SAVEPOINT/RELEASE/OTHER) so Prometheus label
  cardinality stays bounded. Idempotent install — safe to call
  multiple times on the same engine.
- **Production docker-compose + deployment guide (slice 3)** —
  `docker-compose.prod.yml` with mypalace + worker + Postgres + Qdrant
  + FalkorDB (also serves as the cache/rate-limiter Redis since
  FalkorDB is a Redis module). Healthchecks + `restart: unless-stopped`
  on every container. Production-default knobs preset:
  `PALACE_RATE_LIMIT_ENABLED=true`, `PALACE_WORKER_QUEUE_ENABLED=true`,
  `PALACE_LOG_FORMAT=json`. Required vars (`PALACE_BOOTSTRAP_ADMIN_KEY`,
  `POSTGRES_PASSWORD`) refuse to start the stack if missing.
  `.env.example` rewritten to cover both local-dev defaults and the
  production-required vars. `docs/deployment.md` walks through bring-up,
  scaling (web + workers), observability (PromQL examples), backups
  (pg_dump, Qdrant volume snapshot, per-tenant NDJSON export),
  upgrades, common operational scenarios, and troubleshooting.

## [0.7.1] — 2026-05-04

License metadata correction follow-up to 0.7.0.

### Fixed

- **`license` field now uses the SPDX expression form**
  `"PolyForm-Noncommercial-1.0.0"` (PEP 639 / setuptools 77+). 0.7.0
  declared the license only via the (mismatched MIT) classifier and the
  LICENSE.md file. Wheels now show the canonical
  `License-Expression: PolyForm-Noncommercial-1.0.0` in METADATA.
- **Removed the `License :: Other/Proprietary License` classifier.**
  setuptools 77+ rejects mixing the structured `license =` field with a
  `License :: ...` classifier (PEP 639 says they're alternatives, not
  combinable). The license-expression field is the canonical signal now.
- **README license badge** updated from MIT (legacy mistake) to
  PolyForm Noncommercial 1.0.0 in both server and client READMEs.

No code changes. v0.7.0's PyPI publish never succeeded (pending-publisher
mismatch), so this is the first version to actually reach PyPI.

## [0.7.0] — 2026-05-04

**Project rename: Palace → MyPalace.** Brand alignment with mypalclara.
Plus a license correction.

### Changed (BREAKING)

- **PyPI distribution names** —
  - `palace-memory` → `mypalace`
  - `palace-client` → `mypalace-client`
  - Operators upgrading should `pip uninstall palace-memory palace-client`
    and `pip install mypalace mypalace-client` (versions sync at 0.7.0).
- **Python import paths** —
  - `from palace.X import Y` → `from mypalace.X import Y`
  - `from palace_client import Y` → `from mypalace_client import Y`
- **Docker image** — `bangrocket/palace:X.Y.Z` → `bangrocket/mypalace:X.Y.Z`
- **gRPC proto package** — `palace.v1` → `mypalace.v1` (regenerate stubs
  if you carry your own)
- **License** — Project is **PolyForm Noncommercial 1.0.0**, NOT MIT as
  prior pyproject metadata incorrectly claimed. License is now declared
  via the `License :: Other/Proprietary License` classifier and the
  `LICENSE.md` file at the repo root, which both wheels bundle.
  *No license intent change* — this corrects metadata that never matched
  the project's actual licensing.

### Migration

For most operators:

```bash
pip uninstall palace-memory palace-client
pip install mypalace==0.7.0 mypalace-client==0.7.0
# Then update your imports:
sed -i '' 's/from palace\./from mypalace./g; s/from palace_client/from mypalace_client/g' your_code.py
```

The HTTP API surface (paths, request/response shapes, headers) is
**unchanged** — only the package and import names changed. Existing
clients hitting `/v1/...` keep working.

The gRPC proto package change `palace.v1 → mypalace.v1` is on the wire,
so existing gRPC clients need to regenerate their stubs from the new
`proto/mypalace.proto`.

## [0.6.0] — 2026-05-04

Compliance + forensics + cross-tenant search. Three slices since 0.5.

### Added — phase 7

- **Admin audit log (slice 1)** — `audit_logs` table (alembic 0005)
  records every `/v1/admin/*` and `/v1/maintenance/*` call:
  `key_id`, `tenant_id`, `method`, `path`, `status_class`,
  `request_body_hash`, `response_ms`. Body is hashed (SHA256), not
  stored, so audit answers "did this happen" without leaking
  bootstrap-key plaintext. AuditMiddleware runs innermost (after
  auth) and inserts fire-and-forget so audit failures never break
  the actual request. `GET /v1/admin/audit?since=...&until=...&key_id=...&path_prefix=...`
  exposes the trail; tenant-bound keys see only their tenant's rows,
  cross-tenant admin sees all.
- **Memory change history (slice 2)** — `memory_versions` table
  (alembic 0006) snapshots every memory mutation as an append-only
  row: `memory_id`, `version_number`, `content`, `metadata_json`,
  `change_kind` (one of `created` / `updated` / `superseded`),
  `actor_key_id`. Snapshots happen on `memory_service.create` (v1),
  `memory_service.update` (vN+1), and the supersession path (snapshot
  of OLD memory's content). All best-effort — version-table failures
  log + swallow; primary writes stay correct.
  `GET /v1/memories/{id}/history` returns chronological trail,
  tenant-scoped.
- **Cross-tenant search (slice 3)** —
  `POST /v1/memories/search` accepts an optional `tenant_id` field:
  null = bound key's tenant, `"<id>"` = explicit (admin-only for
  others), `"ALL"` = cross-tenant fanout (cross-tenant admin only).
  Embedding happens once; per-tenant Qdrant searches run in parallel
  and merge by score. Results in ALL mode carry a `tenant_id` field;
  single-tenant payloads unchanged (field is null).
- **Migration guide (this release)** —
  `docs/migrating-mypalclara.md` walks operators through swapping
  mypalclara's embedded ClaraMemory + MemoryManager for a remote
  Palace 0.6.0 deployment. Covers mint-keys, point-the-router,
  data-replay-via-existing-script, validation, and rollback.

### Notes

- Worker-path event publishers (deferred from phase 5 slice 5) are
  already correct: `episode_service.reflect_session` and
  `arc_service.synthesize_narratives` publish events at the bottom of
  their bodies, and the worker handlers call those same functions —
  no separate worker-path wire-up needed.

## [0.5.0] — 2026-05-04

Operations + DR + lifecycle features. Four slices since 0.4.

### Added — phase 6

- **Release pipeline fixes (slice 1)** — `build-and-publish` job's
  permissions block now declares `contents: read` (the prior version
  set only `id-token: write`, which stripped checkout's read access and
  caused "Repository not found" failures on every tag). Docker job is
  conditional on `vars.PUBLISH_DOCKER == 'true'` and bridges
  `secrets.DOCKERHUB_USERNAME` cleanly. `github-release` no longer
  hard-depends on docker. README gains a "Releasing" section
  documenting PyPI trusted-publishing setup, optional Docker Hub
  configuration, and the tag/re-tag dance.
- **Bulk import/export (slice 2)** — `GET /v1/admin/export?tenant_id=<id>`
  streams a NDJSON dump of all tenant data (memories, sessions,
  narrative_arcs, intentions, memory_dynamics, memory_supersessions —
  in FK-safe order). `POST /v1/admin/import?tenant_id=<id>` ingests the
  same shape. Idempotent via `db.merge()`; target tenant_id always
  wins over any tenant_id in the dump. Vector data deliberately
  excluded — re-embed on import keeps dumps portable across embedding
  models. `api_keys` excluded. Disaster recovery + tenant migration
  use cases.
- **Memory TTL (slice 3)** — `Memory.expires_at` column (alembic 0004
  with a partial index). `CreateMemoryRequest.ttl_seconds` field
  computes `expires_at = now + ttl`. Search/list/get filter expired
  rows immediately (`WHERE expires_at IS NULL OR expires_at > now()`)
  even before the cleanup worker has run. New `cleanup` worker handler
  garbage-collects expired rows + their Qdrant vectors per-tenant in
  bounded batches.
- **Embedding migration (slice 4)** — `POST /v1/admin/reembed` enqueues
  a `reembed` worker job that walks every memory in a tenant and
  re-embeds it under a named (provider, model). New `make_embedder`
  factory builds an arbitrary embedder without touching the global
  default. Handles dim changes (writes alongside existing vectors;
  operators drop the old collection out-of-band when ready to cut over).
  Pairs with bulk import: `POST /v1/admin/import?reembed=false` for
  large imports, then trigger reembed for the bulk embed work.

### Notes

- gRPC mirror of the new admin endpoints (export, import, reembed) is
  deliberately deferred — these are operator tools used over HTTP.

## [0.4.0] — 2026-05-04

Surface completion + ops polish. Three slices since 0.3.

### Added — phase 5

- **Worker-queue routing (slice 1)** — new `PALACE_WORKER_QUEUE_ENABLED`
  env flag. When set, the async-mode `/v1/reflection/session` and
  `/v1/synthesis/narratives` routes enqueue jobs onto the Postgres queue
  instead of running them in-process via `asyncio.create_task`. The
  in-process path stays the default so single-process deployments keep
  working without a worker process.
- **Episode/intention/arc event publishers (slice 1)** —
  `episode_service.reflect_session` publishes one `episode.created` per
  written episode; `intentions.service.check` publishes
  `intention.fired` per match (after commit, so subscribers see
  authoritative state); `arc_service.synthesize_narratives` publishes
  `arc.synthesized` per new/updated arc. WebSocket subscribers from
  phase 4 slice 5 now receive the full event stream.
- **gRPC mirror of remaining surfaces (slice 2)** — 22 new RPCs across 8
  services: `SessionService`, `EpisodeService`, `ArcService`,
  `IntentionService`, `DynamicsService`, `RetrievalService`,
  `IngestionService`, `JobService`. All servicers delegate to the same
  singleton services backing HTTP. Auth interceptor `RPC_SCOPE` map
  extended with the same scope rules as HTTP. `PalaceGrpcClient` mirrors
  every new RPC.
- **Cross-tenant analytics (slice 3)** — `GET /v1/admin/stats?tenant_id=<id>`
  returns a per-tenant snapshot (row counts, 7-day activity rollup,
  top-10 users by access, FSRS health). `tenant_id=ALL` returns one
  entry per tenant — but only for cross-tenant admin keys.

### Notes

- gRPC `LayeredContext`, intention `trigger_conditions`, and
  supersession metadata are encoded as JSON strings in proto3 to avoid a
  schema explosion across deeply-nested dict-of-lists shapes.
- Async-mode gRPC endpoints (`ReflectSession`, `SynthesizeNarratives`)
  use proto3 `oneof` (pending vs episodes/arcs); request field `mode`
  carries `"sync"|"async"` instead of HTTP's query param + 200/202
  split.
- Per-tenant Postgres schemas and an admin web UI are deliberately
  deferred — operators who need stronger isolation should run separate
  Palace instances per tenant; a web UI is a different skill and a
  separate phase if requested.

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
