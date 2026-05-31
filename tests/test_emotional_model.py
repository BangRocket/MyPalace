"""Schema-shape assertions for the EmotionalContext table."""
from __future__ import annotations

from mypalace.models import EmotionalContext


def test_tablename():
    assert EmotionalContext.__tablename__ == "emotional_contexts"


def test_columns_present():
    cols = set(EmotionalContext.__table__.columns.keys())
    assert {
        "id", "tenant_id", "user_id", "agent_id", "channel_id", "channel_name",
        "is_dm", "starting_sentiment", "ending_sentiment", "emotional_arc",
        "energy_level", "topic_summary", "created_at",
    } <= cols


def test_recurrence_index_exists():
    names = {ix.name for ix in EmotionalContext.__table__.indexes}
    assert "ix_emotional_contexts_tenant_user_created" in names
