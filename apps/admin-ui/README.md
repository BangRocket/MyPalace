# mypalace-admin-ui

Browser-based operator console for [MyPalace](https://github.com/BangRocket/MyPalace). Mirrors the day-to-day surface of `mypalace-admin` (CLI) plus a few browse-style flows that are easier in a UI (audit history, memory browser, live health).

Design rationale + decisions: [`docs/admin-ui-design.md`](../../docs/admin-ui-design.md).

## Stack

- Vite + React 18 + TypeScript
- Tailwind CSS for styling
- TanStack Query for data fetching
- React Router for client-side routing
- Vitest + React Testing Library for unit tests

## v1 surface

- **Login** — admin key in `sessionStorage`, sent as `X-Palace-Key` on every API call. Closing the tab signs out.
- **Health** (default page) — backend-by-backend status from `/ready`, polling every 10s.
- **Tenants** — list, create, drop (calls `/v1/admin/tenants`).
- **API keys** — list (with `?include_revoked=true` toggle), mint with one-time plaintext display, revoke.
- **Stats** — per-tenant snapshot (or `ALL`) with row counts, 7d activity, FSRS health, top users.
- **Audit log** — paginated browse with key_id / path_prefix filters.
- **Memories** — read-only browser per (user, optional agent).

Everything write-related on routes other than tenants/keys is intentionally **not** in v1 — operators script those via the CLI.

## Local development

```bash
# 1. Start a MyPalace server on localhost:8000 (in another terminal):
cd ../..
docker compose up postgres qdrant
.venv/bin/uvicorn mypalace.main:app --reload

# 2. Build / run the UI:
cd apps/admin-ui
npm install
npm run dev          # http://localhost:5173/admin/  (vite proxies /v1 → :8000)
```

## Build

```bash
npm run build        # outputs dist/
npm run preview      # serves dist/ on http://localhost:4173/admin/
```

The production Docker image (`Dockerfile`) builds the bundle in a Node stage and copies `dist/` into the Python image at `/app/static/admin/`. The server's `mypalace.main._mount_admin_ui()` picks it up and mounts it at `/admin/*`.

## Tests

```bash
npm test             # vitest run
npm run typecheck    # tsc --noEmit
```

E2E tests are out of scope for v1 (per design §7) — re-evaluate once operator usage patterns settle.

## Auth + security notes

- Admin key sits in `sessionStorage`. XSS in any UI component would leak it; mitigations are React's default escaping, no `dangerouslySetInnerHTML` anywhere, and the same trust boundary as the CLI (the operator already pastes this key into shell commands).
- Same-origin only; no CORS in v1. UI and API share the MyPalace origin.
- A `401` from any API call automatically clears the stored key and bounces back to the login screen.

## License

PolyForm Noncommercial 1.0.0 — same as the rest of MyPalace.
