"""Shared Pydantic models for API request/response envelopes."""

from __future__ import annotations

import json
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
            metadata=json.loads(m.metadata_json) if m.metadata_json else None,
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
