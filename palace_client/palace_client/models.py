"""Pydantic wire types — mirror Palace's response shapes 1:1."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Memory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    memory_type: str
    source: str | None = None
    importance: float
    created_at: datetime | None = None
    updated_at: datetime | None = None
    accessed_at: datetime | None = None
    access_count: int = 0
    metadata: dict[str, Any] | None = None


class ScoredMemory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    content: str
    memory_type: str
    importance: float
    score: float
    created_at: datetime | None = None


class Session(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    title: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    role: str
    content: str
    created_at: datetime | None = None


class SessionWithMessages(Session):
    messages: list[Message] = Field(default_factory=list)


class Context(BaseModel):
    model_config = ConfigDict(extra="ignore")
    memories: list[dict[str, Any]] = Field(default_factory=list)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None


class Episode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    emotional_tone: str
    significance: float
    timestamp: datetime | None = None
    session_id: str | None = None
    message_count: int = 0
    score: float | None = None


class NarrativeArc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    title: str
    summary: str
    status: str
    key_episode_ids: list[str] = Field(default_factory=list)
    emotional_trajectory: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    kind: str
    user_id: str
    status: str
    created_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any | None = None
    error: str | None = None


class JobPending(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_id: str
    status: str = "pending"


class MemoryDynamics(BaseModel):
    """FSRS-6 state for a memory (slice 3)."""

    model_config = ConfigDict(extra="ignore")
    memory_id: str
    user_id: str
    stability: float
    difficulty: float
    retrieval_strength: float
    storage_strength: float
    is_key: bool = False
    importance_weight: float = 1.0
    category: str | None = None
    tags: dict[str, Any] | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScoreBreakdown(BaseModel):
    """Composite-score breakdown returned by /v1/memories/{id}/score."""

    model_config = ConfigDict(extra="ignore")
    composite_score: float
    fsrs_score: float
    retrievability: float
    storage_strength: float


class Intention(BaseModel):
    """Intention/reminder row (slice 4)."""

    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str
    content: str
    source_memory_id: str | None = None
    trigger_conditions: dict[str, Any]
    priority: int = 0
    fired: bool = False
    fire_once: bool = True
    created_at: datetime | None = None
    expires_at: datetime | None = None
    fired_at: datetime | None = None


class FiredIntention(BaseModel):
    """A single fired-intention payload returned by /v1/intentions/check."""

    model_config = ConfigDict(extra="ignore")
    id: str
    content: str
    trigger_type: str
    priority: int = 0
    match_details: dict[str, Any] = Field(default_factory=dict)
    source_memory_id: str | None = None


# --- slice 5: layered retrieval + smart ingestion ---

class MemoryWithScore(BaseModel):
    """Memory with similarity score and optional FSRS composite score."""

    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    memory_type: str
    importance: float
    score: float
    composite_score: float | None = None
    fsrs_score: float | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class LayeredContext(BaseModel):
    """Structured response from /v1/context/layered. Caller composes
    these tiers into prompts; the service does not return typed Messages."""

    model_config = ConfigDict(extra="ignore")
    l1_user_profile: dict[str, Any] = Field(default_factory=dict)
    l2_relevant_context: dict[str, Any] = Field(default_factory=dict)
    recent_messages: list[dict[str, Any]] | None = None
    summary: str | None = None
    char_counts: dict[str, int] = Field(default_factory=dict)


class Supersession(BaseModel):
    """A row from the memory_supersessions audit table."""

    model_config = ConfigDict(extra="ignore")
    superseded_id: str
    new_id: str
    reason: str
    similarity_score: float | None = None
    created_at: datetime | None = None
