# Per-tenant Postgres schemas — design doc (phase 12 slice 0)

**Status:** DRAFT, awaiting Joshua sign-off before any phase-12.1 code lands.
**Author:** Claude (per phase-12 plan).
**Last updated:** 2026-05-05.

This document scopes the move from MyPalace's current **table-level
tenant isolation** (every row carries a `tenant_id` column; queries
filter by it) to **schema-level tenant isolation** (every tenant gets
its own Postgres schema; no `tenant_id` columns; queries are scoped via
`SET search_path`). It does **not** propose code yet — the goal here is
to agree on the approach, the migration path, and the operational
implications.

The README has historically listed "per-tenant Postgres schemas" as
**out of scope**. Phase 12 reverses that: the gap analysis vs mypalclara
flagged tenancy as a divergence ("MyPalace ready for per-tenant schemas;
mypalclara assumes single tenant"), and the operator workflow now wants
hard isolation with no risk of a bad query leaking across tenants.

---

## 1. Why this change

Today, **table-level isolation** means:

- Every domain table (`memories`, `sessions`, `messages`, `episodes`,
  `narrative_arcs`, `intentions`, `audit_logs`, …) has a `tenant_id`
  column. There are 19 occurrences across `mypalace/models.py` and
  ~652 references across `mypalace/**/*.py`.
- Application code MUST add a `WHERE tenant_id = :tenant_id` clause to
  every query. We rely on code review, composite indexes
  (`(tenant_id, …)`), and `auth.resolve_tenant()` to enforce this.
- A single missed filter in a future feature would silently leak data
  across tenants. The compiler doesn't catch it; integration tests
  catch only what they exercise.

**Schema-level isolation** moves the boundary into Postgres itself:

- Each tenant gets a schema, e.g. `acme`, `globex`, `default`.
- Tables exist once per schema (`acme.memories`, `globex.memories`).
- Each request `SET search_path TO <tenant>, public` so SQL referring
  to bare `memories` automatically resolves to the right schema.
- A missed filter is no longer possible — there is no global `memories`
  table to accidentally hit.

This is the same isolation pattern used by Stripe, GitLab, Heroku
Postgres-as-a-service, and (relevantly) **mypalclara isn't using it**.
We're moving _ahead_ of mypalclara here, not toward parity.

---

## 2. Strategy decisions (and the recommendations to ratify)

### 2.1 Where does the `public` schema sit?

**Recommendation:** keep two kinds of tables:

| Where | What lives there | Why |
|---|---|---|
| `public` (shared catalog) | `tenants`, `api_keys`, `audit_logs`, `alembic_version`, `reflection_jobs` (worker queue) | These are operational/cross-tenant. Splitting them per tenant would defeat the point (e.g. you want one place to enumerate API keys). |
| `<tenant>` (per-tenant) | `memories`, `messages`, `sessions`, `episodes`, `narrative_arcs`, `intentions`, `memory_dynamics`, `memory_supersession`, `memory_versions`, `memory_access_logs`, `entity_aliases`, `personality_traits` | All domain content. Hard isolation between tenants. |

`audit_logs` is the only judgement call: arguments for `public` (operators want a single timeline; cross-tenant admin actions belong in one place) outweigh arguments for per-tenant (faster queries, smaller indexes per tenant). Keep it in `public`, with `tenant_id` retained on the row.

### 2.2 Migration semantics

**Recommendation:** **Alembic stays single-source-of-truth**, but the
Alembic apply step **fans out per tenant** for per-tenant tables.

Two possible models:

- **(A) Templated DDL.** `alembic upgrade head` runs once; it owns
  `public` directly and runs per-tenant DDL inside a loop over
  `SELECT id FROM tenants`. Migration files use `op.execute()` with
  schema-qualified names.
- **(B) Multi-target Alembic.** Each tenant gets its own
  `alembic_version_<tenant>` row; `alembic upgrade head -x tenant=acme`
  upgrades just acme. CLI hides the loop.

**Pick A.** Simpler, atomic-per-revision, no parallel-revision drift between tenants. The fanout cost is fine because tenant counts are small (tens, not thousands). If we ever need (B), it's a follow-up.

### 2.3 Tenant lifecycle

**Create:** `POST /v1/admin/tenants` is the existing endpoint. Today it inserts a row in `public.tenants`. Phase 12 makes it additionally:

```sql
CREATE SCHEMA "<tenant_id>";
-- + run all per-tenant DDL from current head
```

**Drop:** new operation; require explicit confirmation (deleting a tenant deletes all their data). `DROP SCHEMA "<tenant_id>" CASCADE` plus `DELETE FROM public.tenants`. Add `DELETE /v1/admin/tenants/{id}?confirm=<id>` and `mypalace-admin tenants drop --id <id> --confirm <id>`.

**Rename:** Postgres supports `ALTER SCHEMA RENAME`, but tenant_id is referenced as a string in API keys, audit logs, and the per-tenant Qdrant collection name. Out of scope for phase 12 — call it explicit migration if needed.

### 2.4 search_path management

Two layers, neither leaking into the other:

- **Per-request:** `AuthMiddleware` already resolves the tenant for each request. After resolving, before the request handler runs, set `search_path` on the **session** (not the connection — connections are pooled and shared). Use SQLAlchemy's session event hooks or set it at the start of the request via `await db.execute(text("SET LOCAL search_path TO :s, public"))` inside a transaction.
- **Per-worker-job:** worker handlers receive `tenant_id` already; same pattern in the queue runner (`runner.py`'s `process_one`) before invoking the handler. Backup worker iterates tenants; sets per tenant.

`SET LOCAL` (transaction-scoped) is safer than `SET` (connection-scoped) because it auto-resets at transaction end — if a connection returns to the pool mid-flight, the next checkout gets a clean state. Cost is one extra round-trip per request; with `pool_pre_ping` already off-by-default elsewhere this is acceptable.

**Risk:** asyncpg connection pooling + SQLAlchemy session lifecycle. If a transaction begins **before** the SET, the search_path is wrong for that transaction. All MyPalace queries currently open `async with async_session() as db: await db.execute(...)` — fine, the SET goes in `async_session.__aenter__`. We need to push the tenant context into a contextvar so the session factory can read it without changing every callsite.

### 2.5 Vector store + graph store

Per-tenant Qdrant collections (`palace_<tenant>`) and per-tenant FalkorDB graph names already exist. **No change needed** — the Postgres schema work is orthogonal. The naming convention stays; we just stop relying on `tenant_id` columns in Postgres.

### 2.6 Cache + rate limit

Both already key on tenant. **No change.**

---

## 3. Migration path (existing → phase 12)

This is the part we should be most careful about. Existing deployments
have rows in `public.memories` etc. with `tenant_id` columns. Cutover
must be online-able for production; downtime-tolerant for solo dev.

**Proposed phased rollout** (each phase a separate PR):

### Phase 12.1 — Runtime plumbing, dual-mode

Land the plumbing **without** dropping the `tenant_id` columns:

1. Per-request `SET LOCAL search_path` driven by a `tenant_context` contextvar.
2. Tenant lifecycle endpoints learn to `CREATE SCHEMA` + replicate per-tenant DDL on tenant create.
3. Alembic 0010: copy existing `public.memories` etc. into per-tenant schemas, leaving `public.*` in place as a fallback. Shadow-write everything for one revision.
4. New code paths read from per-tenant schemas; old code paths still work because `tenant_id` columns persist.
5. Feature flag `PALACE_TENANT_SCHEMA_MODE=schema|table` (default `table`) gates which read path is active. Defaults preserve current behavior. Operators flip the flag once shadowed data is in sync.

### Phase 12.2 — Backup/export/import + admin tooling

`workers/backup.py` already iterates tenants; switch its export to use the per-tenant schema. `/v1/admin/export` and `/v1/admin/import` keep the same NDJSON wire format (records carry `_type`, no schema info) — they just read/write the per-tenant schema instead of the global table with a WHERE clause.

`mypalace-admin stats`, `tenants`, etc. switch to per-tenant queries.

### Phase 12.3 — Two-step rollout (revised after implementation)

Originally planned as one PR. Split into two during implementation
because shadow-copy and column-drop have very different reversibility
profiles, and bundling them locks operators into one big upgrade.

**12.3a (this minor — v0.11.0)** — Alembic 0010 shadow-copy migration:
for each tenant in `public.tenants`, CREATE SCHEMA + replicate per-
tenant DDL + INSERT ... SELECT every row from `public.<table>`. Default
mode stays `table`. Operators upgrade, run `alembic upgrade head`, then
flip `PALACE_TENANT_SCHEMA_MODE=schema` on their schedule. Reversible:
flip back to `table`, `alembic downgrade -1`, the per-tenant schemas
drop. Live writes during the brief in-between window go to whichever
mode is active.

**12.3b (next minor — v0.12.0)** — flip the default to `schema` and
ship Alembic 0011 dropping the legacy `tenant_id` columns + the
duplicate `public.<table>` rows. Removes the feature flag entirely.
Coincides with the v0.12.0 server-side `mypalace-admin` shim removal
(scheduled in phase 11) so all phase-12-era breaking changes happen
at one release boundary.

This **is** the irreversible step — gate on Joshua's explicit
go-ahead before tagging v0.12.0.

---

## 4. Backup / restore implications

- **Backup format unchanged.** NDJSON-per-tenant, same wire shape. Each
  tenant backup is one schema's worth of tables.
- **Restore semantics:** `/v1/admin/import?tenant_id=acme` ensures the
  `acme` schema exists (creates if not), then writes records into
  `acme.<table>` instead of `public.<table>` with a WHERE.
- **`pg_dump` interaction:** operators who want a raw Postgres-level
  backup (not via `/v1/admin/export`) can now use `pg_dump -n <tenant>`
  to dump just one tenant. Document this in `docs/deployment.md`.

## 5. Test impact

- **Mock tests:** mostly unaffected. They mock `async_session` and never
  touch real DDL. The `tenant_id` they pass to mocks just gets ignored
  by the (mocked) DB.
- **Integration tests:** every test in `tests/integration/` will need to
  be updated to create the per-tenant schema in setup. The helper
  fixture `tests/integration/conftest.py` should grow a `_ensure_schema`
  hook.
- **New tests:** schema lifecycle tests (CREATE, DROP, double-CREATE,
  drop-with-data, ALTER ownership), search_path leak tests (a request
  for tenant A must NOT be able to see tenant B's tables under any
  query path), Alembic fanout tests.

## 6. Performance

- **Connection pool:** unchanged — the same pool serves all tenants.
- **Per-request overhead:** one extra round-trip for `SET LOCAL`. Maybe
  shave to zero by piggybacking on the first query of the transaction
  (`SELECT set_config('search_path', :s, true); <query>` in one prepared
  statement); investigate in 12.1 if metrics show measurable impact.
- **Index size:** per-tenant indexes are smaller and tighter (no
  `tenant_id` column, no per-tenant filter selection). Net win for big
  tenants; basically neutral for small.
- **Query planner:** Postgres handles the schema-qualified case
  identically to the unqualified case. No surprises expected.

## 7. Out of scope for phase 12

- Per-tenant **databases** (one Postgres database per tenant). Bigger
  isolation; bigger ops. We could move there in a future phase if a
  customer requires CCPA/GDPR-grade physical isolation.
- Per-tenant **Postgres users**. `app_role` connection still owns all
  schemas. If we want hard role isolation, it's a phase-13+ story.
- Tenant-rename. Out of scope.
- Online (zero-downtime) cutover from table-mode to schema-mode in a
  multi-process deployment. Phase 12.1 + 12.2 give us
  shadow-write + dual-read; the cutover itself still wants either a
  brief maintenance window OR a careful rolling deploy. Document, don't
  automate.

## 8. Rollback plan

While the feature flag is in dual-mode (between 12.1 and 12.3):
flip `PALACE_TENANT_SCHEMA_MODE=table`, restart, done. All data is
still in `public.*`.

After 12.3 ships and `tenant_id` columns are dropped: rollback requires
a restore from backup. Treat 12.3 as the irreversible step.

## 9. Open questions

1. **`audit_logs` placement** (§2.1). Locking in `public`. Object?
2. **Drop-tenant authorization.** `--confirm <id>` flag is fine for the
   CLI, but should the HTTP endpoint require a separate scope (`admin:destructive`)? Recommendation: yes; gate it.
3. **Migration ordering inside `init_db()`.** Today `init_db` creates
   missing tables on a fresh DB. With per-tenant schemas, "fresh" means
   no schemas; we need to also bootstrap the `default` tenant's schema.
   Straightforward but must not regress the zero-config dev experience.
4. **Per-tenant connection pooling for very-large tenants.** Some
   schema-per-tenant designs (Heroku's, Citus's) split the pool by
   tenant for isolation. We're not there yet; flag if a tenant grows
   past ~5% of total query volume.

---

## 10. Decision needed from Joshua

Before phase 12.1 work starts, please ratify (or push back on):

- ✅ / ❌ Two-tier table layout (§2.1): `public` for catalog,
  per-tenant schema for domain.
- ✅ / ❌ Alembic strategy A — single-target with per-tenant fanout
  inside migrations (§2.2).
- ✅ / ❌ Tenant lifecycle: `POST /v1/admin/tenants` creates schema;
  new `DELETE /v1/admin/tenants/{id}?confirm=<id>` drops it (§2.3).
- ✅ / ❌ Per-request `SET LOCAL search_path` driven by a contextvar
  populated in `AuthMiddleware` (§2.4).
- ✅ / ❌ Three-PR rollout: 12.1 dual-mode plumbing → 12.2 backup/admin
  adaptation → 12.3 drop legacy columns + remove flag (§3).
- ✅ / ❌ Open questions (§9): audit_logs in `public`,
  destructive-scope for tenant drop.

When you sign off, I'll start phase 12.1.
