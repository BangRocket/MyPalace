# Palace Phase 5 — Master Plan

**Date:** 2026-05-04
**Branch:** `phase-5`
**Goal:** Close the deliberately-deferred items from phase 3+4, ship the full gRPC surface, and add the analytics endpoints support/ops will inevitably ask for. Tag `v0.4.0`.

Four slices. Same phase-3/4 cadence — design upfront, power through, stop only on real blockers.

## Cuts

- **Per-tenant Postgres schemas** — speculative; operators who need that level of isolation should run separate Palace deployments per tenant.
- **Admin web UI** — different skill (frontend) and not load-bearing for any backend consumer. Worth its own phase if requested.

## Slice ordering

```
1. carry-over     — workers-by-default flag + episode/intention/arc publishers
2. grpc-mirror    — sessions, episodes, arcs, intentions, dynamics, retrieval, ingestion, jobs
3. analytics      — /v1/admin/stats with row counts, activity, FSRS health
4. release        — bump to 0.4.0, CHANGELOG, tag, watch the workflow
```

---

## Slice 1 — Deferred wire-ups (workers + events)

### Surface

- `palace/config.py` — `worker_queue_enabled: bool` from `PALACE_WORKER_QUEUE_ENABLED`
- `palace/api/episodes.py` — when `worker_queue_enabled` and `mode != "sync"`, route to `workers.enqueue("reflection", payload, user_id, tenant_id)` instead of `job_service.run_async`
- `palace/api/arcs.py` — same for `synthesis`
- `palace/episode_service.py` — after each successful reflection batch, publish `episode.created` per episode
- `palace/intentions/service.py` — after `check()` returns matches, publish `intention.fired` per fired intention
- `palace/arc_service.py` — after `synthesize_narratives` writes new arcs, publish `arc.synthesized` per arc

### Decisions

- D1.1 — `worker_queue_enabled` is opt-in (defaults False). Existing deployments without a worker process keep working.
- D1.2 — Publishers are fire-and-forget like the graph layer; failures log+swallow.
- D1.3 — `intention.fired` payload includes `id`, `content`, `trigger_type`, `priority`, `match_details` (matches `FiredIntentionOut`).

### Tests

- Unit: route handlers call `enqueue` when flag set, `run_async` otherwise.
- Unit: episode/intention/arc paths publish events with correct shape.
- Existing 268 mock tests stay green.

---

## Slice 2 — gRPC mirror of remaining surfaces

### Surface

`proto/palace.proto` grows ~8 service definitions:

```proto
service SessionService {
  rpc CreateSession(...) returns (SessionResponse);
  rpc GetSession(...) returns (SessionWithMessagesResponse);
  rpc AddMessage(...) returns (MessageResponse);
  rpc UpdateSession(...) returns (SessionResponse);
  rpc DeleteSession(...) returns (DeleteResponse);
}
service EpisodeService {
  rpc ReflectSession(...) returns (JobPendingOrEpisodesResponse);
  rpc SearchEpisodes(...) returns (EpisodesResponse);
  rpc GetRecentEpisodes(...) returns (EpisodesResponse);
}
service ArcService {
  rpc SynthesizeNarratives(...) returns (JobPendingOrArcsResponse);
  rpc GetActiveArcs(...) returns (ArcsResponse);
}
service IntentionService {
  rpc SetIntention(...) returns (IntentionResponse);
  rpc CheckIntentions(...) returns (FiredIntentionsResponse);
  rpc FormatIntentions(...) returns (FormattedIntentionsResponse);
  rpc ListIntentions(...) returns (IntentionsResponse);
  rpc DeleteIntention(...) returns (DeleteResponse);
}
service DynamicsService {
  rpc PromoteMemory(...) returns (DynamicsResponse);
  rpc DemoteMemory(...) returns (DynamicsResponse);
  rpc GetDynamics(...) returns (DynamicsResponse);
  rpc ScoreMemory(...) returns (ScoreBreakdownResponse);
}
service RetrievalService {
  rpc AssembleLayered(...) returns (LayeredContextResponse);
}
service IngestionService {
  rpc SupersedeMemory(...) returns (SupersessionResponse);
  rpc GetSupersessions(...) returns (SupersessionsResponse);
}
service JobService {
  rpc GetJob(...) returns (JobResponse);
}
```

### Decisions

- D2.1 — Same checked-in-stub pattern as phase 3 slice 5. Regenerate via the documented `protoc` invocation.
- D2.2 — Async-mode endpoints (reflection, synthesis) return a `oneof` of `JobPending` or the materialized result so the proto is honest about mode-dependent shapes.
- D2.3 — Auth interceptor `RPC_SCOPE` map extended; same scope rules as HTTP.
- D2.4 — `PalaceGrpcClient` mirrors all new methods; HTTP client stays the canonical reference.

### Tests

- Servicer unit tests for each service (mocking the underlying `*_service` singleton). Pattern from phase 3 slice 5 carries over verbatim.
- Auth interceptor scope-map test covers the new methods.

---

## Slice 3 — Cross-tenant analytics

### Surface

- `palace/api/stats.py` — admin-scope endpoints
- `GET /v1/admin/stats?tenant_id=...` — single-tenant snapshot
- `GET /v1/admin/stats?tenant_id=ALL` — across-all-tenants summary (cross-tenant admin keys only)

### Returned shape

```json
{
  "tenant_id": "acme",
  "row_counts": {
    "memories": 12453,
    "sessions": 87,
    "episodes": 412,
    "narrative_arcs": 23,
    "intentions": 14,
    "memory_supersessions": 89
  },
  "activity_7d": {
    "memories_created": 312,
    "memories_accessed": 1844,
    "episodes_reflected": 41,
    "intentions_fired": 7
  },
  "top_users_by_access_7d": [
    {"user_id": "u1", "access_count": 412},
    {"user_id": "u2", "access_count": 188}
  ],
  "fsrs_health": {
    "tracked_memories": 8421,
    "key_memories": 318,
    "mean_stability": 4.21,
    "mean_retrieval_strength": 0.83
  }
}
```

### Decisions

- D3.1 — All counts come from a single round-trip with grouped queries; no per-tenant N+1 even in ALL mode.
- D3.2 — Top-N capped at 10. Activity windows hard-coded to 7d for v1; configurable later.
- D3.3 — Cross-tenant aggregation via `?tenant_id=ALL` returns `{tenants: [...]}` instead of a single object.

### Tests

- Unit: stats route returns expected shape against mocked service.
- Live integration: insert a known fixture set, assert counts match.

---

## Slice 4 — v0.4.0 release

- Bump `palace-memory` and `palace-client` to `0.4.0`.
- CHANGELOG entry covering all 3 phase-5 slices.
- Re-tag flow if anything fails — same as the v0.3.0 tag dance.
- Tag `v0.4.0`, watch the workflow.

---

## Done criteria

- All 4 slices merged to `phase-5`
- 290+ mock tests pass; 53+ client tests pass
- gRPC servicer test count goes from 8 → ~40
- Live integration tests pass against full stack
- `phase-5` merged to `main`, `v0.4.0` tagged, release workflow green
