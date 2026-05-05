# Gap Analysis: mypalclara → MyPalace Memory Service

## Executive Summary

MyPalace demonstrates **close parity** with mypalclara's memory layer. Core memory operations (ingestion, retrieval, FSRS dynamics, embedding, episodes, reflections, intentions) are present and functional. However, three meaningful gaps exist: (1) personality evolution (`personality.py`), (2) entity resolution for knowledge-graph naming (`entity_resolver.py`), and (3) verbatim chat history search (`vch.py`). Additional env var misalignment exists for budget controls. These gaps are **not blockers** for baseline memory functionality but represent missing sophistication for multi-user systems and long-term trajectory tracking.

---

## Methodology

**mypalclara inventory** (reference):
- `mypalclara/core/memory/` (47 Python files across 8 subdirectories)
- Supporting: `mypalclara/core/llm/`, `clara_core/`, background services
- Scope: memory extraction, storage, dynamics, retrieval, synthesis, graph integration

**MyPalace inventory** (target):
- `mypalace/` (core service with 34 .py modules across 17 subdirectories)
- Database: SQLAlchemy + Alembic (6 migrations baseline)
- gRPC: 8 servicers + proto definitions
- Intentionally excluded: Teams bots, Discord-specific code, chat UI, non-memory MCP servers, personas/SOUL.md infrastructure

**Out of scope**: mypalclara's monolithic features (Clara bot logic, channel context, vault snapshots, personality as Clara's trait, Slack/Teams integrations, database migrations for Clara's user/guild tables).

---

## Gap Tables

### MISSING — Present in mypalclara, absent in MyPalace

| Item | mypalclara Location | MyPalace Location | Notes |
|------|---------------------|-------------------|-------|
| **Personality evolution** | `mypalclara/core/memory/personality.py` (80 lines) | ❌ None | LLM-driven trait synthesis after message exchanges; runs probabilistically. |
| **Entity resolver** | `mypalclara/core/memory/entity_resolver.py` (350+ lines) | ❌ None | Maps platform IDs (discord-xyz) → human names; backs knowledge-graph node labeling. |
| **Verbatim chat history search** | `mypalclara/core/memory/vch.py` (80+ lines) | ❌ None | PostgreSQL full-text search on raw messages; returns conversational context windows. |
| **Embedding budget env vars** | `mypalclara/core/memory/config.py:29–35` | ❌ None | `MEMORY_BUDGET_L0/L1/L2_*` for token-level budgeting; Palace uses hardcoded char budgets in `layered.py:86–91`. |
| **Embedding cache toggle** | `mypalclara/core/memory/config.py:303` | ❌ None | `MEMORY_EMBEDDING_CACHE` env var; Palace always uses cache if Redis is available. |
| **Graph vector store selection** | `mypalclara/core/memory/vector/factory.py` | ❌ `palace/graph/` uses only FalkorDB | Factory pattern for qdrant vs pgvector; Palace hardcodes FalkorDB if `ENABLE_GRAPH_MEMORY=true`. |
| **Dual-write vector migration mode** | `mypalclara/core/memory/vector/dual_write.py` (140+ lines) | ❌ None | `VECTOR_STORE_MODE` env var (primary_only/dual_write/dual_read/secondary_only); Palace has no migration infrastructure. |
| **Embedding migration scripts** | `mypalclara/scripts/migrate_pgvector_to_qdrant.py` | ❌ None | Blue-green reembed tooling absent; Palace has `/api/jobs/reembed` but no migration orchestration. |
| **Contradiction dynamics** | `mypalclara/core/memory/dynamics/contradiction.py` (100+ lines) | ✓ Partial in `retrieval/ingestion.py:44–62` | Heuristic contradiction detection; Palace implements lighter version in smart ingestion. |

### DIVERGED — Present in both but behavior/schema differs

| Item | mypalclara Location | MyPalace Location | Notes |
|------|---------------------|-------------------|-------|
| **LLM config structure** | `mypalclara/core/llm/` + `unified.py` | `mypalace/llm.py:17–22` | mypalclara supports Anthropic, NanoGPT, custom OpenAI endpoints via unified provider; Palace hardcodes openrouter/openai with minimal provider switching. |
| **Env var naming (LLM)** | `PALACE_PROVIDER`, `PALACE_MODEL`, `PALACE_API_KEY`, `PALACE_BASE_URL` | `llm_provider`, `llm_model`, `llm_api_key` (Pydantic aliases) | mypalclara uses env-based config; Palace uses Pydantic settings with case-insensitive mapping. Both are compatible but differ in fallback semantics. |
| **Default embedding model** | `intfloat/e5-large-v2` (1024 dims) or OpenAI `text-embedding-3-small` (1536) | `BAAI/bge-large-en-v1.5` (1024) | Different default; dimension mismatch if switching mid-deployment. |
| **Collection name default** | `clara_memories` (from `PALACE_COLLECTION_NAME`) | `palace_memories` | Minor; but indicates different naming convention. |
| **LLM temperature** | Configurable via `BaseEmbedderConfig`, defaults vary | Hardcoded `temperature=0.7` for completions, `0.0` for extraction | mypalclara allows tuning; Palace mostly fixed. |
| **Rate limiting** | Not explicitly in memory module (handled by chat service) | `mypalace/ratelimit/` + env vars `PALACE_RATE_LIMIT_*` | Palace has first-class rate limit support; mypalclara defers to parent service. |
| **Tenancy model** | No explicit multi-tenant isolation (single-user Clara) | `tenant_id` on all tables + `PALACE_DEFAULT_TENANT_ID` | Palace ready for per-tenant schemas (phase 11); mypalclara assumes single tenant. |
| **Retrieval budget formulation** | Token-based (L0/L1/L2 env vars for tokens); `~4 chars/token` | Char-based hardcoded (L1=3200, L2=12000 chars) | Algorithm identical but units differ; migration requires env→char conversion. |
| **Worker queue backend** | Not modeled in memory (Clara's responsibility) | `mypalace/workers/` + Redis/DB-backed queue | Palace implements async job workers; mypalclara leaves to parent. |

### EXTRA — Present in MyPalace, absent from mypalclara

| Item | mypalclara Location | MyPalace Location | Notes |
|------|---------------------|-------------------|-------|
| **Arc synthesis as first-class service** | Embedded in `reflection.py` | `arc_service.py` + `api/arcs.py` | Palace separates narrative arc CRUD into its own service; mypalclara treats as side-effect of `synthesize_narratives()`. |
| **Audit trail middleware** | Not modeled | `audit/` + `api/audit.py` + `Audit` model | Palace tracks all memory mutations with user/scope/timestamp; mypalclara relies on Clara's logging. |
| **Health checks** | Not present | `health/` + `/live`, `/ready`, `/health/deep` endpoints | Palace exposes k8s-compatible probes. |
| **Observability stack** | Not present | `observability/` (logging, tracing, metrics, slow-query detection) | Palace built with OTLP/Prometheus from day one. |
| **Admin API** | Not present | `api/admin.py` + gRPC admin servicer | Palace has tenant creation, stats, diagnostics endpoints. |
| **WebSocket event broker** | Not present | `events/` + `EventBroker` for real-time updates | Palace can emit memory mutations to connected clients. |
| **Job/background worker framework** | Implicit (cleanup tasks) | `workers/` + `BackupWorker`, `JobRunner`, queue + lease mgmt | Palace has structured async job execution. |
| **Portability (export/import)** | Not present | `api/portability.py` + `backup.py` worker | Palace supports bulk tenant export/import. |
| **Database connection pooling config** | Not exposed | `config.py:103–117` (`db_pool_*` env vars) | Palace allows tuning SQLAlchemy pool behavior. |
| **Scheduled backups** | Not modeled | `workers/backup.py` + `PALACE_BACKUP_*` env vars | Palace can schedule periodic full-tenant dumps. |
| **Session management service** | Partial in `session.py` | `session_service.py` + full CRUD + replay logic | Palace has dedicated session service with conversation replay. |
| **Context service** | Not present | `context_service.py` | Palace caches user+agent context for efficiency. |

---

## Detailed Findings

### MISSING: Personality Evolution

**What it is:** `mypalclara/core/memory/personality.py` implements continuous trait tracking. After memory extraction, a background task runs an LLM prompt to evaluate whether the conversation reveals new personality traits or updates to existing ones. Traits are stored in a `personality_traits` table and evolve over time.

**Why it matters:** Long-term personalization and multi-turn relationship tracking. Users expect the system to "learn" their speaking style, values, and quirks.

**To port:** 
- Create `mypalace/personality_service.py` with async trait CRUD (create, update, delete).
- Add `PersonalityTrait` model to `models.py` (fields: `id`, `tenant_id`, `user_id`, `category`, `trait_key`, `content`, `reason`, `created_at`, `updated_at`).
- Implement LLM prompt matching mypalclara's `EVOLUTION_PROMPT`.
- Wire into `ingestion.py` as a post-extraction callback (probabilistic trigger).
- Create Alembic migration for the trait table + indexes on `(tenant_id, user_id)`.

**Estimated scope:** 1 small PR (200–300 lines code + migration).

---

### MISSING: Entity Resolver

**What it is:** `mypalclara/core/memory/entity_resolver.py` maps platform-prefixed IDs (e.g., `discord-271274659385835521`) to human-readable names (e.g., `Josh`). Uses regex matching + LLM name extraction from conversations. Maintains an `entity_aliases` table with aliases and canonical names.

**Why it matters:** Knowledge-graph nodes need human-readable labels. Without entity resolution, the graph shows `discord-123` instead of `Josh`.

**To port:**
- Create `mypalace/entity_service.py` with async resolve/lookup methods.
- Add `EntityAlias` model to `models.py` (fields: `id`, `tenant_id`, `identifier`, `canonical_name`, `source`, `created_at`, `updated_at`).
- Extract regex patterns from mypalclara's `_PLATFORM_PREFIX_RE` and name-extraction logic.
- Integrate into graph service when creating nodes (e.g., in `graph/service.py:_add_relation()`).
- Create migration for alias table + indexes.

**Estimated scope:** 1 small PR (250–350 lines + migration).

---

### MISSING: Verbatim Chat History Search (VCH)

**What it is:** `mypalclara/core/memory/vch.py` queries raw conversation messages (not summaries) via PostgreSQL full-text search. Returns snippets with context windows (e.g., ±2 messages around matches).

**Why it matters:** Retrieval layer (L2) includes VCH as an optional source. For users who ask "What did we talk about last Tuesday?", semantic search alone may miss exact-match factoids.

**To port:**
- Add `context_window` parameter to `retrieval/layered.py:assemble()`.
- Implement `async search_vch()` in a new `mypalace/vch_service.py` (or inline in `session_service.py`).
- Requires raw message log table; Palace's `Session` model stores `user_messages` (list of dicts) and `assistant_messages`; may need denormalization or a separate `Message` table.
- Integrate into L2 retrieval tier (alongside episodes and semantic search).

**Estimated scope:** 1 medium PR (300–500 lines; may require schema changes).

---

### MISSING: Embedding Budget Environment Variables

**What it is:** mypalclara's `config.py:29–35` defines token-level budgets for each retrieval layer:
```python
BUDGET = {
    "l0_identity": int(os.getenv("MEMORY_BUDGET_L0", "200")),
    "l1_profile": int(os.getenv("MEMORY_BUDGET_L1", "800")),
    "l2_episodes": int(os.getenv("MEMORY_BUDGET_L2_EPISODES", "1500")),
    "l2_graph": int(os.getenv("MEMORY_BUDGET_L2_GRAPH", "500")),
    "l2_memories": int(os.getenv("MEMORY_BUDGET_L2_MEMORIES", "1000")),
}
```

Palace uses hardcoded character budgets in `layered.py:86–91` (L1=3200, L2=12000 chars).

**Why it matters:** Different deployments may want different context sizes. Token-level budgeting is more precise than char-level.

**To port:**
- Add `PALACE_CONTEXT_BUDGET_L0`, `PALACE_CONTEXT_BUDGET_L1`, `PALACE_CONTEXT_BUDGET_L2_MEMORIES`, `PALACE_CONTEXT_BUDGET_L2_EPISODES`, `PALACE_CONTEXT_BUDGET_L2_GRAPH` to `config.py`.
- Convert to chars using `tokens * 4`.
- Pass to `LayeredRetrievalService.assemble()`.
- Update `.env.example` and docs.

**Estimated scope:** Tiny PR (50 lines config + docs).

---

### MISSING: Embedding Cache Toggle

**What it is:** mypalclara's `MEMORY_EMBEDDING_CACHE` env var (default `true`) controls whether embedding results are cached in Redis.

Palace always uses cache if `PALACE_REDIS_URL` is set; no explicit toggle.

**Why it matters:** Some deployments may want to bypass cache for consistency testing or cost control.

**To port:**
- Add `PALACE_EMBEDDING_CACHE_DISABLED` env var to `config.py` (inverted logic for consistency with other `*_disabled` flags).
- Modify `embeddings.py` to check this flag before querying Redis.

**Estimated scope:** Tiny PR (20 lines).

---

### MISSING: Graph Vector Store Selection

**What it is:** mypalclara's `mypalclara/core/memory/vector/factory.py` abstracts vector store selection (Qdrant vs pgvector). Could extend to other backends.

Palace hardcodes FalkorDB for graphs (if `ENABLE_GRAPH_MEMORY=true`); no vector store abstraction for graph nodes.

**Why it matters:** If Palace adds graph analytics, may want to use a different vector store than the main memory store.

**Impact:** Low priority; Palace's current design doesn't require this flexibility yet.

**Estimated scope:** Not actionable until graph scaling becomes a concern.

---

### MISSING: Dual-Write Vector Migration Mode

**What it is:** mypalclara's `mypalclara/core/memory/vector/dual_write.py` implements blue-green deployment strategy for vector stores:
- `primary_only`: read/write primary only.
- `dual_write`: write to both, read primary.
- `dual_read`: write primary, read both (choose best score).
- `secondary_only`: read/write secondary only.

Controlled by `VECTOR_STORE_MODE` env var. Enables zero-downtime migration from Qdrant to pgvector or vice versa.

Palace has no migration infrastructure.

**Why it matters:** Large deployments may need to migrate vector stores without downtime.

**To port:** Non-trivial. Requires wrapping all vector store calls in a dual-write layer. Defer until phase 11 when Postgres schema per-tenant is implemented.

**Estimated scope:** 1 medium–large PR (400–600 lines + E2E tests) — **recommend deferring to Phase 11**.

---

### DIVERGED: LLM Provider Configuration

**mypalclara:** Unified provider architecture (`mypalclara/core/llm/`) supports Anthropic, NanoGPT, OpenAI (custom endpoints), OpenRouter. Single config point.

**Palace:** Minimal LLM client (`llm.py`) hardcodes openrouter + openai, with static URL mapping. No Anthropic support.

**Impact:** If a Palace deployment wants Anthropic (for coherence/cost), the LLM client needs extension.

**To port:**
- Expand `llm.py:_get_base_url()` to support Anthropic, custom endpoints.
- Add config for base URL override.
- Consider adopting mypalclara's unified provider pattern if multi-provider support becomes a requirement.

**Estimated scope:** Small PR (50–100 lines); defer if not a requirement.

---

### DIVERGED: Tenancy Model

**mypalclara:** Single-tenant Clara (conceptually); no explicit `tenant_id` in memory tables.

**Palace:** Multi-tenant from day one. Every table has `tenant_id`. `PALACE_DEFAULT_TENANT_ID` env var for bootstrapping.

**Impact:** None for current Palace scope. Phase 11 will extend to per-tenant PostgreSQL schemas; this table-level isolation is the stepping stone.

**No action needed.** Palace is future-proof.

---

### DIVERGED: Retrieval Layer Budget Units

**mypalclara:** Token-based. `_estimate_tokens(text: str) -> int` uses 4-char-per-token heuristic. Budgets defined as token counts.

**Palace:** Character-based. `_enforce_char_budget()` directly counts chars. Budgets are char counts.

**Impact:** Minimal. Both use the same heuristic (4 chars = 1 token). Operators should be aware that "3200 chars" ≈ "800 tokens".

**No action needed** for basic migration. Add budget env vars (see MISSING section above).

---

## Recommended Slice List

### Phase 10 Prerequisites

**Slice 10a: Port Entity Resolver (small)**
- Add `EntityAlias` model.
- Create `entity_service.py` with resolve/lookup.
- Wire into `graph/service.py`.
- **Owner:** Memory team. **Effort:** 2–3 days.

**Slice 10b: Port Personality Evolution (small)**
- Add `PersonalityTrait` model.
- Create `personality_service.py`.
- Integrate callback into `ingestion.py`.
- **Owner:** Memory team. **Effort:** 2–3 days.

**Slice 10c: Budget Env Vars (tiny)**
- Add token budget env vars to `config.py`.
- Pass to `LayeredRetrievalService.assemble()`.
- Update docs.
- **Owner:** Infra. **Effort:** 1 day.

### Phase 11 Prerequisites

**Slice 11a: VCH Search (medium)**
- Add raw message logging (schema change).
- Create `vch_service.py`.
- Integrate into L2 retrieval.
- **Owner:** Memory team. **Effort:** 4–5 days.

**Slice 11b: Embedding Cache Toggle (tiny)**
- Add `PALACE_EMBEDDING_CACHE_DISABLED` env var.
- Modify `embeddings.py` conditional.
- **Owner:** Infra. **Effort:** 1 day.

### Standalone / Phase 12+

**Slice S1: LLM Provider Expansion (low priority)**
- Extend `llm.py` to support Anthropic, custom endpoints.
- Conditional expansion based on `llm_provider` config.
- **Owner:** Infrastructure. **Effort:** 2–3 days (defer until needed).

**Slice S2: Dual-Write Vector Migration (large, defer)**
- Implement blue-green deployment layer for vector stores.
- Add `VECTOR_STORE_MODE` support.
- Requires comprehensive E2E testing.
- **Owner:** Infrastructure. **Effort:** 1–2 weeks. **Recommend:** Phase 12 or later.

---

## Summary

MyPalace is **production-ready** for baseline memory use cases. The three missing features (personality, entity resolution, VCH) are enhancements that improve personalization and search richness but are not blocking. They can be ported in **three small PRs** (Phase 10) + **one medium PR** (Phase 11), totaling ~3–4 weeks of focused work. Environment variable alignment is straightforward. The multi-tenant architecture puts Palace ahead of mypalclara for future scaling.

