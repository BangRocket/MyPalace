# mypalace-client

Async Python client for the [MyPalace Memory Service](https://github.com/BangRocket/mypalace).

## Install

```bash
pip install mypalace-client
# Optional gRPC transport:
pip install "mypalace-client[grpc]"
```

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

## License

PolyForm Noncommercial 1.0.0 — see LICENSE.md.
