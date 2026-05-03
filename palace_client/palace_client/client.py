"""PalaceClient — async HTTP client for the Palace Memory Service."""

from typing import Any

import httpx

from palace_client.exceptions import PalaceError, PalaceNotFound, PalaceTransport
from palace_client.models import (
    Context,
    Memory,
    Message,
    ScoredMemory,
    Session,
    SessionWithMessages,
)


class PalaceClient:
    """Async client for Palace. Use as an async context manager or call
    `aclose()` explicitly."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=timeout, headers=headers,
            )
            self._owns_client = True

    async def __aenter__(self) -> "PalaceClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- HTTP helpers ----

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        try:
            resp = await self._client.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise PalaceTransport(str(e)) from e

        if resp.status_code == 404:
            payload = self._safe_json(resp)
            raise PalaceNotFound(
                self._error_message(payload, "Not found"),
                status_code=404, payload=payload,
            )
        if resp.status_code >= 400:
            payload = self._safe_json(resp)
            raise PalaceError(
                self._error_message(payload, f"HTTP {resp.status_code}"),
                status_code=resp.status_code, payload=payload,
            )
        return self._safe_json(resp)

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict:
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _error_message(payload: dict, fallback: str) -> str:
        if isinstance(payload, dict):
            return str(payload.get("detail") or payload.get("message") or fallback)
        return fallback

    @staticmethod
    def _data(envelope: dict) -> Any:
        return envelope.get("data")

    # ---- memories ----

    async def add(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        memory_type: str = "episodic",
        metadata: dict | None = None,
        source: str | None = None,
        infer: bool = False,
    ) -> list[Memory]:
        body = {
            "user_id": user_id,
            "messages": messages,
            "memory_type": memory_type,
            "infer": infer,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if metadata is not None:
            body["metadata"] = metadata
        if source is not None:
            body["source"] = source
        envelope = await self._request("POST", "/v1/memories/batch", json=body)
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
        source: str | None = None,
    ) -> Memory:
        body = {
            "user_id": user_id,
            "content": content,
            "memory_type": memory_type,
            "importance": importance,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if metadata is not None:
            body["metadata"] = metadata
        if source is not None:
            body["source"] = source
        envelope = await self._request("POST", "/v1/memories", json=body)
        return Memory.model_validate(self._data(envelope))

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[ScoredMemory]:
        body: dict[str, Any] = {"query": query, "limit": limit, "min_score": min_score}
        if user_id is not None:
            body["user_id"] = user_id
        if agent_id is not None:
            body["agent_id"] = agent_id
        if memory_type is not None:
            body["memory_type"] = memory_type
        envelope = await self._request("POST", "/v1/memories/search", json=body)
        return [ScoredMemory.model_validate(m) for m in self._data(envelope) or []]

    async def get(self, memory_id: str) -> Memory:
        envelope = await self._request("GET", f"/v1/memories/{memory_id}")
        return Memory.model_validate(self._data(envelope))

    async def update(self, memory_id: str, **fields: Any) -> Memory:
        envelope = await self._request("PATCH", f"/v1/memories/{memory_id}", json=fields)
        return Memory.model_validate(self._data(envelope))

    async def delete(self, memory_id: str) -> None:
        await self._request("DELETE", f"/v1/memories/{memory_id}")
        return None

    async def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        metadata: dict | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id is not None:
            body["user_id"] = user_id
        if agent_id is not None:
            body["agent_id"] = agent_id
        if run_id is not None:
            body["run_id"] = run_id
        if memory_type is not None:
            body["memory_type"] = memory_type
        if metadata is not None:
            body["metadata"] = metadata
        envelope = await self._request("POST", "/v1/memories/list", json=body)
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    async def delete_all(
        self,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        params: dict[str, str] = {}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if run_id is not None:
            params["run_id"] = run_id
        envelope = await self._request(
            "DELETE", f"/v1/users/{user_id}/memories", params=params,
        )
        data = self._data(envelope) or {}
        return int(data.get("deleted", 0))

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[Memory]:
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/memories", params={"limit": limit},
        )
        return [Memory.model_validate(m) for m in self._data(envelope) or []]

    # ---- sessions ----

    async def create_session(self, user_id: str, title: str | None = None) -> Session:
        body: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            body["title"] = title
        envelope = await self._request("POST", "/v1/sessions", json=body)
        return Session.model_validate(self._data(envelope))

    async def get_session(self, session_id: str) -> SessionWithMessages:
        envelope = await self._request("GET", f"/v1/sessions/{session_id}")
        return SessionWithMessages.model_validate(self._data(envelope))

    async def add_message(
        self, session_id: str, user_id: str, role: str, content: str,
    ) -> Message:
        body = {"user_id": user_id, "role": role, "content": content}
        envelope = await self._request(
            "POST", f"/v1/sessions/{session_id}/messages", json=body,
        )
        return Message.model_validate(self._data(envelope))

    async def update_session(self, session_id: str, **fields: Any) -> Session:
        envelope = await self._request(
            "PATCH", f"/v1/sessions/{session_id}", json=fields,
        )
        return Session.model_validate(self._data(envelope))

    async def delete_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/v1/sessions/{session_id}")
        return None

    # ---- context ----

    async def assemble_context(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        max_memories: int = 10,
        max_messages: int = 20,
    ) -> Context:
        body: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "max_memories": max_memories,
            "max_messages": max_messages,
        }
        if session_id is not None:
            body["session_id"] = session_id
        envelope = await self._request("POST", "/v1/context", json=body)
        return Context.model_validate(self._data(envelope))

    # ---- health ----

    async def health(self) -> dict:
        return await self._request("GET", "/health")
