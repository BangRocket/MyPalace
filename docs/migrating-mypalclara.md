# Migrating mypalclara to mypalace 0.6.0

This guide walks you through swapping mypalclara's embedded
`ClaraMemory` + `MemoryManager` for a remote Palace 0.6.0 deployment.

The migration is non-destructive: mypalclara keeps its database during
the swap, you can roll back at any point, and the cutover is a single
config flag.

---

## Prerequisites

- A working mypalclara deployment (the one you want to migrate from).
- A Palace 0.6.0 deployment reachable from mypalclara. Quickstart in the
  Palace [README](../README.md#install). For most setups:
  ```bash
  docker pull bangrocket/mypalace:0.7.0
  docker run -d --name palace -p 8000:8000 \
    -e PALACE_DATABASE_URL=postgresql+asyncpg://palace:palace@HOST/palace \
    -e QDRANT_URL=http://HOST:6333 \
    -e PALACE_BOOTSTRAP_ADMIN_KEY=pk_live_$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32) \
    bangrocket/mypalace:0.7.0
  ```
  Save the `PALACE_BOOTSTRAP_ADMIN_KEY` value — you'll need it once.
- (Optional but recommended) Worker process for background reflection /
  synthesis / cleanup. From the same image:
  ```bash
  docker run -d --name palace-worker --link palace \
    -e PALACE_DATABASE_URL=... \
    -e QDRANT_URL=... \
    -e PALACE_WORKER_QUEUE_ENABLED=true \
    bangrocket/mypalace:0.7.0 \
    python -m palace.workers.runner
  ```

---

## 1. Mint a write-scope key for mypalclara

```bash
ADMIN_KEY=pk_live_...     # the value from PALACE_BOOTSTRAP_ADMIN_KEY

curl -X POST http://palace:8000/v1/admin/keys \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "mypalclara-prod",
    "scopes": ["read", "write"]
  }'
# → {"data": {"key_id": "...", "plaintext_key": "pk_live_...", ...}}
```

Save the `plaintext_key` — Palace returns it exactly once. This is the
key mypalclara will use for every API call.

The key is bound to the `default` tenant by default. If you want to
isolate mypalclara's data under its own tenant (recommended for
multi-app deployments), create a tenant first and bind the key to it:

```bash
curl -X POST http://palace:8000/v1/admin/tenants \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{"id": "mypalclara", "label": "MyPalClara production"}'

curl -X POST http://palace:8000/v1/admin/keys \
  -H "X-Palace-Key: $ADMIN_KEY" \
  -d '{
    "label": "mypalclara-prod",
    "scopes": ["read", "write"],
    "tenant_id": "mypalclara"
  }'
```

---

## 2. Install mypalace-client in mypalclara

```bash
pip install mypalace-client==0.6.0
```

The HTTP client only — gRPC is optional via `pip install
"mypalace-client[grpc]"` but mypalclara doesn't need it for migration.

---

## 3. Drop in the routed memory module

mypalclara has a router pattern documented in
`mypalace/examples/mypalclara_router.py` that delegates between
the embedded path and a remote Palace via per-method pass-throughs.

Copy that file into mypalclara as `mypalclara/core/memory/routed.py`,
then swap the imports anywhere mypalclara uses `PALACE` or
`MemoryManager`:

```python
# OLD
from mypalclara.core.memory import PALACE
from mypalclara.core.memory.manager import MemoryManager

# NEW
from mypalclara.core.memory.routed import PALACE, MemoryManager
```

Set the runtime env vars:

```bash
export USE_PALACE_SERVICE=true
export PALACE_SERVICE_URL=http://palace:8000
export PALACE_API_KEY=pk_live_...   # the write key from step 1
```

That's the cutover. With `USE_PALACE_SERVICE=true`, every call routes
to the remote Palace; with it unset (the default), behavior is
unchanged. Roll back at any time by unsetting that single env var.

---

## 4. Replay existing data

mypalclara already has a Discord-transcript replay script that reads
historical transcripts and writes them to the memory layer "as if Clara
were experiencing them in real time." That same script works against
remote Palace via the router — no Palace-specific port needed:

```bash
# In mypalclara, with the new env vars set:
USE_PALACE_SERVICE=true \
PALACE_SERVICE_URL=http://palace:8000 \
PALACE_API_KEY=pk_live_... \
python -m mypalclara.scripts.replay_transcripts --since=2024-01-01
```

Each transcript line goes through the normal `PALACE.add(...)` path,
which the router translates into a `POST /v1/memories/batch` against
remote Palace. Episodes get reflected via
`POST /v1/reflection/session?mode=async`, which enqueues a worker job.
Narrative arcs synthesize when the worker handler runs.

For very large replays, you may want to enable the worker queue
(`PALACE_WORKER_QUEUE_ENABLED=true` on the Palace server) so reflection
doesn't pile up in-process.

---

## 5. Validate

After replay (or after running mypalclara live for a while against the
new Palace), verify the data landed:

```bash
# Row counts per tenant
curl "http://palace:8000/v1/admin/stats?tenant_id=mypalclara" \
  -H "X-Palace-Key: $ADMIN_KEY"
# → row_counts.memories should match what you replayed

# Spot-check a search
curl -X POST http://palace:8000/v1/memories/search \
  -H "X-Palace-Key: $PALACE_API_KEY" \
  -d '{"query": "<known phrase>", "limit": 3}'

# Check change history for a sample memory
curl http://palace:8000/v1/memories/<memory_id>/history \
  -H "X-Palace-Key: $PALACE_API_KEY"
```

The audit log records every admin operation you ran:

```bash
curl "http://palace:8000/v1/admin/audit?path_prefix=/v1/admin/&limit=20" \
  -H "X-Palace-Key: $ADMIN_KEY"
```

---

## 6. Optional follow-ups

- **Subscribe to events** — mypalclara can connect to
  `wss://palace:8000/v1/events?api_key=$PALACE_API_KEY` to receive
  `memory.created` / `memory.superseded` / `intention.fired` /
  `arc.synthesized` push notifications instead of polling.
- **Layered context** — replace mypalclara's L1+L2 prompt assembly with
  a single `POST /v1/context/layered` call that returns the full
  structured payload including FSRS reranking and (optionally)
  graph-walked related memories (`include_graph=true`).
- **Smart ingestion** — pass `infer=true` to `POST /v1/memories/batch`
  to get LLM extraction + dedup + auto-supersede for free.
- **Switch to gRPC** — for memory ops only,
  `from palace_client.grpc import PalaceGrpcClient` against
  `PALACE_GRPC_PORT` (set on the server). Same API key, lower overhead.

---

## 7. Decommission mypalclara's embedded path (when ready)

Once you've run live for a while and the audit / stats / spot-checks
all look right, you can:

1. Stop running mypalclara's local Postgres + Qdrant.
2. Delete the embedded `ClaraMemory` + `MemoryManager` modules
   (the routed module no longer references them when
   `USE_PALACE_SERVICE=true`).
3. Drop the `USE_PALACE_SERVICE` env var (the routed module hard-codes
   remote-only behavior or you fold the routed module into a
   plain `palace_client.PalaceClient` wrapper).

The router pattern was deliberately kept reversible during phase 2 so
you don't have to commit irrevocably until you're confident.

---

## Rollback

If something looks wrong:

```bash
# Single-line rollback to the embedded path
unset USE_PALACE_SERVICE
# or in your service manager: USE_PALACE_SERVICE=false
```

mypalclara reads its embedded SQLite/Postgres again, no data is lost,
and the remote Palace deployment keeps whatever it ingested (you can
delete-tenant later if you want a clean slate):

```bash
curl -X DELETE "http://palace:8000/v1/admin/tenants/mypalclara" \
  -H "X-Palace-Key: $ADMIN_KEY"
# 409 if data still references the tenant — purge memories first via:
curl -X DELETE "http://palace:8000/v1/users/<user_id>/memories" \
  -H "X-Palace-Key: $PALACE_API_KEY"
```

---

## Common gotchas

- **`401 unauthenticated` everywhere** — the `X-Palace-Key` header
  isn't being sent. Check `PALACE_API_KEY` is exported in mypalclara's
  process env, not just your shell.
- **`403 cross-tenant access denied`** — your key is tenant-bound to
  `default` but you're trying to operate on `mypalclara`. Either bind
  the key to the right tenant when minting (step 1), or mint a
  cross-tenant admin key with `cross_tenant: true`.
- **Reflection jobs stuck `pending`** — no worker process is running.
  Either start one (`python -m palace.workers.runner`) or unset
  `PALACE_WORKER_QUEUE_ENABLED` so reflection runs in-process.
- **Slow searches under load** — set `PALACE_REDIS_URL` to enable the
  read-through cache; configure `PALACE_RATE_LIMIT_ENABLED=true` if
  you also want per-(tenant, key, user) limits.
- **Dim-mismatch on embedding-model swap** — see
  `POST /v1/admin/reembed` to re-embed the whole tenant under a new
  model. Plays well with `?reembed=false` on bulk import for very
  large migrations.

---

## What you get post-migration

Beyond drop-in parity, swapping in Palace gives mypalclara:

- **Multi-tenancy** — run multiple agents against one Palace
- **Per-key auth + scopes + audit trail** — compliance-friendly
- **WebSocket events** — push instead of poll for new memories /
  intentions / episodes
- **Background workers** — reflection + synthesis don't block requests
- **Layered context with graph enrichment** — single call replaces
  manual L1+L2 prompt assembly
- **Memory TTL + cleanup** — session-scoped memories auto-expire
- **Disaster recovery** — `GET /v1/admin/export` for tenant dumps
- **Embedding model migration** — swap models without losing data
- **Memory change history + supersession audit** — full forensics on
  any memory's lifecycle
- **Cross-tenant search** — admin tooling for support / debugging

mypalclara's existing replay script is the only migration tool you need;
everything else is operator config.
