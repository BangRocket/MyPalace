# Palace Phase 2 Slice 5 — Layered Retrieval + Smart Ingestion

**Branch:** `phase-2-slice-5-layered`

## Background

Final slice of phase 2. Combines two related capabilities from mypalclara:

- **Layered retrieval** — multi-tier context assembly (semantic memories + episodes + active arcs + recent messages), token-budgeted, optionally FSRS-ranked. Replaces the simple `/v1/context` from slice 1.
- **Smart ingestion** — activates the `infer=True` flag on `/v1/memories/batch` (currently a no-op per spec D7 of slice 1). LLM-driven extraction with vector-similarity dedup and heuristic-based auto-supersedence.

Depends on slices 2 (episodes + arcs) and 3 (FSRS dynamics) which are merged.

## Surface area (verified)

- `MM.build_prompt_layered` → `PromptBuilder.build_prompt_layered` (`mypalclara/core/prompt_builder.py:356`) returns a list of typed Message dicts. Composes L0 (persona — Discord-specific), L1 (user profile), L2 (relevant context), plus VCH and Discord-specific blocks.
- `MemoryRetriever.fetch_context` (`mypalclara/core/memory/retrieval.py`) uses ThreadPoolExecutor + Redis cache + FSRS re-ranking + graph dedup. Returns `(user_memories, project_memories, graph_relations)`.
- `LayeredRetrieval.build_context` (`mypalclara/core/memory/retrieval_layers.py:309`) — token-budgeted formatter.
- `ClaraMemory.add(infer=True)` (`mypalclara/core/memory/core/memory.py:263`) calls `_add_to_vector_store` which invokes the LLM to extract facts.
- `MemoryIngestionManager.smart_ingest` (`mypalclara/core/memory/ingestion.py:101`) — vector dedup + heuristic contradiction detection. Thresholds from `config.py:41-43`: `SKIP_THRESHOLD=0.95`, `UPDATE_THRESHOLD=0.75`, `SUPERSEDE_THRESHOLD=0.6`.
- `MemorySupersession` table (`ingestion.py:215`) tracks `(superseded_id, new_id, reason, similarity_score)`.

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| **D1** | `POST /v1/context/layered` returns a **structured dict** (memories/episodes/arcs/recent_messages/supersession_metadata), NOT a list of LLM messages. Caller composes into prompts. | Drops Discord/persona-specific layers (L0 SOUL.md/IDENTITY.md, channel_context, vault_snapshot, user_workspace). Keeps Palace generic. |
| **D2** | Layered context is **token-budgeted via char count** (rough 4-chars-per-token approximation). Defaults: `max_l1_chars=800*4=3200`, `max_l2_chars=3000*4=12000`. Configurable per request. | Avoids adding `tiktoken` as a dependency. Char count is good enough for budget enforcement; precise counting can come later. |
| **D3** | Layered context **uses FSRS for re-ranking** when dynamics are available. Falls back to pure semantic score when no dynamics row exists. | Matches mypalclara's `_rank_results_with_fsrs_batch` flow. |
| **D4** | Smart ingestion thresholds match mypalclara: `SKIP=0.95`, `UPDATE=0.75`, `SUPERSEDE=0.6`. Configurable via env. | Same numbers gateway/processor.py is tuned for. |
| **D5** | Heuristic contradiction detection is **no-LLM** (matches mypalclara pattern: word-level antonym + negation cues). Auto-supersede only when contradiction confidence > 0.7. | Keeps the hot ingestion path fast. The LLM extraction itself is the only LLM call. |
| **D6** | New `MemorySupersession` Postgres table tracks history. NOT a hard FK (memories may have been deleted) — just memory_id strings. | Audit log; no integrity constraints on memories that may be purged. |
| **D7** | Skip graph entirely (FalkorDB is phase 3). No graph queries in layered context, no graph relations field in the response. | Keeps slice scope manageable. |
| **D8** | Existing slice-1 `/v1/context` endpoint stays unchanged for backward compatibility. New `/v1/context/layered` is additive. | mypalclara router will call the new one when toggle is on; older callers keep working. |
| **D9** | `infer=True` on `/v1/memories/batch` activates the smart-ingestion path (LLM extraction + dedup). `infer=False` keeps slice-1 verbatim behavior. The slice-1 test that asserts `infer=True` is forwarded-but-ignored gets updated to assert the new behavior with a stubbed LLM. | Was forward-compat per slice-1 D7; slice-5 makes it real. |

## Wire contract

### `POST /v1/context/layered`

```json
{
  "user_id": "u1",
  "query": "career growth",
  "agent_id": "clara",
  "session_id": "s-1",                  // optional; pulls recent_messages if provided
  "max_l1_chars": 3200,
  "max_l2_chars": 12000,
  "max_recent_messages": 20,
  "use_fsrs": true,
  "memory_limit": 10,
  "episode_limit": 5,
  "min_episode_significance": 0.3
}

→ 200 {
  "data": {
    "l1_user_profile": {
      "memories": [MemoryWithScore],   // top semantic memories
      "recent_episodes": [Episode],
      "active_arcs": [NarrativeArc]
    },
    "l2_relevant_context": {
      "memories": [MemoryWithScore],   // FSRS-reranked when use_fsrs=true
      "episodes": [Episode]            // semantic-matched
    },
    "recent_messages": [Message] | null,
    "summary": null,                   // session.summary if available
    "char_counts": { "l1": N, "l2": N }
  },
  "meta": { "took_ms": N }
}
```

`MemoryWithScore` = `Memory` extended with `score` (semantic) and optional `composite_score`/`fsrs_score`.

### Updated `POST /v1/memories/batch`

When `infer=True`:
1. Concatenate the messages into a conversation block
2. Call LLM with the smart-ingest prompt (extracts list of factual memories, each with content/category/importance/sensitivity)
3. For each extracted memory:
   a. Embed + search Qdrant for nearest existing memory (same user, same agent)
   b. If `score > SKIP_THRESHOLD` (0.95) — skip (memory is duplicate)
   c. If `score > UPDATE_THRESHOLD` (0.75) — run heuristic contradiction check; if contradiction confidence > 0.7, supersede the old memory; else skip (memory is similar enough)
   d. Else — write the new memory
4. Return the list of memories actually written + a `supersessions` field listing any (old_id, new_id, similarity, reason) pairs.

Response shape extends slice-1's:
```json
{
  "data": [Memory, ...],
  "meta": {
    "count": N,
    "took_ms": N,
    "supersessions": [{"superseded_id": "...", "new_id": "...", "similarity": 0.78, "reason": "contradiction:negation"}],
    "skipped": [{"reason": "duplicate", "similarity": 0.97}]   // optional debug info
  }
}
```

### `POST /v1/memories/{memory_id}/supersede`

```json
{ "user_id": "u1", "new_content": "Updated fact about user", "reason": "manual_correction", "metadata": {} }

→ 200 { "data": { "superseded_id": "...", "new_id": "...", "reason": "..." }, "meta": {...} }
```

Manual supersede — replaces an existing memory with a new one. Demotes the old (calls dynamics service) and creates a new memory linked via `MemorySupersession`.

### `GET /v1/memories/{memory_id}/supersedes`

```
→ 200 { "data": [{"superseded_id": "...", "new_id": "...", "reason": "...", "similarity_score": 0.8, "created_at": "..."}], "meta": {...} }
```

Returns any supersession history involving this memory_id (as either side).

## Data model

```python
class MemorySupersession(SQLModel, table=True):
    __tablename__ = "memory_supersessions"
    __table_args__ = (
        Index("ix_supersession_superseded", "superseded_id"),
        Index("ix_supersession_new", "new_id"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    superseded_id: str
    new_id: str
    user_id: str = Field(index=True)
    reason: str
    similarity_score: float | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
```

## Service layer

```
palace/
├── retrieval/
│   ├── __init__.py
│   ├── layered.py     # LayeredRetrievalService
│   └── ingestion.py   # SmartIngestionService (LLM extraction + dedup + supersede)
├── prompts/
│   └── ingestion.py   # SMART_INGEST_PROMPT
└── api/
    └── retrieval.py   # /v1/context/layered + /v1/memories/{id}/supersede(s) routes
```

`LayeredRetrievalService.assemble(user_id, query, ...) -> dict` — composes L1 + L2 + recent_messages.

`SmartIngestionService`:
- `extract_memories(messages, user_id, agent_id) -> list[dict]` — LLM call; returns extracted memory candidates.
- `dedup_and_write(candidates, user_id, agent_id, ...) -> tuple[list[Memory], list[dict], list[dict]]` — for each candidate: search nearest, decide skip/update/supersede/write.
- `_check_contradiction(old_content, new_content) -> tuple[bool, float, str]` — heuristic.

## Client + router

`PalaceClient` gains:
- `assemble_layered_context(...)` — returns structured dict
- `supersede_memory(memory_id, user_id, new_content, reason, metadata)` — returns supersession record
- `get_supersessions(memory_id) -> list`

`add(messages, user_id, infer=True, ...)` already exists; the response shape extends with `supersessions` and `skipped` in `meta`. The Pydantic model `Memory` doesn't change; the client returns the list as before but the caller can read `meta` from the raw response if needed (or we add a typed wrapper — going with raw access for slice 5).

`examples/mypalclara_router.py`:
- `MM.build_prompt_layered` graduates to remote when toggle is on. Returns the structured dict, NOT typed Messages — mypalclara's caller adapts. (Note: this is a non-trivial integration on the mypalclara side; the spec acknowledges that mypalclara's `prompt_builder.py:356` returns typed Messages and an adapter is needed there. Leave that as a follow-up exercise; the router branch returns the dict and the consumer composes.)
- `MM.build_prompt` (the simpler non-layered version) stays embedded — slice 5 doesn't replicate it.

## Test plan

- ~12 mock unit tests for layered service + smart ingestion logic (with mocked LLM + mocked dedup search).
- ~6 trigger tests for the contradiction heuristic.
- ~4 integration tests covering layered context end-to-end and smart ingestion with a stubbed LLM.

## Commit plan

5 commits:
1. `feat(models): MemorySupersession table`
2. `feat(retrieval): layered context service + endpoint`
3. `feat(ingestion): smart ingestion (activate infer=True) + supersede endpoints`
4. `feat(client): layered + supersede methods`
5. `test(integration) + docs(examples): live coverage + router updates + README slice-5 section + phase-2 wrap-up`

(Combining tests + docs into the final commit since slice 5 wraps phase 2.)
