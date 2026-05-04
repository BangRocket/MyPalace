# Palace Phase 3 — Master Plan

**Date:** 2026-05-04
**Branch:** `phase-3`
**Goal:** Production-readiness pass: auth, multi-tenancy, graph parity, hot-path cache, gRPC, and PyPI publishing.

Six slices. Each slice merges to `phase-3` via PR. End of phase 3 → merge `phase-3` to `main` and tag `v0.2.0`.

---

## Slice ordering rationale

Auth and multi-tenancy come first because every later API addition has to know about them — adding them mid-phase would mean revisiting every other slice's surface. Graph (FalkorDB) closes the parity gap with mypalclara. Redis cache and gRPC are scale/transport concerns and ride on top. Publish is last so v0.2.0 is one coherent release.

```
1. auth         — API key middleware + per-key scopes
2. multi-tenancy — tenant_id everywhere; per-tenant Qdrant collection isolation
3. graph        — FalkorDB integration; episode/arc/memory edges; graph-aware retrieval
4. redis-cache  — read-through cache for layered context, search, dynamics
5. grpc         — alternative transport over Protobuf; reuse services
6. publish      — palace-client → PyPI; palace-server → Docker Hub + PyPI; v0.2.0 tag
```

---

## Slice 1 — Auth

**Surface:** API key middleware. Header `X-Palace-Key: <key>`. Per-key scopes (`read`, `write`, `admin`). Keys stored in new `api_keys` table with bcrypt hash, scopes, label, created_at, last_used_at, revoked_at.

**Endpoints (admin scope only):**
- `POST /v1/admin/keys` — create key (returns plaintext once)
- `GET /v1/admin/keys` — list (no plaintext)
- `DELETE /v1/admin/keys/{key_id}` — revoke

**Bootstrap:** First-run env var `PALACE_BOOTSTRAP_ADMIN_KEY` mints an admin key on lifespan startup if no admin keys exist.

**Scope mapping:**
- `read` — GET endpoints + POST /search, /list, /context/*
- `write` — read + POST/PATCH/DELETE on memories/sessions/episodes/etc.
- `admin` — write + /admin/* + /maintenance/*

**Out of scope:** JWT, OAuth, mTLS, per-user rate limits. Keys are server-to-server; mypalclara holds one and proxies user identity via `user_id` body field (status quo).

**Decision points:**
- D1.1: Header name — `X-Palace-Key` (not `Authorization: Bearer ...`) to keep it obviously non-OAuth. **Pick:** `X-Palace-Key`.
- D1.2: Storage — bcrypt hash of full key, lookup by `key_id` prefix (first 8 chars stored plaintext for indexing). **Pick:** prefix-indexed bcrypt.
- D1.3: Disable for tests — `PALACE_AUTH_DISABLED=true` env flag bypasses middleware. **Pick:** yes, for the test client.

---

## Slice 2 — Multi-tenancy

**Surface:** New `tenant_id` column on every user-data table (memory, session, message, episode, narrative_arc, memory_dynamics, intention, job, supersession). API requests carry `tenant_id` in body or URL. API key is bound to a tenant on creation (admin keys may be cross-tenant).

**Qdrant isolation:** One collection per tenant: `palace_memories_{tenant_id}` and `palace_episodes_{tenant_id}`. `vector_store.ensure_collection` becomes per-tenant lazy.

**Migration:** Existing rows get `tenant_id = "default"` via Alembic migration. New `tenants` table tracks tenant metadata.

**Decision points:**
- D2.1: tenant resolution — body field on every request, or derive from API key? **Pick:** derive from API key (one tenant per key); admin keys may pass `tenant_id` explicitly.
- D2.2: cross-tenant queries — admin only via explicit `tenant_id` parameter; never implicit. **Pick:** explicit.
- D2.3: Qdrant collection naming — sanitize tenant_id (alphanum + `_`, max 32 chars). **Pick:** sanitize + reject invalid.

---

## Slice 3 — Graph (FalkorDB)

**Surface:** New `palace/graph/` module wrapping FalkorDB (Redis-protocol Cypher). Nodes: `User`, `Memory`, `Episode`, `Arc`, `Topic`. Edges: `MENTIONS`, `PARTICIPATES_IN`, `BELONGS_TO`, `SUPERSEDES`, `RELATES_TO`.

**Write path:** On memory/episode/arc create, async-enqueue a graph upsert (re-uses `job_service` pattern). On supersede, write `SUPERSEDES` edge.

**Read path:** New `/v1/graph/neighbors` endpoint — given a node id, return n-hop neighbors with edge types. Layered retrieval grows an optional `l3_graph_context` with graph-walked memories ranked by edge weight.

**Decision points:**
- D3.1: graph DB choice — FalkorDB (Redis-protocol Cypher, ARM-native, fast) vs Neo4j (heavier, mature). **Pick:** FalkorDB to match mypalclara.
- D3.2: write consistency — sync vs async. **Pick:** async via `job_service` (graph is enrichment, not source of truth).
- D3.3: schema migration — graph schema changes are additive only in phase 3.

---

## Slice 4 — Redis cache

**Surface:** Read-through cache in front of:
- `/v1/context/layered` — key by hash of (tenant, user, query, params); TTL 60s
- `/v1/memories/search` — key by hash of (tenant, query, filters); TTL 60s
- Memory-by-id GETs — TTL 300s; invalidated on update/delete

**Invalidation:** On write, publish to a Redis channel; cache wrapper subscribes and busts. Write-through is rejected (too easy to skew).

**Optional:** `PALACE_CACHE_DISABLED=true` env flag for tests. If `PALACE_REDIS_URL` is unset, cache is a no-op.

**Decision points:**
- D4.1: Redis instance — same Redis as FalkorDB (FalkorDB ships in `falkordb/falkordb` image which is a Redis with the module loaded). **Pick:** reuse.
- D4.2: cache library — `redis-py` async client, no decorator magic; explicit cache wrapper class.
- D4.3: TTL strategy — short (60s) so staleness is bounded; invalidation is best-effort speedup.

---

## Slice 5 — gRPC

**Surface:** `proto/palace.proto` defining `MemoryService`, `EpisodeService`, `ContextService`, `IntentionService`, `DynamicsService`, `IngestionService`. Generated stubs in `palace/grpc/`. Server runs alongside FastAPI on a separate port via `grpc.aio`.

**Auth:** Same API key, passed in metadata `x-palace-key`.

**Client:** `palace_client/grpc.py` adds `PalaceGrpcClient` mirroring REST client surface.

**Decision points:**
- D5.1: REST stays primary; gRPC is additive. **Pick:** yes.
- D5.2: streaming endpoints — only `search` returns a stream (memory-at-a-time). All others unary.
- D5.3: codegen — `grpcio-tools` build step, checked-in stubs (no runtime codegen).

---

## Slice 6 — Publish

**Targets:**
- `palace-client` → PyPI (`pip install palace-client`). Already standalone subpackage.
- `palace` server → PyPI (`pip install palace-memory[server]`) + Docker Hub `palace/palace:0.2.0`.
- GitHub release with changelog.

**Steps:**
1. Bump versions to `0.2.0` in both `pyproject.toml` files.
2. CHANGELOG.md covering phase 2 + phase 3.
3. GitHub Actions: `release.yml` triggered on `v*` tag → build, test, twine upload, docker push.
4. README install instructions, quickstart, deployment guide.
5. Cut `v0.2.0` tag.

**Decision points:**
- D6.1: package names — `palace-client` and `palace-memory` (server). **Pick:** confirm at slice time.
- D6.2: Docker base — `python:3.12-slim`. **Pick:** confirmed.
- D6.3: PyPI vs TestPyPI first — TestPyPI for both, then PyPI. **Pick:** TestPyPI rehearsal.

---

## Cross-slice testing strategy

- Each slice ships unit tests (mocked deps) + integration tests against real backends (Postgres + Qdrant + FalkorDB + Redis as needed).
- Integration tests stay opt-in (`-m integration`).
- Auth is wired into the existing `client` fixture via `PALACE_AUTH_DISABLED=true`.
- Multi-tenancy: the test client uses `tenant_id="test"`.

## Out of scope for phase 3

- Per-user rate limiting (phase 4)
- WebSocket subscriptions for memory events (phase 4)
- Embedded mode (palace-as-library, not service) — explicitly rejected
- Cross-tenant analytics (phase 4)

## Done criteria

- All 6 slices merged to `phase-3`
- Mock test suite green; integration suite green against full stack
- `palace-client==0.2.0` and `palace-memory==0.2.0` published to TestPyPI
- Docker image builds and runs end-to-end smoke
- `phase-3` merged to `main` with tag `v0.2.0`
