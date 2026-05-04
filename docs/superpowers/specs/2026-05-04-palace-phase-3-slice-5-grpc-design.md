# Palace Phase 3 — Slice 5: gRPC Transport

**Date:** 2026-05-04
**Branch:** `phase-3-slice-5-grpc` (off `phase-3`)
**Depends on:** slices 1+2 (auth metadata, tenant scoping)

## Goal

Add gRPC as a parallel transport. Same auth (X-Palace-Key in metadata), same tenant binding, same services underneath. **Scope this slice to MemoryService only** — Create, Search, Get, Delete, List. The remaining 12+ surfaces wait for phase 4 unless a real consumer asks for them sooner.

Rationale: a partially-implemented gRPC surface is worse than none. Better to ship a small, complete service and document the path to full parity than to ship a half-mirrored mess.

## Surface

- `proto/palace.proto` — `MemoryService` definition + shared message types
- `palace/grpc/__init__.py`
- `palace/grpc/server.py` — `grpc.aio` server. Runs on a separate port. Spawned by `python -m palace.grpc` or alongside FastAPI via `lifespan` (opt-in via env).
- `palace/grpc/memory_servicer.py` — Servicer implementation that delegates to `memory_service`
- `palace/grpc/auth_interceptor.py` — extracts `x-palace-key` from metadata, runs key_service.lookup, attaches AuthContext to ServicerContext
- `palace/grpc/_generated/` — checked-in `*_pb2.py` and `*_pb2_grpc.py` stubs (regenerated via Makefile target)
- `palace_client/palace_client/grpc.py` — `PalaceGrpcClient` mirroring relevant `PalaceClient` methods

## Decisions

| ID | Decision | Why |
|---|---|---|
| D5.1 | REST stays primary; gRPC additive | No breaking change |
| D5.2 | MemoryService only this slice | Avoid half-built surface |
| D5.3 | Stubs checked in (not generated at build) | Simpler ops; deterministic |
| D5.4 | Auth via metadata key `x-palace-key` (lowercase per HTTP/2 norms) | Mirrors HTTP header |
| D5.5 | Server starts via `PALACE_GRPC_PORT` env (unset = HTTP-only) | Zero-config dev unchanged |
| D5.6 | One unified .proto file | Easy to evolve; one import |

## .proto sketch

```proto
syntax = "proto3";
package palace.v1;

service MemoryService {
  rpc CreateMemory(CreateMemoryRequest) returns (MemoryResponse);
  rpc GetMemory(GetMemoryRequest) returns (MemoryResponse);
  rpc DeleteMemory(DeleteMemoryRequest) returns (DeleteResponse);
  rpc SearchMemories(SearchMemoriesRequest) returns (SearchMemoriesResponse);
  rpc ListMemories(ListMemoriesRequest) returns (ListMemoriesResponse);
}

message Memory {
  string id = 1;
  string user_id = 2;
  string agent_id = 3;
  string content = 4;
  string memory_type = 5;
  float importance = 6;
  string created_at = 7;
  string updated_at = 8;
}
// ... plus request/response messages
```

## Done criteria

- gRPC server starts when `PALACE_GRPC_PORT` is set
- Auth interceptor enforces X-Palace-Key (returns UNAUTHENTICATED otherwise)
- 5 MemoryService RPCs work end-to-end against real services
- PalaceGrpcClient covers same 5 methods
- README documents how to enable + use
- Tests cover servicer logic (mocking memory_service) + interceptor
- Existing 205 mock tests still pass
