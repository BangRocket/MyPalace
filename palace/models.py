"""Database models for Palace Memory Service."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    accessed_at: datetime | None = None
    access_count: int = Field(default=0)
    metadata_json: str | None = None


class Session(SQLModel, table=True):
    """A conversation session."""

    __tablename__ = "sessions"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    user_id: str = Field(index=True)
    title: str | None = None
    summary: str | None = None
    context_snapshot: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    """A message within a session."""

    __tablename__ = "messages"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    session_id: str = Field(foreign_key="sessions.id", index=True)
    user_id: str = Field(index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)
