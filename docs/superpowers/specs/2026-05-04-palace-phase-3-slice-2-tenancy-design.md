# Palace Phase 3 — Slice 2: Multi-tenancy

**Date:** 2026-05-04
**Branch:** `phase-3-slice-2-tenancy` (off `phase-3`)
**Depends on:** slice 1 (auth) — keys are bound to tenants
**Master plan:** `docs/superpowers/specs/2026-05-04-palace-phase-3-master.md`

## Goal

Every user-data row is tagged with `tenant_id`. API keys are bound to a tenant on creation. The middleware sets `request.state.auth.tenant_id` from the key; services filter every query by it. Qdrant collections are per-tenant. A migration backfills existing rows with `"default"`.

After this slice: a `tenant=A` key cannot read or write `tenant=B` data; admin keys may pass `?tenant_id=...` explicitly to operate cross-tenant; the test client uses `tenant_id="test"`.

## Non-goals

- Per-tenant LLM/embedding configs (still global)
- Per-tenant rate limits or quotas
- A tenant-management UI
- Per-tenant Postgres schemas or DBs (single shared DB; row-level filtering)

---

## Surface

### New table

`tenants`:
| col | type | notes |
|---|---|---|
| id | varchar(32) PK | sanitized: `[a-z0-9_]+`, max 32 chars |
| label | varchar(100) | human-friendly name |
| created_at | timestamptz | |
| metadata_json | JSONB nullable | extension point |

### tenant_id on all data tables

Add `tenant_id: str` (indexed, default `"default"`) to:
- `memories`
- `sessions`
- `messages`
- `narrative_arcs`
- `reflection_jobs`
- `memory_dynamics`
- `intentions`
- `memory_access_logs`
- `memory_supersessions`
- `api_keys` (the key's tenant binding; `None` = cross-tenant admin)

### Migration strategy

**Decision:** Alembic is deferred to slice 6 (publish). Rationale: there is no live data anywhere yet, and `init_db()` creates the full schema on startup. Adding Alembic now would mean writing the first migration AND wiring up env.py AND backfilling test setups — yak shaving for a feature with no current consumers. Slice 6 gets a single greenfield Alembic migration covering all of phase 3 in one shot.

For this slice: `init_db()` creates the new `tenants` table and `tenant_id` columns directly. Anyone running an existing v0.1 Palace will need to either drop+recreate (no live data) or wait for slice 6's migration story.

### Auth integration

`AuthContext` grows `tenant_id: str | None`. Middleware sets it from the key row:
- `key.tenant_id is not None` → `ctx.tenant_id = key.tenant_id`; later attempts to override via request param are rejected (403).
- `key.tenant_id is None` (admin cross-tenant key) → `ctx.tenant_id` comes from request body/query `tenant_id`; if absent, default to `"default"`.

### Service layer

Every `*_service` method that takes `user_id` also takes `tenant_id`. Internal queries add `Model.tenant_id == tenant_id` to every WHERE clause. New helper:

```python
def tenant_filter(model, tenant_id: str):
    return model.tenant_id == tenant_id
```

Routes pull `tenant_id` from `request.state.auth` and pass it down.

### Qdrant per-tenant collections

`vector_store.ensure_collection(dim, tenant_id: str)` creates `palace_memories_{tenant_id}` lazily. The vector_store wrapper grows a `for_tenant(tenant_id)` method returning a tenant-scoped facade. Episode store likewise.

Sanitization: `tenant_id` matches `^[a-z0-9_]{1,32}$`. Anything else → 400 `invalid_tenant_id`. Validation lives in `palace/auth/tenant.py:validate_tenant_id`.

### Endpoints (admin-scope)

- `POST /v1/admin/tenants` body `{id: str, label: str}` → create
- `GET /v1/admin/tenants` → list
- `DELETE /v1/admin/tenants/{id}` — refuses if any rows still reference (must purge first)
- API key creation grows optional `tenant_id` field; if omitted defaults to admin's bound tenant; if admin is cross-tenant and field omitted → 422.

### Bootstrap

In `lifespan` startup, ensure `tenants` row `"default"` exists (idempotent INSERT … ON CONFLICT DO NOTHING).

---

## Decisions

| ID | Decision | Why |
|---|---|---|
| D2.1 | tenant resolved from API key | Single source of truth; admins override explicitly |
| D2.2 | cross-tenant admin keys exist (tenant_id=NULL) | Migrations, support, debugging |
| D2.3 | per-tenant Qdrant collections | Strong isolation; easy delete-tenant operation |
| D2.4 | shared Postgres with row filtering | Simpler ops than per-tenant DBs; sufficient isolation |
| D2.5 | tenant_id sanitized to `[a-z0-9_]{1,32}` | Safe in Qdrant collection names |
| D2.6 | "default" tenant exists out of the box | Backfill target; single-tenant deployments work zero-config |
| D2.7 | Alembic introduced now | First non-trivial schema migration |
| D2.8 | request body/query `tenant_id` only honored for cross-tenant admin keys | Defense in depth; non-admin keys can never escape their tenant |
| D2.9 | DELETE tenant refuses if data exists | Avoids orphaned Qdrant collections |
| D2.10 | Cross-tenant search uses an explicit `tenant_id` parameter, never wildcard | No accidental tenant-leak |

---

## Files to create

- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `alembic/versions/2026_05_04_0001_phase3_slice2_tenancy.py`
- `palace/auth/tenant.py` — `validate_tenant_id`, sanitization
- `palace/api/tenants.py` — `/v1/admin/tenants` routes
- `tests/test_tenancy_models.py`
- `tests/test_tenancy_routes.py`
- `tests/test_tenancy_isolation.py`
- `tests/integration/test_tenancy_live.py`

## Files to modify

- `palace/models.py` — add `tenant_id` to all 9 tables, add `Tenant` table
- `palace/auth/context.py` — `AuthContext.tenant_id`
- `palace/auth/middleware.py` — set `tenant_id` on context; reject body overrides for tenant-bound keys
- `palace/auth/key_service.py` — `create_key(tenant_id=...)`; bootstrap binds to `"default"`; lookup returns tenant
- `palace/api/admin.py` — accept `tenant_id` on key creation
- All `palace/api/*.py` route handlers — read `tenant_id` from auth context, pass to services
- All `palace/*_service.py` files — accept `tenant_id`, filter every query
- `palace/vector.py` — per-tenant collection helper
- `palace/main.py` — bootstrap `default` tenant in lifespan
- `palace/config.py` — `default_tenant_id` setting (default `"default"`)
- `tests/conftest.py` — `mock_key_service` returns AuthContext with `tenant_id="test"`; bypass also sets `"test"`
- `tests/integration/conftest.py` — pass `PALACE_DEFAULT_TENANT_ID="test"` so live tests use a sandbox tenant
- `palace_client/palace_client/client.py` — no API change (tenant is server-side); but `health()` now optional
- `pyproject.toml` — alembic already a dep; nothing new
- `README.md` — multi-tenancy section

---

## Edge cases & test matrix

| Scenario | Expected |
|---|---|
| Tenant-bound key + request without explicit tenant_id | Uses key's tenant |
| Tenant-bound key + request with conflicting tenant_id | 403 cross-tenant denied |
| Cross-tenant admin key + tenant_id in body | Honored |
| Cross-tenant admin key + no tenant_id | Falls back to `default_tenant_id` setting |
| Tenant A creates memory; tenant B searches | B sees nothing |
| Tenant A creates memory; admin searches with `tenant_id=A` | Sees it |
| `tenant_id="A B"` (space) | 400 `invalid_tenant_id` |
| `tenant_id="aaa…aaa" * 33` | 400 `invalid_tenant_id` |
| Delete tenant with rows | 409 conflict |
| Delete tenant with no rows | 200 |
| Qdrant collection per-tenant | `palace_memories_default`, `palace_memories_A` exist |
| Migration applied to legacy DB | All rows have `tenant_id='default'` |

## Done criteria

- All scenarios pass (unit + integration)
- Existing 153 mock tests still pass (because conftest sets `tenant_id="test"` everywhere)
- Existing live tests still pass against test-tenant collections
- Alembic upgrade-from-empty produces a schema identical to `init_db`
- README documents tenants, default tenant, key binding, admin override
- Merged to `phase-3` via PR
