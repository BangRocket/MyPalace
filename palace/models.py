"""Database models for Palace Memory Service."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts_column(*, nullable: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable)


class Memory(SQLModel, table=True):
    """A stored memory — fact, preference, episode, etc."""

    __tablename__ = "memories"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
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
    metadata_json: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class Session(SQLModel, table=True):
    """A conversation session."""

    __tablename__ = "sessions"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
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
    session_id: str = Field(foreign_key="sessions.id", index=True)
    user_id: str = Field(index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class NarrativeArc(SQLModel, table=True):
    """A narrative arc rolling up multiple Episodes into a storyline."""

    __tablename__ = "narrative_arcs"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
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
