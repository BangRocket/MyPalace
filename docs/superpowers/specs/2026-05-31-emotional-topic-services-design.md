# Design: Emotional Context + Topic Recurrence as first-class MyPalace services

- **Date:** 2026-05-31
- **Status:** Approved (design); pending implementation plan
- **Repos:** MyPalace (service + client, primary) · mypalclara (consumer wiring, follow-up)
- **Related:** `docs/gap-analysis-mypalclara.md`, `docs/migrating-mypalclara.md`

## Motivation

These are the last two memory capabilities from mypalclara that are **not represented in
MyPalace**. Today they are memory-backed helpers whose logic lives entirely in mypalclara:

- **Emotional context** (`mypalclara/core/memory/context/emotional.py`): VADER sentiment per
  message (in-memory) → on conversation finalize, compute an arc → store a summary as an ordinary
  Palace memory tagged `metadata.memory_type="emotional_context"`. Read back via
  `PALACE.get_all(...)` + client-side filter.
- **Topic recurrence** (`mypalclara/core/memory/context/topics.py`): LLM extracts ≤3 normalized
  topics → store each as a memory tagged `topic_mention` (+ sentiment/weight/channel) →
  `fetch_topic_recurrence` does `PALACE.get_all(limit=100)`, filters client-side, groups by topic,
  and computes recurrence patterns in Python.

Two problems: (1) the **logic** (VADER scoring, arc classification, LLM topic extraction,
recurrence aggregation) is not in Palace — it just holds opaque tagged rows; (2) retrieval relies
on `get_all(limit=100)` + client-side filtering, which does not scale and cannot filter by type or
time window server-side.

## Decisions

- **Depth: first-class services.** Build dedicated services with their own tables and
  aggregation endpoints, following the existing `episode_service`/`session_service`/`entity_service`/
  `personality_service` precedent (and the porting recipe in `gap-analysis-mypalclara.md`).
- **Extraction: server-side.** Palace runs VADER + LLM topic extraction + arc/recurrence
  aggregation. mypalclara sends raw conversation data. Topic extraction runs via the async worker
  queue (like `personality_evolve`/reflection); arc scoring is synchronous (VADER is cheap).
- **Consumer-facing, not admin.** Unlike `personality`/`entity` (admin-only `/v1/admin/*`, no client
  methods), these are called by mypalclara on every conversation finalize and prompt build, so they
  mount as first-class `/v1/*` routes **with** `PalaceClient` methods, alongside
  `episodes`/`intentions`/`context`.

## Architecture & data flow

```
Conversation finalizes (idle/end) in mypalclara
   ├─ POST /v1/emotional/record   → VADER over messages → arc → store  (sync)
   └─ POST /v1/topics/extract     → enqueue worker → LLM extract → store (async, 202 + job_id)

Prompt build in mypalclara
   ├─ GET /v1/users/{id}/emotional-context?limit=&max_age_days=        → recent rows
   └─ GET /v1/users/{id}/topic-recurrence?lookback_days=&min_mentions= → grouped + pattern-scored
```

## Component 1 — Data model (SQLModel + Alembic)

Two tables in `mypalace/models.py`, following the `PersonalityTrait`/`EntityAlias` style; both
tenant- and user-scoped. Two Alembic migrations in the `2026_05_05_00XX_*` series, chaining off the
current head `2026_05_05_0010_per_tenant_shadow_copy`.

**`EmotionalContext`**

| column | type | notes |
|---|---|---|
| `id` | str (uuid) | PK |
| `tenant_id` | str | `DEFAULT_TENANT_ID` |
| `user_id` | str | |
| `agent_id` | str | default `"default"` |
| `channel_id` | str | opaque (platform-agnostic) |
| `channel_name` | str | |
| `is_dm` | bool | |
| `starting_sentiment` | float | first-message VADER compound |
| `ending_sentiment` | float | last-message VADER compound |
| `emotional_arc` | str | `stable` / `improving` / `declining` / `volatile` |
| `energy_level` | str | caller-supplied (from mypalclara ORS extraction) |
| `topic_summary` | str | caller-supplied |
| `created_at` | datetime | |

Index: `(tenant_id, user_id, created_at)`.

**`TopicMention`**

| column | type | notes |
|---|---|---|
| `id` | str (uuid) | PK |
| `tenant_id` | str | |
| `user_id` | str | |
| `agent_id` | str | |
| `topic` | str | normalized, lowercase, singular |
| `topic_type` | str | `entity` / `theme` |
| `context_snippet` | str | ≤100 chars |
| `emotional_weight` | str | `light` / `moderate` / `heavy` |
| `sentiment` | float | conversation compound at mention time |
| `channel_id` | str | |
| `channel_name` | str | |
| `is_dm` | bool | |
| `created_at` | datetime | |

Index: `(tenant_id, user_id, topic, created_at)`.

This replaces overloading the generic memory table with `metadata.memory_type` tags — a real schema
the server filters/aggregates by type + time window.

## Component 2 — Services

**`mypalace/emotional_service.py` → `EmotionalService`** (module singleton `emotional_service`)

- `record(user_id, agent_id, messages: list[str], channel_id, channel_name, is_dm, energy, summary,
  tenant_id) -> EmotionalContext` — runs VADER server-side over the message timeline, ports
  `compute_emotional_arc` (needs ≥3 messages; `variance > 0.3` → `volatile`; `end_avg - start_avg >
  0.2` → `improving`; `start_avg - end_avg > 0.2` → `declining`; else `stable`), stores a row.
  **Sync.** Adds the `vaderSentiment` dependency to MyPalace (mirror
  `mypalclara/core/sentiment.py`: lazy `SentimentIntensityAnalyzer`, compound score).
- `get_recent(user_id, agent_id, limit, max_age_days, tenant_id) -> list[EmotionalContext]` —
  server-side time-windowed query, newest first.

**`mypalace/topic_service.py` → `TopicService`** (module singleton `topic_service`)

- `extract_and_store(user_id, agent_id, conversation_text, conversation_sentiment, channel_id,
  channel_name, is_dm, tenant_id) -> list[TopicMention]` — ports `TOPIC_EXTRACTION_PROMPT` using
  `mypalace.llm` (`await llm.complete([...], temperature=0.0)`), validates/normalizes, dedupes to
  ≤3 by heaviest weight, stores rows. Reuses a `_parse_llm_json` helper like
  `personality_service`. **Runs via the worker queue** (`kind="topic_extract"`).
- `get_recurrence(user_id, agent_id, lookback_days, min_mentions, tenant_id) -> list[dict]` — queries
  the window, groups by topic, ports `compute_topic_pattern` (`mention_count`, `sentiment_trend`,
  `avg_emotional_weight`, `pattern_note`), filters to `>= min_mentions`, returns recurring topics
  sorted by `mention_count` desc, with relative-time first/last and channel list.

**Trigger helper** `enqueue_topic_extract(...)` mirroring `maybe_enqueue_evolution` (fire-and-forget
`asyncio.create_task` → `workers.queue.enqueue`). Register a `topic_extract` handler in
`mypalace/workers/handlers.py`.

## Component 3 — HTTP API + client

API modules `mypalace/api/emotional.py` and `mypalace/api/topics.py`, registered in `mypalace/main.py`
using the `ApiResponse`/`Meta`/`AuthContext`/`resolve_tenant` conventions from `api/personality.py`:

- `POST /v1/emotional/record` → 200 `EmotionalContextOut`
- `GET /v1/users/{user_id}/emotional-context?limit=&max_age_days=` → `list[EmotionalContextOut]`
- `POST /v1/topics/extract` → 202 `{job_id}` (enqueues worker; mirrors reflection async)
- `GET /v1/users/{user_id}/topic-recurrence?lookback_days=&min_mentions=` → `list[TopicRecurrenceOut]`

`mypalace_client` (`client.py` + `models.py`): add **`PalaceClient`** methods
`record_emotional_context(...)`, `get_emotional_context(...)`, `extract_topics(...)` (returns
job/pending), `get_topic_recurrence(...)`, plus `EmotionalContext` / `TopicRecurrence` Pydantic
models. Bump the `mypalace-client` version.

## Component 4 — mypalclara wiring (follow-up PR)

- **Bump the `mypalace-client` pin** from `^0.7.1` to the new version — prerequisite; re-locks the
  whole remote surface.
- `context/emotional.py` + `context/topics.py`: add a `USE_PALACE_SERVICE` branch. Remote → call the
  new client methods via the async bridge; embedded → unchanged (preserves reversibility). On the
  remote path, finalize sends the conversation messages (Palace scores them), so per-message local
  VADER becomes embedded-only.
- `prompt_builder.fetch_emotional_context` / `fetch_topic_recurrence`: route to the client when
  remote, else embedded — mirroring how episodes already branch in `build_prompt_layered`.

## Error handling

Graceful degradation matching the originals: VADER/LLM failure → log + empty/false; topic worker
failure → job marked `failed`, never blocks ingestion; record endpoints validate via Pydantic.
mypalclara fetch paths keep their existing `try/except → []` so prompt building never crashes.

## Testing (TDD)

- MyPalace: unit tests for arc thresholds, topic dedup/pattern math, and VADER timeline scoring;
  service tests against the test DB; API tests via httpx; a `topic_extract` worker-handler test.
- mypalclara: routed path calls the client (PalaceClient mocked); embedded path unchanged.

## Scope boundaries

1. **gRPC parity: deferred** to a follow-up slice (HTTP + client first).
2. **Backfill** of existing `emotional_context`/`topic_mention` memories into the new tables:
   **deferred** (optional one-off script later) — new data flows correctly from day one.
3. **Repo/PR split:** bulk lands in MyPalace (`feat/emotional-topic-services` branch + PR); a
   follow-up mypalclara PR does the client bump + wiring on `feat/palace-service-migration`.
4. **Per-message live sentiment streaming to the server: out** — score at finalize from the message
   list.

## Out of scope

mypalclara's ORS extraction (energy/summary inputs are passed through and stored, not computed in
Palace); channel/platform semantics (stored as opaque fields).
