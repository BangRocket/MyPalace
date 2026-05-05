"""Database models for Palace Memory Service."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts_column(*, nullable: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable)


DEFAULT_TENANT_ID = "default"


class Tenant(SQLModel, table=True):
    """A tenant: hard data-isolation boundary (phase 3 slice 2)."""

    __tablename__ = "tenants"

    id: str = Field(primary_key=True, max_length=32)
    label: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    metadata_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class Memory(SQLModel, table=True):
    """A stored memory — fact, preference, episode, etc."""

    __tablename__ = "memories"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    content: str
    memory_type: str = Field(default="semantic", index=True)
    source: str | None = None
    importance: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    accessed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    access_count: int = Field(default=0)
    # Phase 6 slice 3: optional TTL. Null = never expires (backwards compat).
    expires_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    metadata_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class Session(SQLModel, table=True):
    """A conversation session."""

    __tablename__ = "sessions"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    title: str | None = None
    summary: str | None = None
    context_snapshot: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class Message(SQLModel, table=True):
    """A message within a session."""

    __tablename__ = "messages"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    user_id: str = Field(index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class NarrativeArc(SQLModel, table=True):
    """A narrative arc rolling up multiple Episodes into a storyline."""

    __tablename__ = "narrative_arcs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    title: str
    summary: str
    status: str = Field(default="active", index=True)  # active | resolved | dormant
    key_episode_ids: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    emotional_trajectory: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class ReflectionJob(SQLModel, table=True):
    """Tracks status of background reflection/synthesis jobs."""

    __tablename__ = "reflection_jobs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    kind: str = Field(index=True)  # "reflection" | "synthesis"
    user_id: str = Field(index=True)
    status: str = Field(default="pending", index=True)  # pending | completed | failed
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    completed_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    result_json: list | dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    error: str | None = None
    # Phase 4 slice 3: worker lease + retry tracking.
    leased_until: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    attempts: int = Field(default=0)
    payload_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class MemoryDynamics(SQLModel, table=True):
    """FSRS-6 scheduling state for a memory (slice 3)."""

    __tablename__ = "memory_dynamics"
    __table_args__ = (
        Index("ix_memory_dynamics_user_accessed", "user_id", "last_accessed_at"),
    )

    memory_id: str = Field(primary_key=True)
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    stability: float = Field(default=1.0)
    difficulty: float = Field(default=5.0)
    retrieval_strength: float = Field(default=1.0)
    storage_strength: float = Field(default=0.5)
    is_key: bool = Field(default=False)
    importance_weight: float = Field(default=1.0)
    category: str | None = Field(default=None, max_length=50)
    tags: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    last_accessed_at: datetime | None = Field(
        default=None, sa_column=_ts_column(nullable=True),
    )
    access_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class Intention(SQLModel, table=True):
    """Future trigger/reminder for proactive memory surfacing (slice 4)."""

    __tablename__ = "intentions"
    __table_args__ = (
        Index("ix_intention_user_unfired", "user_id", "fired"),
        Index("ix_intention_expires", "expires_at"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    agent_id: str = Field(default="clara")
    content: str
    source_memory_id: str | None = None
    trigger_conditions: dict = Field(sa_column=Column(JSONB, nullable=False))
    priority: int = Field(default=0)
    fired: bool = Field(default=False)
    fire_once: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    expires_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    fired_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))


class MemoryAccessLog(SQLModel, table=True):
    """Audit trail of memory accesses with FSRS grade (slice 3)."""

    __tablename__ = "memory_access_logs"
    __table_args__ = (
        Index("ix_memory_access_logs_user_accessed", "user_id", "accessed_at"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    memory_id: str = Field(
        sa_column=Column(
            ForeignKey("memory_dynamics.memory_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: str = Field(index=True)
    grade: int
    signal_type: str
    retrievability_at_access: float
    context: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    accessed_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class ApiKey(SQLModel, table=True):
    """API key for service-to-service auth (phase 3 slice 1)."""

    __tablename__ = "api_keys"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    key_prefix: str = Field(index=True, unique=True, max_length=8)
    key_hash: str = Field(max_length=100)
    label: str = Field(max_length=100)
    tenant_id: str | None = Field(default=None, index=True, max_length=32)
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    last_used_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))
    revoked_at: datetime | None = Field(default=None, sa_column=_ts_column(nullable=True))


class MemoryVersion(SQLModel, table=True):
    """Append-only history of memory content changes (phase 7 slice 2).

    Recorded by memory_service on create / update / supersede. The initial
    `created` row makes the trail complete from row 1 — no special-case
    "memory exists but has no versions" state.
    """

    __tablename__ = "memory_versions"
    __table_args__ = (
        Index("ix_memory_versions_memory_created", "memory_id", "created_at"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    memory_id: str = Field(index=True)
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    user_id: str = Field(index=True)
    version_number: int = Field(default=1)
    content: str
    metadata_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    change_kind: str = Field(max_length=20)  # created | updated | superseded
    actor_key_id: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class AuditLog(SQLModel, table=True):
    """Append-only audit trail of /v1/admin/* and /v1/maintenance/* calls
    (phase 7 slice 1). Recorded by AuditMiddleware, fire-and-forget, post-auth.

    Body content is hashed (SHA256), not stored — audit answers
    "did this happen" without leaking secrets like bootstrap key plaintext.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_key_created", "key_id", "created_at"),
        Index("ix_audit_logs_path_created", "path", "created_at"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    key_id: str = Field(index=True)
    tenant_id: str | None = Field(default=None, index=True, max_length=32)
    method: str = Field(max_length=10)
    path: str = Field(max_length=500)
    status_class: str = Field(max_length=4)
    request_body_hash: str | None = Field(default=None, max_length=64)
    response_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class PersonalityTrait(SQLModel, table=True):
    """Self-evolving agent personality trait (phase 10 slice 2).

    Source mypalclara/db/models.py:PersonalityTrait. Soft-deleted via
    ``active`` so history is preserved without a separate table — the
    audit log already covers who/when on the API surface.
    """

    __tablename__ = "personality_traits"
    __table_args__ = (
        Index(
            "ix_personality_traits_tenant_agent_active",
            "tenant_id", "agent_id", "active",
        ),
        Index(
            "ix_personality_traits_tenant_agent_category",
            "tenant_id", "agent_id", "category",
        ),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, max_length=32)
    agent_id: str = Field(default="default", max_length=64)
    category: str = Field(max_length=50)
    trait_key: str = Field(max_length=100)
    content: str
    source: str = Field(default="self", max_length=20)
    reason: str | None = None
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class EntityAlias(SQLModel, table=True):
    """Maps platform-prefixed identifiers to human-readable names.

    Source mypalclara/core/memory/entity_resolver.py. Used by graph node
    labelling so the knowledge graph shows "Josh" instead of
    "discord-271274659385835521".
    """

    __tablename__ = "entity_aliases"
    __table_args__ = (
        Index(
            "uq_entity_aliases_tenant_identifier",
            "tenant_id", "identifier", unique=True,
        ),
        Index("ix_entity_aliases_tenant_canonical", "tenant_id", "canonical_name"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, max_length=32)
    identifier: str = Field(max_length=200)
    canonical_name: str = Field(max_length=200)
    source: str = Field(default="manual", max_length=20)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class MemorySupersession(SQLModel, table=True):
    """Audit log linking a superseded memory to its replacement (slice 5).

    Not a hard FK because memories may be deleted; this is an append-only
    audit log of memory replacement decisions (manual or auto via the
    smart-ingestion contradiction heuristic).
    """

    __tablename__ = "memory_supersessions"
    __table_args__ = (
        Index("ix_supersession_superseded", "superseded_id"),
        Index("ix_supersession_new", "new_id"),
    )

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    tenant_id: str = Field(default=DEFAULT_TENANT_ID, index=True, max_length=32)
    superseded_id: str
    new_id: str
    user_id: str = Field(index=True)
    reason: str
    similarity_score: float | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
