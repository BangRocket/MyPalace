# Palace Phase 3 — Slice 3: Graph (FalkorDB)

**Date:** 2026-05-04
**Branch:** `phase-3-slice-3-graph` (off `phase-3`)
**Depends on:** slice 2 (tenant-scoped graphs)

## Goal

Wrap FalkorDB. Async-write a graph edge whenever a memory, episode, arc, or supersession is created. Expose `/v1/graph/neighbors` for n-hop traversal. Layered retrieval gains an optional `l3_graph_context` slot.

If `PALACE_FALKORDB_URL` is unset, the graph is a no-op (skips writes, neighbors endpoint returns 503). This keeps the dev story and existing test suite zero-config.

## Surface

### Module: `palace/graph/`

- `palace/graph/__init__.py`
- `palace/graph/client.py` — async FalkorDB wrapper. One graph per tenant: `palace_<tenant_id>`.
- `palace/graph/service.py` — `GraphService` with `upsert_memory_node`, `upsert_episode_node`, `upsert_arc_node`, `add_supersedes_edge`, `add_mentions_edge`, `neighbors`.
- `palace/api/graph.py` — `GET /v1/graph/neighbors?node_id=...&depth=2`

### Schema (Cypher)

```
(:Memory {id, user_id, agent_id, content, memory_type, importance})
(:Episode {id, user_id, summary, significance, timestamp})
(:Arc {id, user_id, title, status})
(:Topic {name})

(Memory)-[:MENTIONS]->(Topic)
(Episode)-[:MENTIONS]->(Topic)
(Episode)-[:PARTICIPATES_IN]->(Arc)
(Memory)-[:SUPERSEDES]->(Memory)
(Memory)-[:RELATES_TO {weight}]->(Memory)
```

One graph per tenant: `palace_<tenant_id>` (FalkorDB graphs are namespaces in a single Redis instance).

### Write path

Memory create / episode create / arc create / supersede each schedule a fire-and-forget asyncio task that calls the graph service. Failures log a WARNING but never break the primary write. Pattern:

```python
async def _async_graph_write(coro_factory):
    if not graph_service.enabled:
        return
    asyncio.create_task(_safe(coro_factory))
```

### Read path

`GET /v1/graph/neighbors?node_id=<id>&depth=2&edge_type=MENTIONS` — returns `{nodes: [...], edges: [...]}`. Tenant resolved from auth context; graph queried is `palace_<tenant_id>`.

Layered retrieval grows optional `include_graph: bool = False` flag; when true, includes `l3_graph_context: {memories: [...]}` populated from 1-hop neighbors of the L2 results.

## Decisions

| ID | Decision | Why |
|---|---|---|
| D3.1 | FalkorDB | Cypher + Redis-protocol; matches mypalclara |
| D3.2 | Async writes via asyncio.create_task | Graph is enrichment, not source of truth; latency tax unacceptable |
| D3.3 | One graph per tenant | Hard isolation; cheap to drop entire tenant |
| D3.4 | No-op when PALACE_FALKORDB_URL unset | Keep dev/test zero-config |
| D3.5 | /v1/graph/neighbors only — no Cypher passthrough | Don't expose full DB attack surface |
| D3.6 | Layered include_graph defaults False | Backwards-compatible |

## Files

**Create:**
- `palace/graph/__init__.py`
- `palace/graph/client.py`
- `palace/graph/service.py`
- `palace/api/graph.py`
- `tests/test_graph_service.py`
- `tests/test_graph_routes.py`
- `tests/integration/test_graph_live.py` (skipped unless FalkorDB available)

**Modify:**
- `palace/main.py` — register graph router
- `palace/config.py` — `falkordb_url` setting (default None)
- `palace/memory_service.py` — fire-and-forget graph upsert in `create`
- `palace/episode_service.py` — same
- `palace/arc_service.py` — same
- `palace/retrieval/ingestion.py` — fire-and-forget SUPERSEDES edge
- `palace/api/retrieval.py` — accept `include_graph` flag
- `palace/retrieval/layered.py` — populate `l3_graph_context` when enabled
- `pyproject.toml` — add `falkordb>=1.0` dep
- `README.md` — graph section

## Done criteria

- Memory/Episode/Arc create writes to graph asynchronously when configured
- `/v1/graph/neighbors` returns n-hop neighbors for a node
- Existing 174 mock tests still pass (graph defaults to disabled in test env)
- New unit tests cover service + routes (mocking the FalkorDB client)
- Live integration test optional (skipped if no FalkorDB env var)
- README documents graph setup
- Merged to phase-3
