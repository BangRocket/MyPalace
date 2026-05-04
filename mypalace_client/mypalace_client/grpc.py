"""PalaceGrpcClient — async gRPC mirror of PalaceClient.

Phase 3 slice 5 introduced MemoryService bindings; phase 5 slice 2 expands the
client to cover Session / Episode / Arc / Intention / Dynamics / Retrieval /
Ingestion / Job services. The HTTP PalaceClient remains the canonical reference
for behaviour.

Usage:
    async with PalaceGrpcClient("localhost:50051", api_key="pk_live_...") as c:
        mem = await c.create(user_id="u1", content="hello")
        session = await c.create_session(user_id="u1")

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
        from mypalace.grpc._generated import (  # type: ignore[import-not-found]
            mypalace_pb2,
            mypalace_pb2_grpc,
        )

        self._pb2 = mypalace_pb2
        self._pb2_grpc = mypalace_pb2_grpc
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
        self._session_stub = self._pb2_grpc.SessionServiceStub(self._channel)
        self._episode_stub = self._pb2_grpc.EpisodeServiceStub(self._channel)
        self._arc_stub = self._pb2_grpc.ArcServiceStub(self._channel)
        self._intention_stub = self._pb2_grpc.IntentionServiceStub(self._channel)
        self._dynamics_stub = self._pb2_grpc.DynamicsServiceStub(self._channel)
        self._retrieval_stub = self._pb2_grpc.RetrievalServiceStub(self._channel)
        self._ingestion_stub = self._pb2_grpc.IngestionServiceStub(self._channel)
        self._job_stub = self._pb2_grpc.JobServiceStub(self._channel)

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

    # ------------------------------------------------------------------
    # Session ops
    # ------------------------------------------------------------------

    async def create_session(self, user_id: str, title: str | None = None) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.CreateSessionRequest(user_id=user_id, title=title or "")
        resp = await self._session_stub.CreateSession(req, metadata=self._md())
        return _session_to_dict(resp.session)

    async def get_session(self, session_id: str) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetSessionRequest(session_id=session_id)
        resp = await self._session_stub.GetSession(req, metadata=self._md())
        out = _session_to_dict(resp.data.session)
        out["messages"] = [_message_to_dict(m) for m in resp.data.messages]
        return out

    async def add_message(
        self, session_id: str, user_id: str, role: str, content: str,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.AddMessageRequest(
            session_id=session_id, user_id=user_id, role=role, content=content,
        )
        resp = await self._session_stub.AddMessage(req, metadata=self._md())
        return _message_to_dict(resp.message)

    async def update_session(
        self,
        session_id: str,
        title: str | None = None,
        summary: str | None = None,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.UpdateSessionRequest(
            session_id=session_id, title=title or "", summary=summary or "",
        )
        resp = await self._session_stub.UpdateSession(req, metadata=self._md())
        return _session_to_dict(resp.session)

    async def delete_session(self, session_id: str) -> bool:
        if self._stub is None:
            await self._connect()
        req = self._pb2.DeleteSessionRequest(session_id=session_id)
        resp = await self._session_stub.DeleteSession(req, metadata=self._md())
        return bool(resp.deleted)

    # ------------------------------------------------------------------
    # Episode ops
    # ------------------------------------------------------------------

    async def reflect_session(
        self,
        user_id: str,
        messages: list[dict],
        agent_id: str | None = None,
        session_id: str | None = None,
        mode: str = "async",
    ) -> dict:
        """Returns either {"job_id": ..., "status": "pending"} or
        {"episodes": [...]} depending on mode and oneof field."""
        if self._stub is None:
            await self._connect()
        req = self._pb2.ReflectSessionRequest(
            user_id=user_id,
            messages=[
                self._pb2.ReflectionMessage(role=m["role"], content=m["content"])
                for m in messages
            ],
            agent_id=agent_id or "",
            session_id=session_id or "",
            mode=mode,
        )
        resp = await self._episode_stub.ReflectSession(req, metadata=self._md())
        which = resp.WhichOneof("result")
        if which == "pending":
            return {"job_id": resp.pending.job_id, "status": resp.pending.status}
        return {"episodes": [_episode_to_dict(e) for e in resp.episodes.episodes]}

    async def search_episodes(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        min_significance: float = 0.0,
    ) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.SearchEpisodesRequest(
            query=query, user_id=user_id, limit=limit, min_significance=min_significance,
        )
        resp = await self._episode_stub.SearchEpisodes(req, metadata=self._md())
        return [_episode_to_dict(e) for e in resp.episodes]

    async def get_recent_episodes(self, user_id: str, limit: int = 5) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetRecentEpisodesRequest(user_id=user_id, limit=limit)
        resp = await self._episode_stub.GetRecentEpisodes(req, metadata=self._md())
        return [_episode_to_dict(e) for e in resp.episodes]

    # ------------------------------------------------------------------
    # Arc ops
    # ------------------------------------------------------------------

    async def synthesize_narratives(
        self,
        user_id: str,
        agent_id: str | None = None,
        lookback_episodes: int = 20,
        mode: str = "async",
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.SynthesizeNarrativesRequest(
            user_id=user_id,
            agent_id=agent_id or "",
            lookback_episodes=lookback_episodes,
            mode=mode,
        )
        resp = await self._arc_stub.SynthesizeNarratives(req, metadata=self._md())
        which = resp.WhichOneof("result")
        if which == "pending":
            return {"job_id": resp.pending.job_id, "status": resp.pending.status}
        return {"arcs": [_arc_to_dict(a) for a in resp.arcs.arcs]}

    async def get_active_arcs(self, user_id: str, limit: int = 10) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetActiveArcsRequest(user_id=user_id, limit=limit)
        resp = await self._arc_stub.GetActiveArcs(req, metadata=self._md())
        return [_arc_to_dict(a) for a in resp.arcs]

    # ------------------------------------------------------------------
    # Intention ops
    # ------------------------------------------------------------------

    async def set_intention(
        self,
        user_id: str,
        content: str,
        trigger_conditions: dict,
        agent_id: str = "clara",
        expires_at: str | None = None,
        source_memory_id: str | None = None,
        priority: int = 0,
        fire_once: bool = True,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.SetIntentionRequest(
            user_id=user_id,
            content=content,
            trigger_conditions_json=json.dumps(trigger_conditions),
            agent_id=agent_id,
            expires_at=expires_at or "",
            source_memory_id=source_memory_id or "",
            priority=priority,
            fire_once=fire_once,
        )
        resp = await self._intention_stub.SetIntention(req, metadata=self._md())
        return _intention_to_dict(resp.intention)

    async def check_intentions(
        self,
        user_id: str,
        message: str,
        context: dict | None = None,
        agent_id: str = "clara",
    ) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.CheckIntentionsRequest(
            user_id=user_id,
            message=message,
            context_json=json.dumps(context) if context else "",
            agent_id=agent_id,
        )
        resp = await self._intention_stub.CheckIntentions(req, metadata=self._md())
        return [_fired_to_dict(f) for f in resp.fired]

    async def format_intentions(self, intentions: list[dict], max: int = 3) -> str:
        if self._stub is None:
            await self._connect()
        req = self._pb2.FormatIntentionsRequest(
            intentions_json=json.dumps(intentions), max=max,
        )
        resp = await self._intention_stub.FormatIntentions(req, metadata=self._md())
        return resp.text

    async def list_intentions(
        self,
        user_id: str,
        fired: str = "all",
        limit: int = 50,
        agent_id: str = "clara",
    ) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.ListIntentionsRequest(
            user_id=user_id, fired=fired, limit=limit, agent_id=agent_id,
        )
        resp = await self._intention_stub.ListIntentions(req, metadata=self._md())
        return [_intention_to_dict(i) for i in resp.intentions]

    async def delete_intention(self, intention_id: str) -> bool:
        if self._stub is None:
            await self._connect()
        req = self._pb2.DeleteIntentionRequest(intention_id=intention_id)
        resp = await self._intention_stub.DeleteIntention(req, metadata=self._md())
        return bool(resp.deleted)

    # ------------------------------------------------------------------
    # Dynamics ops
    # ------------------------------------------------------------------

    async def promote_memory(
        self,
        memory_id: str,
        user_id: str,
        grade: int = 3,
        signal_type: str = "used_in_response",
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.PromoteMemoryRequest(
            memory_id=memory_id, user_id=user_id, grade=grade, signal_type=signal_type,
        )
        resp = await self._dynamics_stub.PromoteMemory(req, metadata=self._md())
        return _dynamics_to_dict(resp.dynamics)

    async def demote_memory(
        self, memory_id: str, user_id: str, reason: str = "user_correction",
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.DemoteMemoryRequest(
            memory_id=memory_id, user_id=user_id, reason=reason,
        )
        resp = await self._dynamics_stub.DemoteMemory(req, metadata=self._md())
        return _dynamics_to_dict(resp.dynamics)

    async def get_dynamics(self, memory_id: str, user_id: str) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetDynamicsRequest(memory_id=memory_id, user_id=user_id)
        resp = await self._dynamics_stub.GetDynamics(req, metadata=self._md())
        return _dynamics_to_dict(resp.dynamics)

    async def score_memory(
        self, memory_id: str, user_id: str, semantic_score: float,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.ScoreMemoryRequest(
            memory_id=memory_id, user_id=user_id, semantic_score=semantic_score,
        )
        resp = await self._dynamics_stub.ScoreMemory(req, metadata=self._md())
        b = resp.breakdown
        return {
            "composite_score": float(b.composite_score),
            "fsrs_score": float(b.fsrs_score),
            "retrievability": float(b.retrievability),
            "storage_strength": float(b.storage_strength),
        }

    # ------------------------------------------------------------------
    # Retrieval ops
    # ------------------------------------------------------------------

    async def assemble_layered(
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
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.AssembleLayeredRequest(
            user_id=user_id,
            query=query,
            agent_id=agent_id or "",
            session_id=session_id or "",
            max_l1_chars=max_l1_chars,
            max_l2_chars=max_l2_chars,
            max_recent_messages=max_recent_messages,
            use_fsrs=use_fsrs,
            memory_limit=memory_limit,
            episode_limit=episode_limit,
            min_episode_significance=min_episode_significance,
            include_graph=include_graph,
            graph_depth=graph_depth,
            graph_max_neighbors=graph_max_neighbors,
        )
        resp = await self._retrieval_stub.AssembleLayered(req, metadata=self._md())
        ctx = resp.context
        out = {
            "l1_user_profile": {
                "memories": json.loads(ctx.l1_user_profile.memories_json or "[]"),
                "recent_episodes": json.loads(
                    ctx.l1_user_profile.recent_episodes_json or "[]",
                ),
                "active_arcs": json.loads(ctx.l1_user_profile.active_arcs_json or "[]"),
            },
            "l2_relevant_context": {
                "memories": json.loads(ctx.l2_relevant_context.memories_json or "[]"),
                "episodes": json.loads(ctx.l2_relevant_context.episodes_json or "[]"),
            },
            "l3_graph_context": None,
            "recent_messages": (
                json.loads(ctx.recent_messages_json) if ctx.recent_messages_json else None
            ),
            "summary": ctx.summary or None,
            "char_counts": {
                "l1": int(ctx.char_counts.l1),
                "l2": int(ctx.char_counts.l2),
            },
        }
        if ctx.has_l3_graph_context:
            out["l3_graph_context"] = {
                "related_memories": json.loads(
                    ctx.l3_graph_context.related_memories_json or "[]",
                ),
                "edges": json.loads(ctx.l3_graph_context.edges_json or "[]"),
            }
        return out

    # ------------------------------------------------------------------
    # Ingestion ops
    # ------------------------------------------------------------------

    async def supersede_memory(
        self,
        memory_id: str,
        user_id: str,
        new_content: str,
        reason: str = "manual_correction",
        metadata: dict | None = None,
    ) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.SupersedeMemoryRequest(
            memory_id=memory_id,
            user_id=user_id,
            new_content=new_content,
            reason=reason,
            metadata_json=json.dumps(metadata) if metadata else "",
        )
        resp = await self._ingestion_stub.SupersedeMemory(req, metadata=self._md())
        return _supersession_to_dict(resp.supersession)

    async def get_supersessions(self, memory_id: str) -> list[dict]:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetSupersessionsRequest(memory_id=memory_id)
        resp = await self._ingestion_stub.GetSupersessions(req, metadata=self._md())
        return [_supersession_to_dict(s) for s in resp.supersessions]

    # ------------------------------------------------------------------
    # Job ops
    # ------------------------------------------------------------------

    async def get_job(self, job_id: str) -> dict:
        if self._stub is None:
            await self._connect()
        req = self._pb2.GetJobRequest(job_id=job_id)
        resp = await self._job_stub.GetJob(req, metadata=self._md())
        return _job_to_dict(resp.job)


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


def _session_to_dict(s: Any) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "title": s.title or None,
        "summary": s.summary or None,
        "created_at": s.created_at or None,
        "updated_at": s.updated_at or None,
    }


def _message_to_dict(m: Any) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at or None,
    }


def _episode_to_dict(e: Any) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "agent_id": e.agent_id or None,
        "content": e.content,
        "summary": e.summary,
        "participants": list(e.participants),
        "topics": list(e.topics),
        "emotional_tone": e.emotional_tone,
        "significance": float(e.significance),
        "timestamp": e.timestamp or None,
        "session_id": e.session_id or None,
        "message_count": int(e.message_count),
        "score": float(e.score) if e.score else None,
    }


def _arc_to_dict(a: Any) -> dict:
    return {
        "id": a.id,
        "user_id": a.user_id,
        "agent_id": a.agent_id or None,
        "title": a.title,
        "summary": a.summary,
        "status": a.status,
        "key_episode_ids": list(a.key_episode_ids),
        "emotional_trajectory": a.emotional_trajectory or "",
        "created_at": a.created_at or None,
        "updated_at": a.updated_at or None,
    }


def _intention_to_dict(i: Any) -> dict:
    return {
        "id": i.id,
        "user_id": i.user_id,
        "agent_id": i.agent_id,
        "content": i.content,
        "source_memory_id": i.source_memory_id or None,
        "trigger_conditions": (
            json.loads(i.trigger_conditions_json) if i.trigger_conditions_json else {}
        ),
        "priority": int(i.priority),
        "fired": bool(i.fired),
        "fire_once": bool(i.fire_once),
        "created_at": i.created_at or None,
        "expires_at": i.expires_at or None,
        "fired_at": i.fired_at or None,
    }


def _fired_to_dict(f: Any) -> dict:
    return {
        "id": f.id,
        "content": f.content,
        "trigger_type": f.trigger_type,
        "priority": int(f.priority),
        "match_details": (
            json.loads(f.match_details_json) if f.match_details_json else {}
        ),
        "source_memory_id": f.source_memory_id or None,
    }


def _dynamics_to_dict(d: Any) -> dict:
    return {
        "memory_id": d.memory_id,
        "user_id": d.user_id,
        "stability": float(d.stability),
        "difficulty": float(d.difficulty),
        "retrieval_strength": float(d.retrieval_strength),
        "storage_strength": float(d.storage_strength),
        "is_key": bool(d.is_key),
        "importance_weight": float(d.importance_weight),
        "category": d.category or None,
        "tags": json.loads(d.tags_json) if d.tags_json else None,
        "last_accessed_at": d.last_accessed_at or None,
        "access_count": int(d.access_count),
        "created_at": d.created_at or None,
        "updated_at": d.updated_at or None,
    }


def _supersession_to_dict(s: Any) -> dict:
    return {
        "superseded_id": s.superseded_id,
        "new_id": s.new_id,
        "reason": s.reason,
        "similarity_score": float(s.similarity_score) if s.has_similarity_score else None,
        "created_at": s.created_at or None,
    }


def _job_to_dict(j: Any) -> dict:
    return {
        "id": j.id,
        "kind": j.kind,
        "user_id": j.user_id,
        "status": j.status,
        "created_at": j.created_at or None,
        "completed_at": j.completed_at or None,
        "result": json.loads(j.result_json) if j.result_json else None,
        "error": j.error or None,
    }
