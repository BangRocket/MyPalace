"""Deterministic trigger matchers for intentions (slice 4).

Ported character-for-character from
mypalclara/mypalclara/core/intentions.py — the four matcher functions plus a
dispatch helper. **No LLM.** Topic matching uses simple word-overlap as the
fallback (mypalclara's import-fallback path; we never go through the
sentence-transformers path).

Trigger schemas (all dicts):

- keyword: ``{"type": "keyword", "keywords": [...], "regex": ?, "case_sensitive": ?}``
- topic:   ``{"type": "topic", "topic": str, "threshold": float, "quick_keywords": [...]}``
- time:    ``{"type": "time", "at": ISO|null, "after": ISO|null}``
- context: ``{"type": "context", "conditions": {channel_name|is_dm|time_of_day|day_of_week}}``
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum


class TriggerType(StrEnum):
    """Types of intention triggers."""

    KEYWORD = "keyword"
    TOPIC = "topic"
    TIME = "time"
    CONTEXT = "context"


def _check_keyword_trigger(
    message: str,
    conditions: dict,
) -> tuple[bool, dict]:
    """Check if message contains trigger keywords.

    Supports a simple keyword list, optional case-sensitive matching, and an
    optional regex pattern. Returns (should_fire, match_details).
    """
    keywords = conditions.get("keywords", [])
    regex_pattern = conditions.get("regex")
    case_sensitive = conditions.get("case_sensitive", False)

    message_check = message if case_sensitive else message.lower()
    matched_keywords = []

    for keyword in keywords:
        keyword_check = keyword if case_sensitive else keyword.lower()
        if keyword_check in message_check:
            matched_keywords.append(keyword)

    if regex_pattern:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(regex_pattern, message, flags):
            matched_keywords.append(f"regex:{regex_pattern}")

    if matched_keywords:
        return True, {"matched_keywords": matched_keywords}
    return False, {}


def _check_topic_trigger(
    message: str,
    conditions: dict,
) -> tuple[bool, dict]:
    """Check if message overlaps with a topic by word-set intersection.

    mypalclara has an LLM-similarity path gated behind a sentence-transformers
    import; we always take the keyword fallback (no LLM in slice 4).
    """
    topic = conditions.get("topic", "")
    threshold = conditions.get("threshold", 0.7)

    if not topic:
        return False, {}

    topic_words = set(topic.lower().split())
    message_words = set(message.lower().split())
    overlap = len(topic_words & message_words) / max(len(topic_words), 1)

    if overlap >= threshold:
        return True, {"topic": topic, "similarity": overlap}

    return False, {}


def _check_time_trigger(
    now: datetime,
    conditions: dict,
) -> tuple[bool, dict]:
    """Check if current time has reached the trigger time.

    Supports ``at`` (specific datetime) and ``after`` (fire-after datetime).
    Both compared in naive UTC.
    """
    trigger_at = conditions.get("at")
    trigger_after = conditions.get("after")

    if trigger_at:
        try:
            target_time = datetime.fromisoformat(trigger_at.replace("Z", "+00:00"))
            target_time = target_time.replace(tzinfo=None)
            if now >= target_time:
                return True, {"trigger_time": trigger_at, "type": "at"}
        except (ValueError, TypeError):
            pass

    if trigger_after:
        try:
            target_time = datetime.fromisoformat(trigger_after.replace("Z", "+00:00"))
            target_time = target_time.replace(tzinfo=None)
            if now >= target_time:
                return True, {"trigger_time": trigger_after, "type": "after"}
        except (ValueError, TypeError):
            pass

    return False, {}


def _check_context_trigger(
    context: dict,
    conditions: dict,
) -> tuple[bool, dict]:
    """Check if current context matches all configured conditions.

    Supported keys: channel_name (substring, case-insensitive), is_dm (exact),
    time_of_day (morning/afternoon/evening/night, evaluated against UTC now),
    day_of_week (full lowercase weekday name, evaluated against UTC now).
    """
    match_conditions = conditions.get("conditions", {})
    if not match_conditions:
        return False, {}

    matched = {}

    if "channel_name" in match_conditions:
        expected = match_conditions["channel_name"].lower()
        actual = context.get("channel_name", "").lower()
        if expected not in actual:
            return False, {}
        matched["channel_name"] = actual

    if "is_dm" in match_conditions:
        expected = match_conditions["is_dm"]
        actual = context.get("is_dm", False)
        if expected != actual:
            return False, {}
        matched["is_dm"] = actual

    if "time_of_day" in match_conditions:
        expected = match_conditions["time_of_day"].lower()
        now = datetime.now(UTC)
        hour = now.hour

        time_periods = {
            "morning": (6, 12),
            "afternoon": (12, 17),
            "evening": (17, 21),
            "night": (21, 6),
        }

        if expected in time_periods:
            start, end = time_periods[expected]
            # Night wraps around midnight; the others are simple half-open ranges.
            in_period = (
                (hour >= start or hour < end)
                if expected == "night"
                else (start <= hour < end)
            )

            if not in_period:
                return False, {}
            matched["time_of_day"] = expected

    if "day_of_week" in match_conditions:
        expected = match_conditions["day_of_week"].lower()
        now = datetime.now(UTC)
        actual = now.strftime("%A").lower()
        if expected != actual:
            return False, {}
        matched["day_of_week"] = actual

    if matched:
        return True, {"matched_conditions": matched}

    return False, {}


def evaluate_trigger(
    message: str,
    trigger_conditions: dict,
    context: dict | None = None,
    now: datetime | None = None,
) -> tuple[bool, dict]:
    """Dispatch to the right matcher based on trigger_conditions['type'].

    Defaults to keyword if type is missing (mypalclara compatibility).
    """
    context = context or {}
    trigger_type = trigger_conditions.get("type", TriggerType.KEYWORD.value)
    if now is None:
        now = datetime.now(UTC).replace(tzinfo=None)

    if trigger_type == TriggerType.KEYWORD.value:
        return _check_keyword_trigger(message, trigger_conditions)
    if trigger_type == TriggerType.TOPIC.value:
        # Quick keyword pre-filter (mypalclara's TIERED strategy behaviour).
        keywords = trigger_conditions.get("quick_keywords", [])
        if keywords and not any(kw.lower() in message.lower() for kw in keywords):
            return False, {}
        return _check_topic_trigger(message, trigger_conditions)
    if trigger_type == TriggerType.TIME.value:
        return _check_time_trigger(now, trigger_conditions)
    if trigger_type == TriggerType.CONTEXT.value:
        return _check_context_trigger(context, trigger_conditions)

    return False, {}
