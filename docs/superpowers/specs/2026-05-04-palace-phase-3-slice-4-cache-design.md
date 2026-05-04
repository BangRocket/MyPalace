# Palace Phase 3 — Slice 4: Redis Cache

**Date:** 2026-05-04
**Branch:** `phase-3-slice-4-cache` (off `phase-3`)
**Depends on:** slice 2 (tenant scoping in cache keys)

## Goal

Read-through cache wrapping `/v1/context/layered` and `/v1/memories/search`. Keys hash (tenant, user, query, params). TTL 60s. On write (memory create/update/delete/supersede), invalidate via Redis pub/sub.

If `PALACE_REDIS_URL` is unset → cache is a no-op (every read hits the source). FalkorDB and the cache can share the same Redis instance (FalkorDB ships as a Redis module).

## Surface

- `palace/cache/__init__.py`
- `palace/cache/client.py` — async wrapper around `redis.asyncio.Redis`. Lazy connect.
- `palace/cache/decorator.py` — `cached_response(ttl, key_fn)` async decorator
- `palace/cache/invalidate.py` — pub/sub invalidator. On write events publishes `cache_bust`; subscribers in same process drop matching keys (best-effort) — for cross-worker, the TTL bounds staleness.

## Decisions

| ID | Decision | Why |
|---|---|---|
| D4.1 | Reuse Redis with FalkorDB | One container; FalkorDB shipped as Redis module |
| D4.2 | Read-through cache, never write-through | Avoids skew between cache and DB |
| D4.3 | TTL 60s for context/search, 300s for GET-by-id | Bounded staleness; cheap to refresh |
| D4.4 | Invalidate via pub/sub on write | Best-effort; TTL is the safety net |
| D4.5 | PALACE_REDIS_URL unset = no-op | Zero-config dev |
| D4.6 | Cache key includes tenant_id | Avoids cross-tenant cache hits |
| D4.7 | Bypass via PALACE_CACHE_DISABLED=true | Tests can opt out without unsetting Redis URL |

## Done criteria

- Two endpoints cached: `/v1/context/layered`, `/v1/memories/search`
- Memory write paths publish invalidation events
- Cache miss/hit tracked via simple counters (logged at INFO)
- Existing 190 mock tests pass (cache disabled in test env)
- New tests cover wrapper logic + key derivation
- README documents cache setup
