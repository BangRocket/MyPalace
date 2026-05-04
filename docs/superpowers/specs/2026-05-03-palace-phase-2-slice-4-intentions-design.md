# Palace Phase 2 Slice 4 — Intentions

**Branch:** `phase-2-slice-4-intentions`

## Background

Slice 4 ports mypalclara's intentions subsystem: deterministic-trigger reminders that fire when matching keywords, topics, times, or context conditions are detected in conversation. **No LLM** — purely structural matching. Smaller and simpler than slice 2.

## Surface area (verified at `/Volumes/Storage/Code/mypalclara`)

- `Intention` model: `db/models.py:491-545` — id, user_id, agent_id, content, source_memory_id, trigger_conditions (JSON text), priority, fired, fire_once, created_at, expires_at, fired_at. Indexes: `(user_id, fired)` and `(expires_at,)`.
- `IntentionManager`: `core/memory/intentions.py` — facade over module-level functions in `core/intentions.py`.
- `set_intention(user_id, content, trigger_conditions, expires_at, source_memory_id) -> str`
- `check_intentions(user_id, message, context) -> list[dict]` — loads unfired+unexpired intentions, evaluates each per `trigger_conditions["type"]` (keyword/topic/time/context), marks fired, deletes if `fire_once`, returns matches sorted by priority.
- `format_intentions_for_prompt(fired_intentions) -> str` — markdown bullet list for system prompt injection.
- `cleanup_expired_intentions() -> int` — bulk delete past expires_at.
- Trigger schemas (4 types):
  - `keyword`: `{"type":"keyword","keywords":[...],"regex":?,"case_sensitive":?}`
  - `topic`: `{"type":"topic","topic":str,"threshold":float,"quick_keywords":[...]}` — fallback word-overlap; no LLM
  - `time`: `{"type":"time","at":ISO|null,"after":ISO|null}`
  - `context`: `{"type":"context","conditions":{"channel_name":?,"is_dm":?,"time_of_day":?,"day_of_week":?}}`

External callers: `gateway/processor.py:626` (check), `:697` (format_for_prompt), and `MM.set_intention` (internal).

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| **D1** | Port `core/intentions.py` matching logic character-for-character into `palace/intentions/triggers.py`. Pure functions; trivial port. | Same risk-of-drift argument as slice-3 FSRS port. |
| **D2** | `trigger_conditions` stored as JSONB (not Text-encoded JSON). Cleaner queries; no double-decode. mypalclara uses Text only because they predate JSONB use in their schema. | Matches slice 1's JSONB philosophy. |
| **D3** | `format_intentions_for_prompt` is a server-side endpoint AND a client-side helper. Endpoint variant is `POST /v1/intentions/format` with `{intentions: [...]}` body. Caller can compose locally too. | Symmetry with mypalclara's MM facade. |
| **D4** | No LLM. All endpoints sync, no jobs. | Same as deterministic matching in mypalclara. |
| **D5** | `cleanup_expired_intentions` is `POST /v1/maintenance/cleanup-intentions`. Admin op; no auto-prune. | Matches mypalclara's manual-trigger pattern. |
| **D6** | `check_intentions` accepts `context` as an optional dict. The endpoint validates loosely — pass-through to the matcher which enforces shape. | Matches mypalclara's flexible context shape. |

## Wire contract

### `POST /v1/intentions`
```json
{ "user_id": "u1", "content": "Remind me about the meeting", "trigger_conditions": {"type": "keyword", "keywords": ["meeting"]}, "agent_id": "clara", "expires_at": null, "source_memory_id": null, "priority": 0, "fire_once": true }
→ 200 { "data": IntentionOut, "meta": {...} }
```

### `POST /v1/intentions/check`
```json
{ "user_id": "u1", "message": "When is the meeting?", "context": {"channel_name": "general", "is_dm": false} }
→ 200 { "data": [FiredIntentionOut, ...], "meta": {"count": N, "took_ms": N} }
```

`FiredIntentionOut` = `{id, content, trigger_type, priority, match_details, source_memory_id}` mirroring mypalclara.

### `POST /v1/intentions/format`
```json
{ "intentions": [FiredIntentionOut, ...], "max": 3 }
→ 200 { "data": { "text": "## Reminders\n- ..." }, "meta": {...} }
```

### `GET /v1/users/{user_id}/intentions?fired={true|false|all}&limit=50`
→ list intentions for user, filtered by fired status.

### `DELETE /v1/intentions/{intention_id}`
→ 200 `{deleted: true}` or 404.

### `POST /v1/maintenance/cleanup-intentions`
→ 200 `{deleted: N}`.

## Data model

```python
class Intention(SQLModel, table=True):
    __tablename__ = "intentions"
    __table_args__ = (
        Index("ix_intention_user_unfired", "user_id", "fired"),
        Index("ix_intention_expires", "expires_at"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    agent_id: str = Field(default="clara")
    content: str
    source_memory_id: str | None = None
    trigger_conditions: dict = Field(sa_column=Column(JSONB, nullable=False))
    priority: int = Field(default=0)
    fired: bool = Field(default=False)
    fire_once: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    expires_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    fired_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
```

## Service layer

```
palace/
├── intentions/
│   ├── __init__.py
│   ├── triggers.py     # ported deterministic matchers (4 types)
│   └── service.py      # IntentionService (DB wrapper)
└── api/
    └── intentions.py   # 5 routes
```

`IntentionService`:
- `set(user_id, content, trigger_conditions, **opts) -> Intention`
- `check(user_id, message, context=None) -> list[dict]`
- `format_for_prompt(fired: list[dict], max=3) -> str`
- `list_for_user(user_id, fired_filter="all", limit=50) -> list[Intention]`
- `delete(intention_id) -> bool`
- `cleanup_expired() -> int`

## Client + router

`PalaceClient` gains 6 methods mirroring the endpoints. Wire types: `Intention`, `FiredIntention`.

`examples/mypalclara_router.py`: graduate `MM.set_intention`, `MM.check_intentions`, `MM.format_intentions_for_prompt` to `if USE_PALACE_SERVICE` branches.

## Test plan

- ~10 mock unit tests (trigger matching for each of 4 types + endpoint wiring).
- ~3 integration tests (set → check → expire cycle, cleanup, list with filter).
- Trigger matchers tested deterministically — no LLM, no flakiness.

## Commit plan

1. `feat(models): Intention table`
2. `feat(intentions): trigger matchers + service + 5 endpoints`
3. `feat(client): intention methods + wire types`
4. `test(integration): live intention coverage`
5. `docs(examples): router updates + README slice-4 section`
