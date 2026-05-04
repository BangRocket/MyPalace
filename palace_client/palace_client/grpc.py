"""PalaceGrpcClient — async gRPC mirror of PalaceClient (memory ops only).

Phase 3 slice 5: scope is MemoryService — Create / Get / Delete / Search /
List. Other surfaces (sessions, episodes, etc.) ride HTTP via PalaceClient
for now.

Usage:
    async with PalaceGrpcClient("localhost:50051", api_key="pk_live_...") as c:
        mem = await c.create(user_id="u1", content="hello")

This module imports `grpc` and the generated stubs lazily so that the
HTTP-only PalaceClient remains importable without grpcio installed.
"""

from __future__ import annotations

import json
from typing import Any


class PalaceGrpcClient:
    """Async gRPC client mirroring a subset of PalaceClient (memory ops)."""

    def __init__(self, address: str, api_key: str | None = None) -> None:
        try:
            import grpc  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "grpcio not installed; install palace-client[grpc] to use this transport",
            ) from e
        # Generated stubs must be importable from within the *server* package
        # — we re-import them here from the same path.
        from palace.grpc._generated import (  # type: ignore[import-not-found]
            palace_pb2,
            palace_pb2_grpc,
        )

        self._pb2 = palace_pb2
        self._pb2_grpc = palace_pb2_grpc
        self._address = address
        self._api_key = api_key
        self._channel: Any = None
        self._stub: Any = None

    async def __aenter__(self) -> PalaceGrpcClient:
        await self._connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _connect(self) -> None:
        import grpc
        self._channel = grpc.aio.insecure_channel(self._address)
        self._stub = self._pb2_grpc.MemoryServiceStub(self._channel)

    async def aclose(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    def _md(self) -> list[tuple[str, str]]:
        if not self._api_key:
            return []
        return [("x-palace-key", self._api_key)]

    # ------------------------------------------------------------------
    # Memory ops
    # ------------------------------------------------------------------

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        source: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.CreateMemoryRequest(
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            agent_id=agent_id or "",
            source=source or "",
            importance=importance,
            metadata_json=json.dumps(metadata) if metadata else "",
        )
        resp = await self._stub.CreateMemory(req, metadata=self._md())
        return _memory_to_dict(resp.memory)

    async def get(self, memory_id: str) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetMemoryRequest(memory_id=memory_id)
        resp = await self._stub.GetMemory(req, metadata=self._md())
        return _memory_to_dict(resp.memory)

    async def delete(self, memory_id: str) -> bool:
        if self._stub is None:
            await self._connect()
        req = self._pb2.DeleteMemoryRequest(memory_id=memory_id)
        resp = await self._stub.DeleteMemory(req, metadata=self._md())
        return bool(resp.deleted)

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.SearchMemoriesRequest(
            query=query,
            user_id=user_id or "",
            agent_id=agent_id or "",
            memory_type=memory_type or "",
            limit=limit,
            min_score=min_score,
        )
        resp = await self._stub.SearchMemories(req, metadata=self._md())
        return [
            {**_memory_to_dict(r.memory), "score": float(r.score)}
            for r in resp.results
        ]

    async def list_memories(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.ListMemoriesRequest(
            user_id=user_id or "",
            agent_id=agent_id or "",
            memory_type=memory_type or "",
            limit=limit,
            offset=offset,
        )
        resp = await self._stub.ListMemories(req, metadata=self._md())
        return [_memory_to_dict(m) for m in resp.memories]


def _memory_to_dict(m: Any) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "agent_id": m.agent_id or None,
        "content": m.content,
        "memory_type": m.memory_type,
        "source": m.source or None,
        "importance": float(m.importance),
        "created_at": m.created_at or None,
        "updated_at": m.updated_at or None,
        "accessed_at": m.accessed_at or None,
        "access_count": int(m.access_count),
        "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
    }
