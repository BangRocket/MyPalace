"""Shared Pydantic models for API request/response envelopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from palace.models import Memory

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateMemoryRequest(BaseModel):
    user_id: str
    content: str
    memory_type: str = "semantic"
    agent_id: str | None = None
    source: str | None = None
    importance: float = 1.0
    metadata: dict[str, Any] | None = None


class BatchMessage(BaseModel):
    """A single message in a batch-create request. Extra keys allowed and
    flow through into per-memory metadata (per-message keys win over request
    metadata on collision)."""
    model_config = {"extra": "allow"}
    role: str
    content: str


class BatchCreateMemoriesRequest(BaseModel):
    user_id: str
    messages: list[BatchMessage]
    agent_id: str | None = None
    memory_type: str = "episodic"
    metadata: dict[str, Any] | None = None
    source: str | None = None
    infer: bool = False  # accepted but ignored in slice 1 (spec D7)


class ListMemoriesRequest(BaseModel):
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    memory_type: str | None = None
    metadata: dict[str, Any] | None = None
    limit: int = 50
    offset: int = 0


class UpdateMemoryRequest(BaseModel):
    content: str | None = None
    memory_type: str | None = None
    importance: float | None = None
    metadata: dict[str, Any] | None = None


class SearchMemoriesRequest(BaseModel):
    query: str
    user_id: str | None = None
    agent_id: str | None = None
    memory_type: str | None = None
    limit: int = 10
    min_score: float = 0.0


class CreateSessionRequest(BaseModel):
    user_id: str
    title: str | None = None


class AddMessageRequest(BaseModel):
    user_id: str
    role: str
    content: str


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    summary: str | None = None


class AssembleContextRequest(BaseModel):
    user_id: str
    query: str
    session_id: str | None = None
    max_memories: int = 10
    max_messages: int = 20


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MemoryOut(BaseModel):
    id: str
    user_id: str
    agent_id: str | None
    content: str
    memory_type: str
    source: str | None
    importance: float
    created_at: str | None
    updated_at: str | None
    accessed_at: str | None
    access_count: int
    metadata: dict[str, Any] | None

    @classmethod
    def from_memory(cls, m: Memory) -> MemoryOut:
        return cls(
            id=m.id,
            user_id=m.user_id,
            agent_id=m.agent_id,
            content=m.content,
            memory_type=m.memory_type,
            source=m.source,
            importance=m.importance,
            created_at=m.created_at.isoformat() if m.created_at else None,
            updated_at=m.updated_at.isoformat() if m.updated_at else None,
            accessed_at=m.accessed_at.isoformat() if m.accessed_at else None,
            access_count=m.access_count,
            metadata=m.metadata_json,
        )


class SearchedMemoryOut(BaseModel):
    id: str
    content: str
    memory_type: str
    importance: float
    score: float
    created_at: str | None


class SessionOut(BaseModel):
    id: str
    user_id: str
    title: str | None
    summary: str | None
    created_at: str | None
    updated_at: str | None


class MessageOut(BaseModel):
    id: str
    user_id: str
    role: str
    content: str
    created_at: str | None


class ContextOut(BaseModel):
    memories: list[dict]
    recent_messages: list[dict]
    summary: str | None


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class Meta(BaseModel):
    count: int = 0
    took_ms: int = 0


class ApiResponse(BaseModel, Generic[T]):
    data: T | None = None
    meta: Meta = Field(default_factory=Meta)


class ApiError(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ApiError


# ---------------------------------------------------------------------------
# Slice 2: episodes / arcs / jobs
# ---------------------------------------------------------------------------

class ReflectionMessage(BaseModel):
    """A single message in a reflection request body."""
    model_config = {"extra": "allow"}
    role: str
    content: str


class ReflectSessionRequest(BaseModel):
    user_id: str
    messages: list[ReflectionMessage]
    agent_id: str | None = None
    session_id: str | None = None


class SynthesizeRequest(BaseModel):
    user_id: str
    agent_id: str | None = None
    lookback_episodes: int = 20


class SearchEpisodesRequest(BaseModel):
    query: str
    user_id: str
    limit: int = 5
    min_significance: float = 0.0


class EpisodeOut(BaseModel):
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    summary: str
    participants: list[str] = []
    topics: list[str] = []
    emotional_tone: str
    significance: float
    timestamp: str | None = None
    session_id: str | None = None
    message_count: int = 0
    score: float | None = None  # only present in search results


class NarrativeArcOut(BaseModel):
    id: str
    user_id: str
    agent_id: str | None = None
    title: str
    summary: str
    status: str
    key_episode_ids: list[str] = []
    emotional_trajectory: str = ""
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_arc(cls, arc) -> NarrativeArcOut:
        return cls(
            id=arc.id,
            user_id=arc.user_id,
            agent_id=arc.agent_id,
            title=arc.title,
            summary=arc.summary,
            status=arc.status,
            key_episode_ids=arc.key_episode_ids or [],
            emotional_trajectory=arc.emotional_trajectory or "",
            created_at=arc.created_at.isoformat() if arc.created_at else None,
            updated_at=arc.updated_at.isoformat() if arc.updated_at else None,
        )


class JobOut(BaseModel):
    id: str
    kind: str
    user_id: str
    status: str
    created_at: str | None = None
    completed_at: str | None = None
    result: list | dict | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, j) -> JobOut:
        return cls(
            id=j.id,
            kind=j.kind,
            user_id=j.user_id,
            status=j.status,
            created_at=j.created_at.isoformat() if j.created_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            result=j.result_json,
            error=j.error,
        )


class JobPendingOut(BaseModel):
    job_id: str
    status: str = "pending"
