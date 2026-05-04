# Palace Phase 3 — Slice 1: Auth (API Keys + Scopes)

**Date:** 2026-05-04
**Branch:** `phase-3-slice-1-auth` (off `phase-3`)
**Depends on:** none — first slice
**Master plan:** `docs/superpowers/specs/2026-05-04-palace-phase-3-master.md`

## Goal

Lock down every Palace endpoint behind an API key. Per-key scopes (`read`, `write`, `admin`). First-run bootstrap mints an admin key from env var. Tests bypass via `PALACE_AUTH_DISABLED=true`.

After this slice: every existing endpoint requires `X-Palace-Key`; admin operations require `admin` scope; unauthenticated requests get 401; insufficient-scope requests get 403.

## Non-goals

- JWT, OAuth, mTLS, session cookies
- Per-user identity (still passed in body as `user_id`)
- Per-key rate limits
- Per-key tenant binding (slice 2)

---

## Surface

### New table

`api_keys`:
| col | type | notes |
|---|---|---|
| id | uuid PK | internal id |
| key_prefix | varchar(8) indexed unique | first 8 chars of the secret, used for lookup |
| key_hash | varchar(60) | bcrypt hash of full secret |
| label | varchar(100) | human label, e.g. "mypalclara-prod" |
| scopes | JSONB | list[str] from {"read","write","admin"} |
| created_at | timestamptz | |
| last_used_at | timestamptz nullable | bumped at most once per minute |
| revoked_at | timestamptz nullable | non-null = revoked |

### Key format

`pk_<env>_<32-char-base62>` — e.g. `pk_live_a1b2c3d4e5f6...`. The `pk_live_` prefix is fixed (no per-env switching in phase 3, but the format leaves room). The `key_prefix` index column stores the first 8 chars *of the random portion* (not the literal `pk_live_`). So lookup is: parse → take chars 8..16 → SELECT by key_prefix → bcrypt-verify against key_hash.

### Middleware

`palace/auth/middleware.py` — FastAPI middleware that:
1. If `PALACE_AUTH_DISABLED=true`, attach `request.state.auth = AuthContext(scopes={"read","write","admin"}, key_id="disabled")` and pass through.
2. If path is in `PUBLIC_PATHS` (`/health`, `/docs`, `/openapi.json`, `/redoc`), pass through.
3. Read `X-Palace-Key` header. Missing → 401 `{"error":{"code":"unauthenticated","message":"missing X-Palace-Key"}}`.
4. Parse + lookup. Not found / bcrypt mismatch / revoked → 401.
5. Resolve required scope by route (see scope mapping). Insufficient → 403.
6. Update `last_used_at` (debounced — only if last update >60s ago; in-memory cache).
7. Attach `request.state.auth = AuthContext(...)`.

### Scope mapping

A decorator-free table-based approach. `palace/auth/scopes.py` defines:

```python
SCOPE_RULES: list[tuple[str, str, set[str]]] = [
    # (method_pattern, path_pattern, required_scopes)
    ("*", "/v1/admin/*",       {"admin"}),
    ("*", "/v1/maintenance/*", {"admin"}),
    ("GET", "/v1/*",            {"read"}),
    ("POST", "/v1/memories/search", {"read"}),
    ("POST", "/v1/memories/list",   {"read"}),
    ("POST", "/v1/context/*",       {"read"}),
    ("*", "/v1/*",                  {"write"}),  # default
]
```

First match wins. `*` matches one path segment. Default if nothing matches: `{"write"}` (defensive — admins must explicitly add new public routes if needed).

### Endpoints (admin-only)

- `POST /v1/admin/keys` body `{label: str, scopes: list[str]}` → `{key_id, plaintext_key, label, scopes}`. **Plaintext returned exactly once.**
- `GET /v1/admin/keys` → list all keys (no plaintext, no hash). Filter `?include_revoked=false` default.
- `DELETE /v1/admin/keys/{key_id}` → soft-revoke (sets `revoked_at = now()`).

### Bootstrap

In `lifespan` startup, after `init_db`:
- If env `PALACE_BOOTSTRAP_ADMIN_KEY` is set AND no rows exist in `api_keys` with `admin` scope AND no `revoked_at`:
  - Insert a row with `key_prefix` and `key_hash` derived from the env value.
  - Label `"bootstrap-admin"`.
  - Log INFO `"bootstrap admin key registered (label=bootstrap-admin, prefix=...)"`.
- If env is unset and no admin keys exist, log WARN `"no admin keys configured; /v1/admin/* will be inaccessible. Set PALACE_BOOTSTRAP_ADMIN_KEY."`.

### Test bypass

`PALACE_AUTH_DISABLED=true` skips middleware entirely and synthesizes a context with all three scopes. The test `client` fixture sets this env var.

---

## Internal contracts

### `AuthContext`

```python
@dataclass(frozen=True)
class AuthContext:
    key_id: str
    label: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool: ...
    def require(self, scope: str) -> None:  # raises HTTPException(403)
```

Available in handlers via `request.state.auth` or new dependency `get_auth: Annotated[AuthContext, Depends(get_auth_context)]`.

### `KeyService`

`palace/auth/key_service.py`:

- `async create_key(label, scopes) -> tuple[ApiKey, str]` — returns row + plaintext
- `async lookup(plaintext) -> AuthContext | None` — used by middleware
- `async list_keys(include_revoked=False) -> list[ApiKey]`
- `async revoke(key_id) -> bool`
- `async bootstrap_if_needed(plaintext_env_value) -> bool` — idempotent

Singleton `key_service` exported.

### `last_used_at` debounce

`palace/auth/usage.py`:

```python
class UsageTracker:
    def __init__(self, debounce_seconds: float = 60.0): ...
    def should_update(self, key_id: str) -> bool: ...
```

In-memory dict `key_id -> last_update_ts`. Process-local — fine for single-worker; with multi-worker, worst case is N updates per minute instead of 1. Acceptable.

---

## Decisions

| ID | Decision | Why |
|---|---|---|
| D1.1 | Header is `X-Palace-Key` | Obviously not OAuth; no Bearer parsing |
| D1.2 | bcrypt hash + 8-char prefix index | Constant-time compare on hash; fast lookup |
| D1.3 | `PALACE_AUTH_DISABLED=true` test bypass | Avoids wiring keys into every test |
| D1.4 | Public paths hardcoded | `/health` for k8s probes; `/docs` etc. for dev — hide via `?docs_disabled=1` ENV later |
| D1.5 | Route→scope is table-based | Decorators on every handler is sprawl |
| D1.6 | Bootstrap via env, log on absence | Container-friendly; first-boot story |
| D1.7 | Soft-revoke (not delete) | Audit history matters |
| D1.8 | last_used_at debounced 60s | Hot path performance |
| D1.9 | Key prefix `pk_live_` literal | Reserves room for `pk_test_` later w/o breakage |
| D1.10 | Scope hierarchy: admin>write>read | But stored as explicit set; admin doesn't auto-include lower (caller must request all). Forces intentional issuance. |

---

## Files to create

- `palace/auth/__init__.py`
- `palace/auth/middleware.py`
- `palace/auth/key_service.py`
- `palace/auth/scopes.py`
- `palace/auth/usage.py`
- `palace/auth/context.py` — `AuthContext` dataclass
- `palace/api/admin.py` — `/v1/admin/keys` routes
- `tests/test_auth_middleware.py`
- `tests/test_auth_keys.py`
- `tests/test_auth_scopes.py`
- `tests/integration/test_auth_live.py`

## Files to modify

- `palace/models.py` — add `ApiKey` table
- `palace/main.py` — register middleware, register admin router, call `key_service.bootstrap_if_needed` in lifespan
- `palace/config.py` — add `bootstrap_admin_key`, `auth_disabled` settings
- `tests/conftest.py` — set `PALACE_AUTH_DISABLED=true` in `client` fixture; add `mock_key_service` fixture; add new patches
- `palace_client/palace_client/client.py` — add `api_key: str | None = None` constructor param; send `X-Palace-Key` header on every request
- `palace_client/tests/test_client.py` — assert header is sent
- `examples/mypalclara_router.py` — accept `palace_api_key` config and pass to client constructor
- `pyproject.toml` — add `bcrypt>=4.1` dep
- `README.md` — auth section

---

## Edge cases & test matrix

| Scenario | Expected |
|---|---|
| No header | 401 `unauthenticated` |
| Header but key not found | 401 `unauthenticated` |
| Header valid but revoked | 401 `unauthenticated` (don't leak that key existed) |
| Header valid, scope insufficient | 403 `forbidden` with required scope in message |
| Header valid, scope sufficient | 200 + handler runs |
| `PALACE_AUTH_DISABLED=true` | All requests pass; auth context has all scopes |
| `/health` | Always 200, no auth |
| `/docs` | Always 200, no auth |
| Bootstrap env set, no admin keys | Key inserted on lifespan, INFO log |
| Bootstrap env set, admin key exists | No-op |
| Bootstrap env unset, no admin keys | WARN log |
| Create key with invalid scope `"superuser"` | 422 `validation_error` |
| Revoke non-existent key | 404 |
| GET /v1/admin/keys with read-only key | 403 |
| Last-used updates debounced | Two requests within 60s → one DB write |
| key prefix collision | Astronomically unlikely; bcrypt mismatch handles it; test injects two rows with same prefix and verifies correct one wins |

## Integration test plan

`tests/integration/test_auth_live.py`:
1. Start app with `PALACE_AUTH_DISABLED=false` and `PALACE_BOOTSTRAP_ADMIN_KEY=pk_live_test...`
2. Verify `/health` works without key
3. Verify `/v1/memories` 401 without key
4. Verify with admin key, can create a `write` key
5. Verify `write` key can create memories but not list api keys
6. Verify revoked key gets 401
7. Verify bcrypt timing — no observable difference between "key not found" and "key found, hash mismatch" (within 50ms)

---

## Migration plan

Phase 3 has no live data, so no Alembic — `init_db` creates the new table. (Alembic comes in slice 2 for the tenant_id backfill.)

## Done criteria

- All 11 mock-test scenarios above pass
- Live integration `test_auth_live.py` passes against real Postgres
- Existing 100+ mock tests still pass (because `client` fixture sets bypass)
- `palace_client` carries the API key transparently
- README documents auth setup, bootstrap, and key issuance
- Merged to `phase-3` via PR
