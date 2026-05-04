# Palace Phase 7 — Master Plan

**Date:** 2026-05-04
**Branch:** `phase-7`
**Goal:** Compliance + forensics. Track who-did-what at the admin layer and what-changed-when at the data layer. Two small carryovers + a release.

Four slices. Same cadence — design upfront, power through.

## Slice ordering

```
1. audit-log         — admin operation audit trail
2. memory-versions   — per-update content snapshots
3. carryovers        — cross-tenant search + worker-path event publishers
4. release           — v0.6.0
```

## Cuts (still)

- Per-tenant Postgres schemas, admin web UI.
- Memory clustering / topic discovery — interesting but speculative.
- Per-key tenant-resource scoping (read X, write Y) — defer until someone asks.

---

## Slice 1 — Admin audit log

**Surface:**
- New table `audit_logs` (alembic 0005): `id`, `key_id`, `tenant_id` (nullable for cross-tenant ops), `method`, `path`, `status_class`, `request_body_hash`, `response_ms`, `created_at`.
- `palace/audit/__init__.py` + `palace/audit/middleware.py` — Starlette middleware that runs after AuthMiddleware and inserts a row for every `/v1/admin/*` and `/v1/maintenance/*` request.
- `GET /v1/admin/audit?since=...&until=...&key_id=...&path_prefix=...` — admin-scope query endpoint with pagination.

**Decisions:**
- D1.1 — Body hash, not body content. Audit should answer "did this happen" not "what exactly was sent" (which would leak bootstrap key plaintexts, etc.).
- D1.2 — Async insert, fire-and-forget. Audit failures log + swallow; never block a real request.
- D1.3 — Audit middleware ONLY fires for admin/maintenance paths. Recording every `/v1/memories` write would 10× the DB load.

---

## Slice 2 — Memory change history

**Surface:**
- New table `memory_versions` (alembic 0006): `id`, `memory_id`, `tenant_id`, `user_id`, `version_number`, `content`, `metadata_json`, `change_kind` (one of `created`, `updated`, `superseded`), `actor_key_id`, `created_at`.
- `palace/memory_service.py` — `update()` + `_record_supersession()` snapshot the prior content before mutating.
- `GET /v1/memories/{id}/history` — chronological list of versions for a memory.

**Decisions:**
- D2.1 — Versions are append-only; never updated, never deleted (until tenant cleanup).
- D2.2 — Initial `created` version is recorded by `create()` so the trail is always complete from row 1.
- D2.3 — Tenant deletion cascades versions (FK ON DELETE CASCADE).
- D2.4 — Vector data not versioned; the embedding follows content, not the other way around.

---

## Slice 3 — Cross-tenant search + worker-path event publishers

Two small carryovers from earlier phases:

**A. Cross-tenant search.** `POST /v1/memories/search` accepts `tenant_id: str | None` field. Cross-tenant admin keys may pass `"ALL"` to search across every tenant; results carry a `tenant_id` field in the response. Tenant-bound keys still scoped to their own.

**B. Worker-path event publishers.** When `episode_service.reflect_session` runs from the `_reflection_handler` worker, it now also publishes `episode.created`. Same for synthesis. The phase-5 fix only covered the in-process path because that was what tests exercised at the time.

---

## Slice 4 — v0.6.0 release

- Bump `palace-memory` and `palace-client` to `0.6.0`.
- CHANGELOG entry covering all 3 phase-7 slices.
- Tag `v0.6.0`.

---

## Done criteria

- All 4 slices merged to `phase-7`
- 390+ mock tests, 53+ client tests
- `phase-7` merged to `main` and tagged `v0.6.0`
- If PyPI trusted publishing is configured by then, full release pipeline runs green
