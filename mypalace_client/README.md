# mypalace-client

Async Python client for the [MyPalace Memory Service](https://github.com/BangRocket/mypalace).

## Install

```bash
pip install mypalace-client
# Optional gRPC transport:
pip install "mypalace-client[grpc]"
# Operator CLI (`mypalace-admin`):
pip install "mypalace-client[cli]"
```

> The `mypalace-admin` CLI is bundled with this package as of v0.10.x.
> If you previously got it via the server-side `mypalace` package, that
> entry point still works as a deprecation shim and will be removed
> in v0.12.0 — switch to `pip install 'mypalace-client[cli]'`.

## Quick start

```python
import asyncio
from palace_client import PalaceClient

async def main():
    async with PalaceClient(
        base_url="http://localhost:8000",
        api_key="pk_live_...",
    ) as client:
        # Add a memory
        mem = await client.create(
            user_id="u1",
            content="Joshua likes oat milk",
            memory_type="preference",
        )
        # Search
        results = await client.search(query="milk", user_id="u1", limit=5)
        for r in results:
            print(r.score, r.content)

asyncio.run(main())
```

## Features

Mirrors the full Palace HTTP API:

- Memory CRUD + semantic search + smart-ingestion (`infer=True`)
- Sessions + messages
- Episode reflection + narrative arc synthesis
- FSRS dynamics (promote/demote/score)
- Intentions (set/check/format)
- Layered context assembly
- Manual supersede + supersession history

## Auth

Pass `api_key` to the constructor; the client sends it as `X-Palace-Key` on every request. Without an API key, the client works against a server with `PALACE_AUTH_DISABLED=true`.

## gRPC (optional)

Phase 3 ships a focused gRPC mirror covering MemoryService (Create/Get/Delete/Search/List). Use `PalaceGrpcClient` when you want lower-overhead binary transport for memory ops:

```python
from palace_client.grpc import PalaceGrpcClient

async with PalaceGrpcClient("localhost:50051", api_key="pk_live_...") as c:
    mem = await c.create(user_id="u1", content="hello via gRPC")
```

Other surfaces (sessions, episodes, etc.) ride HTTP via `PalaceClient`.

## CLI: `mypalace-admin`

Operator wrapper around the HTTP admin surface. Subcommands cover the
day-to-day surface — `health`, `version`, `keys {list|mint|revoke}`,
`tenants {list|create}`, `stats`, `audit`, `reembed`, `job`, `export`.

```bash
export MYPALACE_URL=http://your-palace:8000
export MYPALACE_ADMIN_KEY=pk_live_...

mypalace-admin health
mypalace-admin tenants list
mypalace-admin keys mint --label acme-prod --scopes read,write --tenant-id acme
mypalace-admin stats acme
mypalace-admin export acme -o acme.ndjson
```

`--json` emits raw JSON (good for `jq` pipelines).

## License

PolyForm Noncommercial 1.0.0 — see LICENSE.md.
