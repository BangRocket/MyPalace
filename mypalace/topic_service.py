"""Topic-recurrence service — LLM topic extraction + recurrence aggregation.

Source: mypalclara/core/memory/context/topics.py. Topic extraction is an LLM
call run via the worker queue; recurrence patterns are computed server-side by
aggregating TopicMention rows over a lookback window.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from mypalace.database import async_session
from mypalace.llm import llm
from mypalace.models import DEFAULT_TENANT_ID, TopicMention, utcnow
from mypalace.prompts.topics import TOPIC_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"
_WEIGHT_ORDER = {"light": 1, "moderate": 2, "heavy": 3}
_VALID_WEIGHTS = {"light", "moderate", "heavy"}
_VALID_TYPES = {"entity", "theme"}


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Fall back to the first {...} block (the prompt may add prose).
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("topic LLM non-JSON response: %.200s", text)
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_topics(raw_topics: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in raw_topics:
        name = (t.get("topic", "") or "").strip().lower()
        if not name or len(name) < 2:
            continue
        topic_type = t.get("topic_type", "theme")
        if topic_type not in _VALID_TYPES:
            topic_type = "theme"
        weight = t.get("emotional_weight", "moderate")
        if weight not in _VALID_WEIGHTS:
            weight = "moderate"
        out.append(
            {
                "topic": name,
                "topic_type": topic_type,
                "context_snippet": (t.get("context_snippet", "") or "")[:100],
                "emotional_weight": weight,
            }
        )
    return out


def _dedupe_topics(topics: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in topics:
        name = t["topic"]
        if name not in seen:
            seen[name] = t
            continue
        if _WEIGHT_ORDER.get(t["emotional_weight"], 0) > _WEIGHT_ORDER.get(
            seen[name]["emotional_weight"],
            0,
        ):
            seen[name] = t
    return list(seen.values())


def compute_topic_pattern(mentions: list[dict]) -> dict:
    """Analyze recurrence for one topic's mentions. Ported from mypalclara."""
    if not mentions:
        return {
            "mention_count": 0,
            "sentiment_trend": "stable",
            "avg_emotional_weight": "light",
            "pattern_note": "",
        }
    count = len(mentions)
    sentiments = [m.get("sentiment", 0.0) for m in mentions]
    if len(sentiments) >= 2 and sentiments[-1] - sentiments[0] < -0.2:
        trend = "declining"
    elif len(sentiments) >= 2 and sentiments[-1] - sentiments[0] > 0.2:
        trend = "improving"
    else:
        trend = "stable"
    weight_scores = [_WEIGHT_ORDER.get(m.get("emotional_weight", "moderate"), 2) for m in mentions]
    avg = sum(weight_scores) / len(weight_scores)
    avg_weight = "heavy" if avg >= 2.5 else "moderate" if avg >= 1.5 else "light"
    weight_increasing = len(weight_scores) >= 2 and weight_scores[-1] > weight_scores[0]
    if count >= 3 and (trend == "declining" or weight_increasing):
        note = f"brought up {count} times, getting heavier"
    elif count >= 3 and avg_weight == "heavy":
        note = f"recurring concern ({count} mentions)"
    elif count >= 2:
        note = f"mentioned {count} times recently"
    else:
        note = "mentioned recently"
    return {
        "mention_count": count,
        "sentiment_trend": trend,
        "avg_emotional_weight": avg_weight,
        "pattern_note": note,
    }


def _format_relative_time(ts: datetime | None) -> str:
    if ts is None:
        return ""
    delta = utcnow() - ts
    if delta.days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            minutes = delta.seconds // 60
            return f"{minutes}m ago" if minutes > 0 else "just now"
        return f"{hours}h ago"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    weeks = delta.days // 7
    return f"{weeks} week{'s' if weeks > 1 else ''} ago"


class TopicService:
    async def extract_and_store(
        self,
        *,
        user_id: str,
        conversation_text: str,
        conversation_sentiment: float = 0.0,
        agent_id: str = DEFAULT_AGENT_ID,
        channel_id: str = "",
        channel_name: str = "",
        is_dm: bool = False,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[TopicMention]:
        if not conversation_text or len(conversation_text.strip()) < 50:
            return []
        prompt = TOPIC_EXTRACTION_PROMPT.format(
            conversation=conversation_text[:4000],
            sentiment=conversation_sentiment,
        )
        try:
            raw = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
        except Exception:
            logger.exception("topic extraction LLM call failed")
            return []
        data = _parse_llm_json(raw) or {}
        topics = _dedupe_topics(_validate_topics(data.get("topics", [])))[:3]
        if not topics:
            return []
        now = utcnow()
        rows = [
            TopicMention(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                topic=t["topic"],
                topic_type=t["topic_type"],
                context_snippet=t["context_snippet"],
                emotional_weight=t["emotional_weight"],
                sentiment=conversation_sentiment,
                channel_id=channel_id,
                channel_name=channel_name,
                is_dm=is_dm,
                created_at=now,
            )
            for t in topics
        ]
        async with async_session() as db:
            for row in rows:
                db.add(row)
            await db.commit()
            for row in rows:
                await db.refresh(row)
        logger.info(
            "topic mentions stored tenant=%s user=%s count=%d",
            tenant_id,
            user_id,
            len(rows),
        )
        return rows

    async def get_recurrence(
        self,
        *,
        user_id: str,
        agent_id: str = DEFAULT_AGENT_ID,
        lookback_days: int = 14,
        min_mentions: int = 2,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        cutoff = utcnow() - timedelta(days=lookback_days)
        async with async_session() as db:
            result = await db.execute(
                select(TopicMention)
                .where(TopicMention.tenant_id == tenant_id)
                .where(TopicMention.user_id == user_id)
                .where(TopicMention.agent_id == agent_id)
                .where(TopicMention.created_at >= cutoff)
                .order_by(TopicMention.created_at),
            )
            rows = list(result.scalars().all())

        groups: dict[str, list[TopicMention]] = defaultdict(list)
        for r in rows:
            groups[r.topic].append(r)

        recurring: list[dict] = []
        for topic, items in groups.items():
            if len(items) < min_mentions:
                continue
            items.sort(key=lambda x: x.created_at)
            mention_dicts = [
                {"sentiment": i.sentiment, "emotional_weight": i.emotional_weight} for i in items
            ]
            pattern = compute_topic_pattern(mention_dicts)
            types = [i.topic_type for i in items]
            channels = sorted({i.channel_name for i in items if i.channel_name})
            recurring.append(
                {
                    "topic": topic,
                    "topic_type": max(set(types), key=types.count),
                    "mention_count": pattern["mention_count"],
                    "first_mentioned": _format_relative_time(items[0].created_at),
                    "last_mentioned": _format_relative_time(items[-1].created_at),
                    "sentiment_trend": pattern["sentiment_trend"],
                    "avg_emotional_weight": pattern["avg_emotional_weight"],
                    "pattern_note": pattern["pattern_note"],
                    "channels": channels,
                }
            )
        recurring.sort(key=lambda x: x["mention_count"], reverse=True)
        return recurring


topic_service = TopicService()
