# Palace Phase 6 — Master Plan

**Date:** 2026-05-04
**Branch:** `phase-6`
**Goal:** Fix the broken release pipeline and add the operational features Palace needs to be a real production data store: bulk import/export, memory TTL, and embedding-model migration.

Four slices. Phase-3/4/5 cadence — design upfront, power through, stop only on real blockers.

## Scope rationale

Phases 3-5 built the surface (auth, multi-tenancy, transports, integrations). Phase 6 fills the operational gaps that show up the moment Palace holds data anyone cares about:

- **Release pipeline broken** — checkout permissions bug + missing Docker secrets means `v0.4.0` never published. Have to fix this before anything else ships.
- **No way to migrate tenant data** — no export, no import. Disaster recovery story is "rebuild from sources." That's table stakes for a data product.
- **Memory grows forever** — no TTL, no cleanup. Operators will eventually want "session memories expire after 30 days, semantic memories never expire."
- **Embedding model is forever** — change the embedding model and existing data becomes garbage. Need a re-embed-all path.

Cuts (still): per-tenant Postgres schemas, admin web UI.

---

## Slice 1 — Release pipeline fixes

### Bugs found in v0.3.0 + v0.4.0 workflow runs

1. `build-and-publish` job overrides default permissions with `id-token: write`, which strips `contents: read`. `actions/checkout@v4` then fails with `Repository not found` (the auth header is set but the token has no scope).
2. `docker` job runs unconditionally; fails with "Username and password required" when `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` repo secrets aren't set.
3. PyPI trusted publishing for `palace-memory` and `palace-client` likely not configured at https://pypi.org. Step would fail even if checkout succeeded.

### Fixes

- Add `contents: read` (and `packages: read` defensively) to the build-and-publish permissions block.
- Bridge `secrets.DOCKERHUB_USERNAME` to a job-level env var; gate the docker job on that var being non-empty. Skip cleanly when it's missing.
- Add a README "Releasing" section with the trusted-publishing setup steps + Docker Hub secret names. Operators see exactly what to configure.
- Cut a no-op tag `v0.4.0-rc1` to verify the workflow runs green end-to-end (TestPyPI route already exists in the workflow for rc tags).

### Decisions

- D1.1 — Fix permissions, don't widen them. Job-level `permissions:` with the specific scopes needed.
- D1.2 — Docker is conditional, not removed. Operators who set the secrets get docker images.
- D1.3 — `v0.4.0-rc1` rehearsal before re-tagging `v0.4.0`. Confirms TestPyPI flow works.

---

## Slice 2 — Bulk import/export

### Surface

- `palace/api/portability.py` — `GET /v1/admin/export?tenant_id=<id>` and `POST /v1/admin/import`.
- Streaming JSON for export to handle large tenants without holding everything in memory (chunked NDJSON).
- Import accepts the same NDJSON shape; idempotent on (tenant_id, id) primary keys via upsert.

### Export shape (NDJSON, one record per line)

```jsonl
{"_type": "tenant", "id": "acme", "label": "Acme Corp"}
{"_type": "memory", "id": "...", "tenant_id": "acme", "user_id": "...", "content": "...", ...}
{"_type": "session", "id": "...", "tenant_id": "acme", "user_id": "...", "title": "...", ...}
{"_type": "message", "id": "...", "tenant_id": "acme", "session_id": "...", ...}
{"_type": "narrative_arc", "id": "...", "tenant_id": "acme", ...}
{"_type": "intention", "id": "...", "tenant_id": "acme", ...}
{"_type": "memory_dynamics", "memory_id": "...", "tenant_id": "acme", ...}
{"_type": "memory_supersession", "id": "...", "tenant_id": "acme", ...}
```

Vector data (Qdrant) is NOT included in the export — re-embed on import. Keeps the dump portable across embedding models.

### Decisions

- D2.1 — NDJSON, one record per line. Streamable, greppable, easy to diff.
- D2.2 — Vectors excluded; re-embed on import. The alternative (export raw vectors) ties dumps to a specific embedding model.
- D2.3 — Import is admin-scope and bounded to the requesting key's tenant (or any tenant for cross-tenant admin keys).
- D2.4 — Import is idempotent via upsert; re-importing the same dump is safe.
- D2.5 — Export does NOT include `api_keys`. Operators set up auth on the new deployment separately.

### Tests

- Round-trip: export tenant A, drop tenant A, import dump, assert all rows reappear with correct relationships.
- Streaming: export 10k memories without OOM (live test with a fixture).
- Import filters: foreign-key validity (orphan messages skipped with warning).

---

## Slice 3 — Memory TTL + cleanup

### Surface

- `palace/models.py` — `Memory.expires_at: datetime | None` column.
- New alembic migration `0004_memory_expires_at.py`.
- `palace/api/common.py` — `CreateMemoryRequest.ttl_seconds: int | None` field.
- `palace/memory_service.py` — `create()` translates `ttl_seconds` to `expires_at = utcnow() + timedelta(...)`.
- `palace/workers/handlers.py` — new `cleanup_expired_memories` handler that deletes rows where `expires_at <= now()`. Runs per-tenant, batched, with the same FOR UPDATE SKIP LOCKED pattern.
- `palace/workers/runner.py` — periodic enqueue: every `PALACE_TTL_CLEANUP_INTERVAL` seconds (default 3600), enqueue a `cleanup` job per tenant.

### Decisions

- D3.1 — `expires_at` is null-by-default. Existing memories never expire.
- D3.2 — Cleanup runs as a worker job, not in the request path. Operators without a worker process don't get auto-cleanup; they can delete via the existing endpoints.
- D3.3 — Search/list filters out expired memories (`WHERE expires_at IS NULL OR expires_at > now()`). Dead rows aren't returned even before cleanup runs.
- D3.4 — Vector store entries for expired memories are deleted alongside the SQL rows (same pattern as `delete_for_user`).

### Tests

- Memory created with `ttl_seconds=60` has `expires_at` set correctly.
- Search excludes expired memories even if cleanup hasn't run.
- Cleanup handler deletes rows past their `expires_at`.

---

## Slice 4 — Embedding migration + v0.5.0 release

### Surface

- `POST /v1/admin/reembed?tenant_id=<id>&model=<name>` — admin-scope, enqueues a `reembed` worker job.
- `palace/workers/handlers.py` — new `reembed` handler:
  1. Resolve target model + dim
  2. If dim differs from current, ensure a NEW Qdrant collection
  3. Iterate memories in the tenant, batch-embed under the new model, upsert into the new collection
  4. Atomically swap collection alias (or just point `vector_store` at the new collection)
  5. Drop the old collection
- `palace/embeddings.py` — function to load arbitrary HF model by name without changing the global default.

### Decisions

- D4.1 — Re-embed is opt-in per-tenant. Operators may want different tenants on different models.
- D4.2 — Swap-via-alias would be cleanest but Qdrant aliasing is a separate API. Use rename-collection fallback.
- D4.3 — Job runs as a normal worker job — no special priority. Operators kicking off a re-embed should expect it to finish in background time.

### Release

- Bump both packages to `0.5.0`.
- CHANGELOG covering all 4 slices.
- Tag `v0.5.0` (after slice 1 has rehearsed `v0.4.0-rc1` successfully).

---

## Done criteria

- All 4 slices merged to `phase-6`
- 360+ mock tests, 53+ client tests
- Live integration tests for export round-trip + TTL cleanup + reembed
- Release workflow runs green end-to-end (rehearsed via rc tag)
- `phase-6` merged to `main` and tagged `v0.5.0`
