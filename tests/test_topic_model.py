"""Schema-shape assertions for the TopicMention table."""
from __future__ import annotations

from mypalace.models import TopicMention


def test_tablename():
    assert TopicMention.__tablename__ == "topic_mentions"


def test_columns_present():
    cols = set(TopicMention.__table__.columns.keys())
    assert {
        "id", "tenant_id", "user_id", "agent_id", "topic", "topic_type",
        "context_snippet", "emotional_weight", "sentiment", "channel_id",
        "channel_name", "is_dm", "created_at",
    } <= cols


def test_recurrence_index_exists():
    names = {ix.name for ix in TopicMention.__table__.indexes}
    assert "ix_topic_mentions_tenant_user_topic_created" in names
