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
