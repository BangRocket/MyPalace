# Deploying MyPalace in production

This guide covers a single-host docker-compose deployment of MyPalace
0.11.0 with all five backends, a worker process, and the recommended
defaults for production. The compose file is at
[`docker-compose.prod.yml`](../docker-compose.prod.yml).

For multi-host / Kubernetes setups, the compose file is the canonical
reference for what containers and env vars to wire up; translate to
your orchestrator of choice.

---

## What you get

- **`mypalace`** — the FastAPI server on port 8000
- **`worker`** — `python -m mypalace.workers.runner` for background
  reflection / synthesis / cleanup / reembed jobs
- **`postgres`** — Postgres 16 with persistent volume
- **`qdrant`** — Qdrant v1.12.0 with persistent volume
- **`falkordb`** — FalkorDB (Redis-protocol) with appendonly persistence,
  used by **all three** of the graph layer, the cache, and the rate
  limiter (it ships as a Redis module so a single instance covers
  everything)

Healthchecks + `restart: unless-stopped` on every container.

---

## Quickstart

```bash
# 1. Copy the env template + fill in the bootstrap key
cp .env.example .env
$EDITOR .env   # set PALACE_BOOTSTRAP_ADMIN_KEY (instructions in the file)

# 2. Bring everything up
docker compose -f docker-compose.prod.yml up -d

# 3. Watch the logs until you see "Palace bootstrap admin key registered"
docker compose -f docker-compose.prod.yml logs -f mypalace

# 4. Smoke
curl http://localhost:8000/health/deep | jq
# Expect: {"status":"ok", "service":"mypalace", "backends":[...]}
```

If any backend reports `ok=false`, check that container's logs:

```bash
docker compose -f docker-compose.prod.yml logs postgres qdrant falkordb
```

---

## Required env vars

| Var | Purpose |
|---|---|
| `PALACE_BOOTSTRAP_ADMIN_KEY` | Cross-tenant admin key minted on first boot. Format `pk_live_<32 alphanumeric>`. Refuses to start if malformed. Save the value once — MyPalace doesn't log it. |

The boot config validator (phase 8 slice 1) will refuse to start the
container if any required var is missing or malformed; you'll see a
clean message in the logs rather than a confusing first-request crash.

---

## Recommended env vars (set in `.env.example`)

| Var | Default | Why |
|---|---|---|
| `MYPALACE_VERSION` | `0.11.0` | Pin the image tag; bump on upgrade |
| `POSTGRES_PASSWORD` | `mypalace` | Change for anything public-facing |
| `EMBEDDING_PROVIDER` | `huggingface` | Local embeddings — no per-call cost |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Small, fast, decent quality |
| `LLM_API_KEY` | (empty) | Required for reflection / smart-ingestion / synthesis. OpenRouter key works out of the box |
| `PALACE_CACHE_TTL_SEARCH` | `60` | Seconds to cache `/context/layered` and `/memories/search` |
| `PALACE_DB_SLOW_QUERY_MS` | `200` | Threshold for slow-query log + counter |
| `PALACE_DB_POOL_SIZE` | `5` | SQLAlchemy connection pool size per process. Bump to 10–20 under sustained load |
| `PALACE_DB_MAX_OVERFLOW` | `10` | Burst capacity beyond `pool_size`. Total max connections = pool_size + max_overflow |
| `PALACE_DB_POOL_TIMEOUT` | `30` | Seconds a request waits for a free connection before erroring |
| `PALACE_DB_POOL_RECYCLE` | `1800` | Recycle connections older than this (seconds). Mitigates idle-timeout drops from pgbouncer / cloud Postgres |
| `PALACE_DB_POOL_PRE_PING` | `true` | Validate connection with `SELECT 1` before each checkout. Costs 1 extra round-trip per request but eliminates "stale connection" errors after Postgres restarts |
| `PALACE_CONTEXT_BUDGET_L1_TOKENS` | `800` | Per-request L1 (user-profile) layer budget in tokens. Converts to chars at 4×. Defaults reproduce the legacy hardcoded 3200 chars. |
| `PALACE_CONTEXT_BUDGET_L2_TOKENS` | `3000` | Per-request L2 (relevant-context) layer budget in tokens. Defaults reproduce the legacy hardcoded 12000 chars. |
| `PALACE_EMBEDDING_CACHE_DISABLED` | `false` | Skip the Redis embedding cache wrapper even when `PALACE_REDIS_URL` is set. Useful for cost-control debugging or to verify embedding determinism. |
| `PALACE_EMBEDDING_CACHE_TTL` | `2592000` (30d) | TTL for cached `(model, text) → vector` entries. Embeddings are deterministic for a given model+text so a long TTL is safe; lower if you frequently switch embedding models. |

The compose file enables the recommended production knobs by default:

- `PALACE_RATE_LIMIT_ENABLED=true` — sliding-window rate limits via Redis
- `PALACE_WORKER_QUEUE_ENABLED=true` — async reflection / synthesis route
  through the worker queue instead of the request process
- `PALACE_LOG_FORMAT=json` — structured logs for production log shippers

---

## First-time setup after boot

Either drive the admin surface with curl directly, or install the
operator CLI (recommended):

```bash
pipx install 'mypalace-client[cli]'   # or: pip install ...
export MYPALACE_URL=http://localhost:8000
export MYPALACE_ADMIN_KEY=$(grep PALACE_BOOTSTRAP_ADMIN_KEY .env | cut -d= -f2)
```

```bash
ADMIN_KEY=$(grep PALACE_BOOTSTRAP_ADMIN_KEY .env | cut -d= -f2)

# 1. Create your tenant (or use the auto-created `default` tenant)
mypalace-admin tenants create --id acme --label "Acme Corp"
# or:
curl -X POST http://localhost:8000/v1/admin/tenants \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"id":"acme","label":"Acme Corp"}'

# 2. Mint a tenant-bound write key for your application
mypalace-admin keys mint --label acme-prod --scopes read,write --tenant-id acme
# → save the plaintext_key from the output

# 3. (Optional) confirm the bootstrap admin key is the only cross-tenant key
curl http://localhost:8000/v1/admin/keys -H "X-Palace-Key: $ADMIN_KEY" | jq
```

---

## Scaling

### Web

```bash
docker compose -f docker-compose.prod.yml up -d --scale mypalace=3
```

You'll need a TCP load balancer (nginx, HAProxy, your cloud LB) in
front of the three containers. Bind the public port to the LB instead
of directly to one container by removing `MYPALACE_HTTP_PORT` from `.env`
and exposing each container only on the docker network.

### Workers

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=2
```

Multiple workers safely share the queue — the
`SELECT … FOR UPDATE SKIP LOCKED` claim semantics ensure no two workers
ever process the same job. Add more workers when:

- Reflection / synthesis backlog is growing (check
  `palace_jobs_total{kind=reflection,outcome=enqueued}` vs
  `outcome=completed` over time)
- Cleanup runs aren't keeping up with TTL'd memory volume
- You've kicked off a large `/v1/admin/reembed` job

---

## Observability

### Metrics

`/metrics` is unauthenticated (Prometheus scrapers need that). Common
queries:

```promql
# Request rate by endpoint
sum(rate(palace_http_requests_total[5m])) by (route)

# 99th percentile latency
histogram_quantile(0.99, sum(rate(palace_http_request_duration_seconds_bucket[5m])) by (le, route))

# Cache hit rate
sum(rate(palace_cache_hits_total[5m])) by (namespace)
  /
(sum(rate(palace_cache_hits_total[5m])) by (namespace) + sum(rate(palace_cache_misses_total[5m])) by (namespace))

# Slow query rate (phase 8 slice 2)
sum(rate(palace_db_slow_queries_total[5m])) by (operation)

# Worker job throughput
sum(rate(palace_jobs_total[5m])) by (kind, outcome)
```

### Structured logs

`PALACE_LOG_FORMAT=json` (the production default) emits one JSON object
per line — pipe straight into Vector, Fluentbit, or `docker logs --json`.
Every request has a `request_id`, `tenant_id`, and `key_id` bound by the
observability middleware.

### Traces (optional)

Set `PALACE_OTLP_ENDPOINT=http://your-otel-collector:4317` and install
the optional extra: `pip install "mypalace[otel]"` (or use a custom
image). FastAPI + httpx are auto-instrumented.

### Audit trail

Every `/v1/admin/*` and `/v1/maintenance/*` call lands in the
`audit_logs` table. Query via:

```bash
curl "http://localhost:8000/v1/admin/audit?since=2026-05-04T00:00:00Z&limit=50" \
  -H "X-Palace-Key: $ADMIN_KEY" | jq
```

---

## Backups

### Postgres

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U mypalace mypalace | gzip > mypalace-pg-$(date +%F).sql.gz
```

### Qdrant

The `qdrant-data` volume holds all collections. Snapshot the docker
volume on a schedule via your backup tool of choice. Per-tenant rebuild
via `/v1/admin/reembed` is the disaster-recovery path if you lose this.

### Bulk export per tenant

For tenant migration or pre-upgrade snapshots:

```bash
curl "http://localhost:8000/v1/admin/export?tenant_id=acme" \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -o mypalace-acme-$(date +%F).ndjson
```

NDJSON is greppable, diffable, and stable across embedding-model swaps
(vectors aren't included — re-embed on import).

---

## Upgrading

```bash
# 1. Bump MYPALACE_VERSION in .env
$EDITOR .env

# 2. Pull the new image
docker compose -f docker-compose.prod.yml pull mypalace worker

# 3. Restart with the new image (compose will recreate just the
#    services whose image changed)
docker compose -f docker-compose.prod.yml up -d
```

Schema migrations are applied automatically on startup via
`init_db()` (which stamps Alembic on first boot) plus
`alembic upgrade head` invoked manually if a tag introduces a new
migration. Check the CHANGELOG for migration callouts.

---

## Common operational scenarios

### Rotate the bootstrap admin key

The bootstrap key is just a regular API key minted from
`PALACE_BOOTSTRAP_ADMIN_KEY` on first boot. To rotate:

1. Mint a new admin key via `POST /v1/admin/keys` using the existing one
2. Use the new key for everything going forward
3. Revoke the old one: `DELETE /v1/admin/keys/{key_id}`
4. Update `PALACE_BOOTSTRAP_ADMIN_KEY` in `.env` to the new key value
   (so a fresh container start with the same DB picks it up — though
   the bootstrap is idempotent and will skip if any admin key already
   exists)

### Re-embed a tenant under a new model

Pair with a temporary worker scale-up if the tenant is large:

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=4

curl -X POST http://localhost:8000/v1/admin/reembed \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"tenant_id":"acme","provider":"openai","model":"text-embedding-3-large","batch_size":50}'
# → returns {"job_id":"..."}; poll /v1/jobs/{id} for completion

# Scale back down when done
docker compose -f docker-compose.prod.yml up -d --scale worker=1
```

### Scheduled backups

The optional `backup` service writes one gzipped NDJSON file per tenant
to `/backups` inside the container (mounted on the `backup-data` named
volume). Disabled by default — enable with the `backup` compose profile:

```bash
# In .env
PALACE_BACKUP_INTERVAL_HOURS=24       # default
PALACE_BACKUP_RETAIN_DAYS=7           # default

docker compose -f docker-compose.prod.yml --profile backup up -d backup

# Inspect contents
docker compose -f docker-compose.prod.yml exec backup ls -lh /backups

# Copy off-host on a cron
docker compose -f docker-compose.prod.yml cp backup:/backups ./offsite-backups
```

The backup wire format matches `/v1/admin/export` exactly, so any file
under `/backups` is restorable via `/v1/admin/import`:

```bash
gunzip -c offsite-backups/acme-20260504T000000Z.ndjson.gz | \
  curl -X POST "http://localhost:8000/v1/admin/import?tenant_id=acme" \
       -H "X-Palace-Key: $ADMIN_KEY" \
       --data-binary @-
```

The worker prunes `*.ndjson.gz` files older than `RETAIN_DAYS` on every
pass. Pruning uses mtime, not the timestamp embedded in the filename —
clock-skew safe.

### Drain workers gracefully

`docker compose -f docker-compose.prod.yml stop worker` sends SIGTERM;
the runner finishes the in-flight job and exits. Lease semantics ensure
that if a worker is killed mid-job, another worker picks up the row
after `PALACE_WORKER_LEASE_SECONDS` (default 60s).

---

## Admin web UI (phase 13)

Operators can manage MyPalace from a browser. The UI is bundled into
the production Docker image; no extra service to run.

```bash
# After `docker compose up`, hit:
open http://localhost:8000/admin/

# Sign in with any key that has the admin scope. The bootstrap admin
# key from .env works:
echo "$PALACE_BOOTSTRAP_ADMIN_KEY"
```

Surface (v1):

- **Health** — live backend status (Postgres / Qdrant / FalkorDB / Redis).
- **Tenants** — list, create, delete.
- **API keys** — list (incl. revoked), mint with one-time plaintext display, revoke.
- **Stats** — per-tenant or `ALL` row counts, 7d activity, FSRS health, top users.
- **Audit log** — recent admin operations with method/path/key filters.
- **Memories** — read-only per-user browser.

Auth model: admin API key in `sessionStorage` (closing the tab signs out). Same key that works with `mypalace-admin` and `curl`. Same trust boundary.

Same-origin only; no extra CORS configuration. If you need to host the UI on a separate origin, that's not supported in v1 — file an issue.

If the UI doesn't load (404 at `/admin/`), the server failed to find the built bundle. The server logs `admin UI bundle not found; /admin disabled` at boot. Either:

- run a release image (the multi-stage build always includes the UI), or
- build it into a dev install: `cd apps/admin-ui && npm install && npm run build`.

## Per-tenant Postgres schemas (phase 12)

Phase 12 moves tenant isolation from `WHERE tenant_id = ...` filtering
to dedicated Postgres schemas (`acme.memories`, `globex.memories`,
etc.). Default mode stays `table` through v0.11.x — the schema mode is
opt-in until v0.12.0.

### Cutover from table-mode to schema-mode (v0.11.x)

```bash
# 1. Run the shadow-copy migration. For every existing tenant this
#    creates the schema + copies the data over. Idempotent (safe to
#    re-run). Legacy public.* rows are preserved as a fallback.
alembic upgrade head

# 2. Spot-check that the per-tenant schemas have the expected row counts
#    against the legacy public.* tables (per tenant):
psql -c "SELECT count(*) FROM acme.memories"
psql -c "SELECT count(*) FROM public.memories WHERE tenant_id='acme'"

# 3. Flip the flag and restart. New writes go to <tenant>.<table>;
#    SET LOCAL search_path scopes every query.
echo "PALACE_TENANT_SCHEMA_MODE=schema" >> .env
docker compose -f docker-compose.prod.yml restart mypalace worker

# 4. Smoke-test against the live API:
mypalace-admin tenants list
mypalace-admin stats acme
```

### Reverting from schema-mode back to table-mode

If something looks wrong after step 3, you can fall back. Live writes
that landed in `<tenant>.<table>` between the flip and the revert will
NOT propagate to `public.<table>` — that's why backups before any flag
flip matter.

```bash
# Flip the flag back, restart.
sed -i 's/PALACE_TENANT_SCHEMA_MODE=schema/PALACE_TENANT_SCHEMA_MODE=table/' .env
docker compose -f docker-compose.prod.yml restart mypalace worker

# (Optional) drop the per-tenant schemas to free disk:
alembic downgrade -1
```

### `pg_dump` per-tenant

Schema-mode enables single-tenant raw dumps without the rest:

```bash
pg_dump -h <host> -U mypalace -n acme mypalace_db > acme.sql
```

Restore the same way (`pg_restore -d ...`). For application-level
migration the `mypalace-admin export` / `import` round-trip remains
the canonical path — `pg_dump` is for ops-side disaster recovery only.

### v0.12.0 — irreversible cutover

When v0.12.0 ships, default mode flips to `schema` and Alembic 0011
drops the legacy `public.<table>` rows + `tenant_id` columns. **Run
the v0.11.x cutover above first**, verify everything works under
schema-mode, then upgrade to v0.12.0. Once 0011 runs there is no
table-mode to fall back to.

## Troubleshooting

- **`/ready` returns 503** (alias: `/health/deep`) — at least one backend
  isn't answering. The `backends` array in the response identifies which
  one. Most often: Postgres connection pool exhausted under load (raise
  `PALACE_DB_POOL_SIZE` / `PALACE_DB_MAX_OVERFLOW`), or FalkorDB
  persistence I/O blocking the event loop (consider moving to a separate
  Redis instance for the cache + rate limiter and keeping FalkorDB for
  graph only).
- **`/live` is the k8s livenessProbe**, `/ready` is the readinessProbe.
  `/live` only checks that the process is up — it intentionally does NOT
  ping backends so that a transient Postgres blip doesn't trigger pod
  restarts. Use `/ready` for the readinessProbe so traffic drains when a
  backend is down. `/health` and `/health/deep` remain as back-compat
  aliases.
- **Slow query log is loud** — `PALACE_DB_SLOW_QUERY_MS` defaults to
  200ms. Tune up if your backend is fundamentally slower (e.g. on
  burstable cloud instances) and track the
  `palace_db_slow_queries_total` counter for trends.
- **`/v1/reflection/session` returns 202 with `job_id` but the job
  never completes** — no worker process running, OR
  `PALACE_WORKER_QUEUE_ENABLED` is set on the web but no worker is
  consuming. Confirm `docker compose ... ps worker` shows it healthy
  and check `docker compose ... logs worker`.
- **`401 unauthenticated` from a known-good key** — the rate-limit
  middleware rejected it; check `Retry-After` header. If you didn't
  expect this key to be limited, mint it with the `unlimited` scope.
