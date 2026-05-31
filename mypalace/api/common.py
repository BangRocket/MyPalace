"""Shared Pydantic models for API request/response envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypalace.models import Intention, Memory

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
    ttl_seconds: int | None = None  # phase 6 slice 3: optional TTL


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
    # Phase 7 slice 3: optional tenant_id override.
    # - None: tenant-bound key uses its tenant; cross-tenant admin uses
    #   settings.default_tenant_id
    # - "<tenant_id>": tenant-bound key must match its binding (or 403);
    #   cross-tenant admin can target any tenant
    # - "ALL": cross-tenant admin only; searches every tenant's
    #   collection and tags results with their tenant_id
    tenant_id: str | None = None


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
    expires_at: str | None = None  # phase 6 slice 3
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
            expires_at=(
                m.expires_at.isoformat()
                if getattr(m, "expires_at", None) else None
            ),
            metadata=m.metadata_json,
        )


class SearchedMemoryOut(BaseModel):
    id: str
    content: str
    memory_type: str
    importance: float
    score: float
    created_at: str | None
    # Phase 7 slice 3: present iff tenant_id="ALL" search; null otherwise
    # to keep existing single-tenant payloads unchanged.
    tenant_id: str | None = None


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
    """Response metadata. Extra keys allowed (e.g. slice-5 ``supersessions``
    and ``skipped`` debug data appended to /v1/memories/batch responses)."""
    model_config = {"extra": "allow"}
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


# ---------------------------------------------------------------------------
# Slice 3: FSRS dynamics
# ---------------------------------------------------------------------------

class PromoteMemoryRequest(BaseModel):
    user_id: str
    grade: int = 3  # GOOD; valid 1-4
    signal_type: str = "used_in_response"


class DemoteMemoryRequest(BaseModel):
    user_id: str
    reason: str = "user_correction"


class ScoreMemoryRequest(BaseModel):
    user_id: str
    semantic_score: float


class MemoryDynamicsOut(BaseModel):
    memory_id: str
    user_id: str
    stability: float
    difficulty: float
    retrieval_strength: float
    storage_strength: float
    is_key: bool
    importance_weight: float
    category: str | None = None
    tags: dict[str, Any] | None = None
    last_accessed_at: str | None = None
    access_count: int
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dynamics(cls, d) -> MemoryDynamicsOut:
        return cls(
            memory_id=d.memory_id,
            user_id=d.user_id,
            stability=d.stability,
            difficulty=d.difficulty,
            retrieval_strength=d.retrieval_strength,
            storage_strength=d.storage_strength,
            is_key=d.is_key,
            importance_weight=d.importance_weight,
            category=d.category,
            tags=d.tags,
            last_accessed_at=d.last_accessed_at.isoformat() if d.last_accessed_at else None,
            access_count=d.access_count,
            created_at=d.created_at.isoformat() if d.created_at else None,
            updated_at=d.updated_at.isoformat() if d.updated_at else None,
        )


class ScoreBreakdownOut(BaseModel):
    composite_score: float
    fsrs_score: float
    retrievability: float
    storage_strength: float


# ---------------------------------------------------------------------------
# Slice 4: intentions
# ---------------------------------------------------------------------------

class SetIntentionRequest(BaseModel):
    user_id: str
    content: str
    trigger_conditions: dict[str, Any]
    agent_id: str = "clara"
    expires_at: datetime | None = None
    source_memory_id: str | None = None
    priority: int = 0
    fire_once: bool = True


class CheckIntentionsRequest(BaseModel):
    user_id: str
    message: str
    context: dict[str, Any] | None = None
    agent_id: str = "clara"


class FormatIntentionsRequest(BaseModel):
    intentions: list[dict[str, Any]]
    max: int = 3


class IntentionOut(BaseModel):
    id: str
    user_id: str
    agent_id: str
    content: str
    source_memory_id: str | None = None
    trigger_conditions: dict[str, Any]
    priority: int
    fired: bool
    fire_once: bool
    created_at: str | None = None
    expires_at: str | None = None
    fired_at: str | None = None

    @classmethod
    def from_intention(cls, i: Intention) -> IntentionOut:
        return cls(
            id=i.id,
            user_id=i.user_id,
            agent_id=i.agent_id,
            content=i.content,
            source_memory_id=i.source_memory_id,
            trigger_conditions=i.trigger_conditions,
            priority=i.priority,
            fired=i.fired,
            fire_once=i.fire_once,
            created_at=i.created_at.isoformat() if i.created_at else None,
            expires_at=i.expires_at.isoformat() if i.expires_at else None,
            fired_at=i.fired_at.isoformat() if i.fired_at else None,
        )


class FiredIntentionOut(BaseModel):
    id: str
    content: str
    trigger_type: str
    priority: int
    match_details: dict[str, Any]
    source_memory_id: str | None = None


class IntentionFormatOut(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Slice 5: layered retrieval + smart ingestion
# ---------------------------------------------------------------------------

class LayeredContextRequest(BaseModel):
    user_id: str
    query: str
    agent_id: str | None = None
    session_id: str | None = None
    # Defaulting to None lets the service fall back to the env-configured
    # token budgets (PALACE_CONTEXT_BUDGET_L1/L2_TOKENS × 4). Operators may
    # still override per-request via these fields.
    max_l1_chars: int | None = None
    max_l2_chars: int | None = None
    max_recent_messages: int = 20
    use_fsrs: bool = True
    memory_limit: int = 10
    episode_limit: int = 5
    min_episode_significance: float = 0.3
    # Phase 4 slice 6: include 1-hop graph neighbors of L2 memories.
    include_graph: bool = False
    graph_depth: int = 1
    graph_max_neighbors: int = 50


class MemoryWithScoreOut(BaseModel):
    """Memory with similarity score and optional FSRS composite score."""
    id: str
    user_id: str
    agent_id: str | None = None
    content: str
    memory_type: str
    importance: float
    score: float
    composite_score: float | None = None
    fsrs_score: float | None = None
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


class LayeredL1Out(BaseModel):
    memories: list[dict[str, Any]] = []
    recent_episodes: list[dict[str, Any]] = []
    active_arcs: list[dict[str, Any]] = []


class LayeredL2Out(BaseModel):
    memories: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []


class LayeredCharCounts(BaseModel):
    l1: int = 0
    l2: int = 0


class LayeredL3GraphOut(BaseModel):
    """Phase 4 slice 6: 1-hop graph neighbors of the L2 memories. Null when
    include_graph=False or the graph is disabled / empty for this query."""
    related_memories: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []


class LayeredContextOut(BaseModel):
    l1_user_profile: LayeredL1Out
    l2_relevant_context: LayeredL2Out
    l3_graph_context: LayeredL3GraphOut | None = None
    recent_messages: list[dict[str, Any]] | None = None
    summary: str | None = None
    char_counts: LayeredCharCounts


class SupersedeMemoryRequest(BaseModel):
    user_id: str
    new_content: str
    reason: str = "manual_correction"
    metadata: dict[str, Any] | None = None


class SupersessionOut(BaseModel):
    superseded_id: str
    new_id: str
    reason: str
    similarity_score: float | None = None
    created_at: str | None = None


# ---------------------------------------------------------------------------
# Emotional context (phase: emotional + topic services)
# ---------------------------------------------------------------------------

class RecordEmotionalRequest(BaseModel):
    user_id: str
    messages: list[str] = Field(default_factory=list)
    agent_id: str = "default"
    channel_id: str = ""
    channel_name: str = ""
    is_dm: bool = False
    energy: str = "neutral"
    summary: str = ""


class EmotionalContextOut(BaseModel):
    id: str
    user_id: str
    agent_id: str
    channel_id: str
    channel_name: str
    is_dm: bool
    starting_sentiment: float
    ending_sentiment: float
    emotional_arc: str
    energy_level: str
    topic_summary: str
    created_at: str | None

    @classmethod
    def from_row(cls, r: Any) -> "EmotionalContextOut":
        return cls(
            id=r.id,
            user_id=r.user_id,
            agent_id=r.agent_id,
            channel_id=r.channel_id,
            channel_name=r.channel_name,
            is_dm=r.is_dm,
            starting_sentiment=r.starting_sentiment,
            ending_sentiment=r.ending_sentiment,
            emotional_arc=r.emotional_arc,
            energy_level=r.energy_level,
            topic_summary=r.topic_summary,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )


# ---------------------------------------------------------------------------
# Topic recurrence
# ---------------------------------------------------------------------------

class ExtractTopicsRequest(BaseModel):
    user_id: str
    conversation_text: str
    conversation_sentiment: float = 0.0
    agent_id: str = "default"
    channel_id: str = ""
    channel_name: str = ""
    is_dm: bool = False


class TopicRecurrenceOut(BaseModel):
    topic: str
    topic_type: str
    mention_count: int
    first_mentioned: str
    last_mentioned: str
    sentiment_trend: str
    avg_emotional_weight: str
    pattern_note: str
    channels: list[str]
