# Admin web UI — design doc (phase 13 slice 0)

**Status:** DRAFT, awaiting Joshua sign-off before any 13.1 code lands.
**Author:** Claude (per phase-13 plan).
**Last updated:** 2026-05-05.

This document scopes a browser-based operator console for MyPalace.
Today operators have two surfaces: raw HTTP via `curl` (or any client)
and the `mypalace-admin` CLI. Phase 13 adds a third — a small web app
that visualizes tenants, keys, stats, audit history, and (later)
memories. **No code yet.** Goal: agree on stack, location, auth, CORS,
and deploy story before scaffolding.

The README has historically listed "admin web UI" as **out of scope**;
phase 13 reverses that. The motivation is the same as the CLI's:
operators benefit from human-friendly surfaces, and a browser is the
right home for browse-style flows (e.g. paging audit history, scrolling
through memory rows for a tenant) that fit poorly in argparse output.

---

## 1. What it does (and doesn't)

**In scope for v1:**

- **Login** with the admin API key (via the same `X-Palace-Key` header
  the rest of MyPalace uses). No separate user system.
- **Tenants** — list, create, drop (with the same `confirm=<id>` guard
  the API requires).
- **API keys** — list, mint (one-time plaintext display), revoke.
- **Stats** dashboard — per-tenant row counts, 7d activity, FSRS
  health, top users.
- **Audit log** — paginated browse with method/path/key_id filters.
- **Memories** — read-only browser per (tenant, user). Search + pagination.
- **Health** — backend-by-backend status from `/ready`.

**Out of scope for v1:**

- Memory editing (write-paths stay on the API; the UI is read-mostly
  for safety).
- Personality trait editing (admin endpoints exist but adding UI is
  premature).
- Multi-user UI auth (no SSO, no sessions). One admin key per tab.
- Charts beyond simple counters (no time-series; Prometheus already
  owns that).
- Real-time WebSocket event streaming (the `/v1/events` surface is
  there, but a polling refresh covers v1's use cases).

**Out of scope, period:**

- Persistent server-side state (no UI-side database, no user prefs).
  Browser localStorage is the only state outside the API.

---

## 2. Stack recommendation

**Recommendation: Vite + React + TypeScript, no SSR, hosted as a
static SPA on the same origin as MyPalace.**

| Choice | Why | Tradeoff |
|---|---|---|
| **Vite** | Fast dev loop, zero-config TypeScript, well-trodden. | Adds Node.js to the dev tooling chain. Mitigated by checking the built `dist/` into the docker image — operators don't need Node. |
| **React** | Largest ecosystem, easy to staff. Familiar. | Heavier than alternatives (Solid, Svelte). Doesn't matter for a small admin tool. |
| **TypeScript** | The MyPalace API has rich types via Pydantic; it's worth keeping that fidelity on the client. | Requires keeping a small set of shared types (or generating them from OpenAPI). |
| **No SSR** | Removes a runtime — the UI is just static files served by the existing FastAPI. | Loses search-engine indexing, which doesn't matter for an admin console. |
| **Tailwind CSS** | Cuts CSS to inline classes; consistent design without designing. | Verbose markup. |
| **TanStack Query** for data fetching | Cache + retry + revalidation primitives that match how admin consoles want to behave. | Another dep, but small. |
| **shadcn/ui** for primitives | Copy-paste components built on Radix; no global theme commitment. | Manual install per component (deliberate). |

**Alternatives considered and rejected:**

- **HTMX + Jinja templates served by FastAPI.** Smaller stack, no
  Node. But: every interaction needs a server round-trip, the API surface
  bifurcates ("HTML for the UI, JSON for everyone else"), and we lose the
  ability for operators to point the UI at a remote MyPalace.
- **Astro / Next.js / SvelteKit.** All overkill for an SPA with one
  surface (the existing JSON API). Adding SSR adds a deploy story.
- **Plain HTML + vanilla JS.** Honest answer: this UI fits in 800
  lines of vanilla JS. But: TypeScript catches API-contract drift the
  moment Pydantic models change, and the data-fetch patterns (auth,
  retry, pagination) are real value. React + Vite isn't oversized for
  this.
- **A separate repo** (e.g. `mypalace-admin-ui`). Keeps the server
  package small, but operators have to bind two artifacts together.
  Recommendation: same repo, same release cadence.

---

## 3. Location in the repo

**Recommendation:** `apps/admin-ui/` — a sibling of `mypalace_client/`.

```
/Volumes/Storage/Code/Palace/
├── alembic/
├── apps/
│   └── admin-ui/                 ← new in 13.1
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── public/
│       └── src/
├── docs/
├── mypalace/                     ← server
├── mypalace_client/              ← client + CLI
├── tests/
└── pyproject.toml
```

Why `apps/`: leaves room for future apps (CLI in client today;
hypothetically a desktop app or a TUI later) without ad-hoc top-level
directories.

---

## 4. Auth flow

**Recommendation: keep it server-driven.** No new endpoints; reuse the
existing `X-Palace-Key` header.

1. UI loads `/admin/index.html`. The page is **public** (so the user
   can reach the login screen).
2. The login form takes the admin key, stores it in `sessionStorage`
   (NOT `localStorage` — sessionStorage clears on tab close, which is
   the right default for an admin tool).
3. Every API call attaches `X-Palace-Key: <stored-key>`.
4. On `401`, the UI clears storage and shows the login screen.
5. There's no "logout" button per se — closing the tab logs out.
   (Add a button later if operators ask.)

**Why not a cookie session?** Would require new endpoints
(`/v1/admin/login`, `/v1/admin/logout`), CSRF tokens, and another
threat-model surface. The CLI already proves that header-only auth is
fine for operator tools.

**XSS risk:** the admin key is in `sessionStorage`, so a stored XSS in
any UI component leaks it. Mitigations:
- React's default escaping covers most surfaces.
- No `dangerouslySetInnerHTML` anywhere in v1.
- Strict CSP header (`default-src 'self'; ...`) served by the existing
  ObservabilityMiddleware.
- The admin key is the same key the operator already pastes into
  curl/CLI — same trust boundary.

---

## 5. CORS

**Recommendation:** UI served from the **same origin** as MyPalace
(under `/admin/*`), so CORS doesn't apply for v1.

Path layout the server adds in 13.1:

- `GET /admin/*` → static files from `apps/admin-ui/dist/` mounted via
  FastAPI's `StaticFiles`.
- `GET /admin/` → serves `index.html` (SPA routing — every unknown
  path returns the same HTML and React Router takes over).
- All API calls go to the same origin's `/v1/admin/*` endpoints. No
  Origin header issues.

**Future:** if operators want to host the UI on a separate origin
(e.g. `admin.palace.example.com` → `palace-api.example.com`), we'll
need to add explicit CORS allowlisting via a `PALACE_ADMIN_UI_ORIGINS`
env var. Out of scope for v1.

---

## 6. Build + deploy

**Recommendation:** Build the UI in CI, ship the `dist/` inside the
existing Docker image.

```dockerfile
# Existing Dockerfile (server-only):
FROM python:3.12-slim AS server
COPY mypalace/ /app/mypalace/
...

# New stage:
FROM node:24-alpine AS ui-build
WORKDIR /ui
COPY apps/admin-ui/package*.json ./
RUN npm ci
COPY apps/admin-ui/ ./
RUN npm run build

FROM python:3.12-slim
# ... existing server steps ...
COPY --from=ui-build /ui/dist /app/static/admin
```

Trade-offs:

- **Pro:** Single image, single tag, single release. Operators get the
  UI for free.
- **Con:** Image grows by ~5 MB (gzipped JS bundle). Negligible.
- **Con:** CI now needs Node. Acceptable; we'll cache `node_modules`.

---

## 7. Test strategy

- **Unit tests:** Vitest for component logic + utility functions.
  React Testing Library for component behavior.
- **End-to-end:** Playwright running against a live MyPalace.
  Smoke-level only in v1 — login → list tenants → mint key → revoke.
  Lives in `apps/admin-ui/e2e/`.
- **Visual regression:** out of scope for v1.
- **Type-checking:** `tsc --noEmit` runs in CI on every push.

---

## 8. Out of scope for v1 (deliberate)

- Multi-language (i18n).
- Light/dark theme toggle (just match `prefers-color-scheme`).
- Keyboard shortcuts beyond browser defaults.
- Anything that requires writing back to the API beyond the CRUD
  endpoints already exposed (no batch delete UI, no bulk reembed
  trigger UI — start scripts via CLI).
- Anything that makes the server stateful for the UI (no UI prefs
  table, no per-operator dashboards).

---

## 9. Open questions for Joshua

1. **Stack ratification** (§2). Vite + React + TypeScript + Tailwind +
   TanStack Query + shadcn/ui — push back on any of these?
2. **Path placement** (§3). `apps/admin-ui/` sibling to `mypalace_client/`?
3. **Auth model** (§4). `sessionStorage` + header — accept the XSS
   trade-off as documented?
4. **Same-origin static serving** (§5). UI mounted under `/admin/*` on
   the existing server, no CORS in v1?
5. **Single-image Docker build** (§6). UI ships inside the server image?
6. **v1 surface** (§1). Tenants + keys + stats + audit + memories
   (read-only) + health is a reasonable cut?
7. **Personality + entity-alias screens** — should they be in v1 or
   deferred to v2 (after we see how operators actually use the rest)?

When you sign off, I'll start phase 13.1.
