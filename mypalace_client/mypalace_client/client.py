"""PalaceClient — async HTTP client for the Palace Memory Service."""

from typing import Any

import httpx

from mypalace_client.exceptions import PalaceError, PalaceNotFound, PalaceTransport
from mypalace_client.models import (
    Context,
    Episode,
    FiredIntention,
    Intention,
    Job,
    JobPending,
    LayeredContext,
    Memory,
    MemoryDynamics,
    Message,
    NarrativeArc,
    ScoreBreakdown,
    ScoredMemory,
    Session,
    SessionWithMessages,
    Supersession,
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
                headers["X-Palace-Key"] = api_key
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
            payload = self._safe_json_for_error(resp)
            raise PalaceNotFound(
                self._error_message(payload, "Not found"),
                status_code=404, payload=payload,
            )
        if resp.status_code >= 400:
            payload = self._safe_json_for_error(resp)
            raise PalaceError(
                self._error_message(payload, f"HTTP {resp.status_code}"),
                status_code=resp.status_code, payload=payload,
            )
        return self._parse_json_or_raise(resp)

    @staticmethod
    def _safe_json_for_error(resp: httpx.Response) -> dict:
        """Best-effort JSON parse of an error response body. Errors swallowed —
        a 502 page can be HTML, but we still want to raise PalaceError with
        whatever status info we have."""
        try:
            payload = resp.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _parse_json_or_raise(resp: httpx.Response) -> dict:
        """Parse a 2xx response body. Raise PalaceError if the body is malformed
        — a successful HTTP status with an unparseable body is a server bug,
        not a transport issue, and we should fail loudly rather than return {}
        and have downstream Pydantic raise a confusing 'missing required field'
        error."""
        try:
            return resp.json()
        except Exception as e:
            raise PalaceError(
                f"Server returned {resp.status_code} but body was not valid JSON: {e}",
                status_code=resp.status_code,
            ) from e

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

    # ---- episodes / reflection ----

    async def reflect_session(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        mode: str = "async",
    ) -> "list[Episode] | JobPending":
        body: dict[str, Any] = {"user_id": user_id, "messages": messages}
        if agent_id is not None:
            body["agent_id"] = agent_id
        if session_id is not None:
            body["session_id"] = session_id
        envelope = await self._request(
            "POST", "/v1/reflection/session",
            json=body, params={"mode": mode},
        )
        data = self._data(envelope)
        if mode == "sync":
            return [Episode.model_validate(e) for e in data or []]
        return JobPending.model_validate(data)

    async def search_episodes(
        self, query: str, user_id: str,
        limit: int = 5, min_significance: float = 0.0,
    ) -> "list[Episode]":
        body = {
            "query": query, "user_id": user_id,
            "limit": limit, "min_significance": min_significance,
        }
        envelope = await self._request("POST", "/v1/episodes/search", json=body)
        return [Episode.model_validate(e) for e in self._data(envelope) or []]

    async def get_recent_episodes(self, user_id: str, limit: int = 5) -> "list[Episode]":
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/episodes/recent",
            params={"limit": limit},
        )
        return [Episode.model_validate(e) for e in self._data(envelope) or []]

    # ---- arcs / synthesis ----

    async def synthesize_narratives(
        self, user_id: str, agent_id: str | None = None,
        lookback_episodes: int = 20, mode: str = "async",
    ) -> "list[NarrativeArc] | JobPending":
        body: dict[str, Any] = {"user_id": user_id, "lookback_episodes": lookback_episodes}
        if agent_id is not None:
            body["agent_id"] = agent_id
        envelope = await self._request(
            "POST", "/v1/synthesis/narratives",
            json=body, params={"mode": mode},
        )
        data = self._data(envelope)
        if mode == "sync":
            return [NarrativeArc.model_validate(a) for a in data or []]
        return JobPending.model_validate(data)

    async def get_active_arcs(self, user_id: str, limit: int = 10) -> "list[NarrativeArc]":
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/arcs/active",
            params={"limit": limit},
        )
        return [NarrativeArc.model_validate(a) for a in self._data(envelope) or []]

    # ---- jobs ----

    async def get_job(self, job_id: str) -> "Job":
        envelope = await self._request("GET", f"/v1/jobs/{job_id}")
        return Job.model_validate(self._data(envelope))

    # ---- dynamics (slice 3) ----

    async def promote_memory(
        self,
        memory_id: str,
        user_id: str,
        grade: int = 3,
        signal_type: str = "used_in_response",
    ) -> MemoryDynamics:
        body = {
            "user_id": user_id,
            "grade": grade,
            "signal_type": signal_type,
        }
        envelope = await self._request(
            "POST", f"/v1/memories/{memory_id}/promote", json=body,
        )
        return MemoryDynamics.model_validate(self._data(envelope))

    async def demote_memory(
        self,
        memory_id: str,
        user_id: str,
        reason: str = "user_correction",
    ) -> MemoryDynamics:
        body = {"user_id": user_id, "reason": reason}
        envelope = await self._request(
            "POST", f"/v1/memories/{memory_id}/demote", json=body,
        )
        return MemoryDynamics.model_validate(self._data(envelope))

    async def get_dynamics(
        self,
        memory_id: str,
        user_id: str,
    ) -> MemoryDynamics:
        envelope = await self._request(
            "GET", f"/v1/memories/{memory_id}/dynamics",
            params={"user_id": user_id},
        )
        return MemoryDynamics.model_validate(self._data(envelope))

    async def score_memory(
        self,
        memory_id: str,
        user_id: str,
        semantic_score: float,
    ) -> ScoreBreakdown:
        body = {"user_id": user_id, "semantic_score": semantic_score}
        envelope = await self._request(
            "POST", f"/v1/memories/{memory_id}/score", json=body,
        )
        return ScoreBreakdown.model_validate(self._data(envelope))

    async def prune_access_logs(self, retention_days: int = 90) -> int:
        envelope = await self._request(
            "POST", "/v1/maintenance/prune-access-logs",
            params={"retention_days": retention_days},
        )
        data = self._data(envelope) or {}
        return int(data.get("deleted", 0))

    # ---- intentions (slice 4) ----

    async def set_intention(
        self,
        user_id: str,
        content: str,
        trigger_conditions: dict,
        agent_id: str | None = None,
        expires_at: Any | None = None,
        source_memory_id: str | None = None,
        priority: int = 0,
        fire_once: bool = True,
    ) -> Intention:
        body: dict[str, Any] = {
            "user_id": user_id,
            "content": content,
            "trigger_conditions": trigger_conditions,
            "priority": priority,
            "fire_once": fire_once,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if expires_at is not None:
            body["expires_at"] = (
                expires_at.isoformat() if hasattr(expires_at, "isoformat") else expires_at
            )
        if source_memory_id is not None:
            body["source_memory_id"] = source_memory_id
        envelope = await self._request("POST", "/v1/intentions", json=body)
        return Intention.model_validate(self._data(envelope))

    async def check_intentions(
        self,
        user_id: str,
        message: str,
        context: dict | None = None,
        agent_id: str | None = None,
    ) -> list[FiredIntention]:
        body: dict[str, Any] = {"user_id": user_id, "message": message}
        if context is not None:
            body["context"] = context
        if agent_id is not None:
            body["agent_id"] = agent_id
        envelope = await self._request("POST", "/v1/intentions/check", json=body)
        return [FiredIntention.model_validate(f) for f in self._data(envelope) or []]

    async def format_intentions(
        self,
        intentions: list[dict],
        max: int = 3,
    ) -> str:
        body = {"intentions": intentions, "max": max}
        envelope = await self._request("POST", "/v1/intentions/format", json=body)
        data = self._data(envelope) or {}
        return str(data.get("text", ""))

    async def list_intentions(
        self,
        user_id: str,
        fired: str = "all",
        limit: int = 50,
    ) -> list[Intention]:
        envelope = await self._request(
            "GET", f"/v1/users/{user_id}/intentions",
            params={"fired": fired, "limit": limit},
        )
        return [Intention.model_validate(i) for i in self._data(envelope) or []]

    async def delete_intention(self, intention_id: str) -> None:
        await self._request("DELETE", f"/v1/intentions/{intention_id}")
        return None

    async def cleanup_expired_intentions(self) -> int:
        envelope = await self._request("POST", "/v1/maintenance/cleanup-intentions")
        data = self._data(envelope) or {}
        return int(data.get("deleted", 0))

    # ---- layered retrieval + supersede (slice 5) ----

    async def assemble_layered_context(
        self,
        user_id: str,
        query: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        max_l1_chars: int = 3200,
        max_l2_chars: int = 12000,
        max_recent_messages: int = 20,
        use_fsrs: bool = True,
        memory_limit: int = 10,
        episode_limit: int = 5,
        min_episode_significance: float = 0.3,
        include_graph: bool = False,
        graph_depth: int = 1,
        graph_max_neighbors: int = 50,
    ) -> LayeredContext:
        body: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "max_l1_chars": max_l1_chars,
            "max_l2_chars": max_l2_chars,
            "max_recent_messages": max_recent_messages,
            "use_fsrs": use_fsrs,
            "memory_limit": memory_limit,
            "episode_limit": episode_limit,
            "min_episode_significance": min_episode_significance,
            "include_graph": include_graph,
            "graph_depth": graph_depth,
            "graph_max_neighbors": graph_max_neighbors,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        if session_id is not None:
            body["session_id"] = session_id
        envelope = await self._request("POST", "/v1/context/layered", json=body)
        return LayeredContext.model_validate(self._data(envelope))

    async def supersede_memory(
        self,
        memory_id: str,
        user_id: str,
        new_content: str,
        reason: str = "manual_correction",
        metadata: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "user_id": user_id,
            "new_content": new_content,
            "reason": reason,
        }
        if metadata is not None:
            body["metadata"] = metadata
        envelope = await self._request(
            "POST", f"/v1/memories/{memory_id}/supersede", json=body,
        )
        return dict(self._data(envelope) or {})

    async def get_supersessions(self, memory_id: str) -> list[Supersession]:
        envelope = await self._request(
            "GET", f"/v1/memories/{memory_id}/supersedes",
        )
        return [Supersession.model_validate(s) for s in self._data(envelope) or []]

    # ---- health ----

    async def health(self) -> dict:
        return await self._request("GET", "/health")
