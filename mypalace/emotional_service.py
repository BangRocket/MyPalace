"""Emotional-context service — VADER arc scoring + storage.

Source: mypalclara/core/memory/context/emotional.py. The service scores a
finalized conversation server-side and stores one EmotionalContext row.
"""
from __future__ import annotations

import logging
import statistics
from datetime import timedelta

from sqlalchemy import select

from mypalace._sentiment import compound_score
from mypalace.database import async_session
from mypalace.models import DEFAULT_TENANT_ID, EmotionalContext, utcnow

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"
MIN_MESSAGES_FOR_ARC = 3


def compute_emotional_arc(timeline: list[float]) -> str:
    """Classify a sentiment trajectory. Ported verbatim from mypalclara."""
    if len(timeline) < MIN_MESSAGES_FOR_ARC:
        return "stable"
    start_avg = sum(timeline[:3]) / 3
    end_avg = sum(timeline[-3:]) / 3
    variance = statistics.variance(timeline) if len(timeline) > 1 else 0
    if variance > 0.3:
        return "volatile"
    if end_avg - start_avg > 0.2:
        return "improving"
    if start_avg - end_avg > 0.2:
        return "declining"
    return "stable"


class EmotionalService:
    """Server-side scoring + storage for per-conversation emotional context."""

    async def record(
        self,
        *,
        user_id: str,
        messages: list[str],
        agent_id: str = DEFAULT_AGENT_ID,
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
        energy: str = "neutral",
        summary: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> EmotionalContext:
        timeline = [compound_score(m) for m in messages if m and m.strip()]
        arc = compute_emotional_arc(timeline)
        starting = timeline[0] if timeline else 0.0
        ending = timeline[-1] if timeline else 0.0
        row = EmotionalContext(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            channel_id=channel_id,
            channel_name=channel_name,
            is_dm=is_dm,
            starting_sentiment=starting,
            ending_sentiment=ending,
            emotional_arc=arc,
            energy_level=energy,
            topic_summary=summary,
            created_at=utcnow(),
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
            await db.refresh(row)
        logger.info(
            "emotional context recorded tenant=%s user=%s arc=%s energy=%s",
            tenant_id, user_id, arc, energy,
        )
        return row

    async def get_recent(
        self,
        *,
        user_id: str,
        agent_id: str = DEFAULT_AGENT_ID,
        limit: int = 3,
        max_age_days: int = 7,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[EmotionalContext]:
        cutoff = utcnow() - timedelta(days=max_age_days)
        async with async_session() as db:
            result = await db.execute(
                select(EmotionalContext)
                .where(EmotionalContext.tenant_id == tenant_id)
                .where(EmotionalContext.user_id == user_id)
                .where(EmotionalContext.agent_id == agent_id)
                .where(EmotionalContext.created_at >= cutoff)
                .order_by(EmotionalContext.created_at.desc())
                .limit(limit),
            )
            return list(result.scalars().all())


emotional_service = EmotionalService()
