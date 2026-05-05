"""Personality evolution service (phase 10 slice 2).

Source: mypalclara/core/personality.py + mypalclara/core/memory/personality.py.

Maintains a per-(tenant, agent) registry of self-evolving traits. The
LLM-driven evaluator runs out-of-band via the worker queue (kind:
``personality_evolve``) so the user-facing ingestion path never blocks
on a personality decision.

Soft-delete via ``active=False`` keeps history without a separate table.
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

from sqlalchemy import select

from mypalace.config import settings
from mypalace.database import async_session
from mypalace.llm import llm
from mypalace.models import DEFAULT_TENANT_ID, PersonalityTrait, utcnow

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"

EVOLUTION_PROMPT = """\
You are evaluating whether a conversation exchange reveals something meaningful \
about your personality that should be recorded as an evolved trait.

Your current personality traits:
{traits}

The conversation:
User: {user_message}
You: {assistant_reply}

Based on this exchange, decide if your personality should evolve. Only evolve when you notice:
- A genuine pattern in how you communicate or think (not a one-off)
- A new interest or perspective developed through conversation
- A refinement in how you express yourself
- A value or boundary becoming clearer

Do NOT evolve for:
- Single requests to "be more X"
- Temporary moods or context
- Trivial or routine exchanges
- Things that contradict existing traits (update the existing trait instead)

Valid categories: interests, communication_style, values, skills, quirks, boundaries, preferences

Respond with ONLY valid JSON (no markdown, no explanation):
- If no evolution needed: {{"evolve": false}}
- If adding a new trait: {{"evolve": true, "action": "add", "category": "...", "trait_key": "...", \
"content": "...", "reason": "..."}}
- If updating an existing trait: {{"evolve": true, "action": "update", "trait_id": "...", \
"content": "...", "reason": "..."}}
- If removing a trait: {{"evolve": true, "action": "remove", "trait_id": "...", "reason": "..."}}\
"""


def _format_traits_for_prompt(traits: list[PersonalityTrait]) -> str:
    if not traits:
        return "No evolved traits yet."
    by_cat: dict[str, list[str]] = {}
    for t in traits:
        by_cat.setdefault(t.category, []).append(
            f"  - [{t.category}/{t.trait_key}] id={t.id}: {t.content}",
        )
    blocks = []
    for cat in sorted(by_cat):
        blocks.append("\n".join(by_cat[cat]))
    return "\n".join(blocks)


class PersonalityService:
    """Async CRUD for personality traits + LLM-driven evolution evaluator.

    Intentionally has no in-memory cache — traits are read in the prompt-
    assembly hot path elsewhere (callers can layer their own cache).
    Worker job handler calls evaluate_and_apply() to evolve.
    """

    async def list_active(
        self,
        agent_id: str = DEFAULT_AGENT_ID,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[PersonalityTrait]:
        async with async_session() as db:
            result = await db.execute(
                select(PersonalityTrait)
                .where(PersonalityTrait.tenant_id == tenant_id)
                .where(PersonalityTrait.agent_id == agent_id)
                .where(PersonalityTrait.active.is_(True))
                .order_by(PersonalityTrait.category, PersonalityTrait.trait_key),
            )
            return list(result.scalars().all())

    async def get(self, trait_id: str) -> PersonalityTrait | None:
        async with async_session() as db:
            result = await db.execute(
                select(PersonalityTrait).where(PersonalityTrait.id == trait_id),
            )
            return result.scalar_one_or_none()

    async def add(
        self,
        category: str,
        trait_key: str,
        content: str,
        agent_id: str = DEFAULT_AGENT_ID,
        tenant_id: str = DEFAULT_TENANT_ID,
        source: str = "self",
        reason: str | None = None,
    ) -> PersonalityTrait:
        now = utcnow()
        async with async_session() as db:
            row = PersonalityTrait(
                tenant_id=tenant_id,
                agent_id=agent_id,
                category=category,
                trait_key=trait_key,
                content=content,
                source=source,
                reason=reason,
                active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        logger.info(
            "personality trait added tenant=%s agent=%s category=%s trait_key=%s id=%s",
            tenant_id, agent_id, category, trait_key, row.id,
        )
        return row

    async def update(
        self, trait_id: str, content: str,
        reason: str | None = None, source: str = "self",
    ) -> PersonalityTrait:
        async with async_session() as db:
            result = await db.execute(
                select(PersonalityTrait).where(PersonalityTrait.id == trait_id),
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"trait not found: {trait_id}")
            row.content = content
            row.reason = reason
            row.source = source
            row.updated_at = utcnow()
            await db.commit()
            await db.refresh(row)
        logger.info("personality trait updated id=%s", trait_id)
        return row

    async def remove(
        self, trait_id: str, reason: str | None = None, source: str = "self",
    ) -> bool:
        """Soft-delete: mark inactive. Returns True if a row was changed."""
        async with async_session() as db:
            result = await db.execute(
                select(PersonalityTrait).where(PersonalityTrait.id == trait_id),
            )
            row = result.scalar_one_or_none()
            if row is None or not row.active:
                return False
            row.active = False
            row.reason = reason
            row.source = source
            row.updated_at = utcnow()
            await db.commit()
        logger.info("personality trait removed id=%s", trait_id)
        return True

    async def evaluate_and_apply(
        self,
        user_message: str,
        assistant_reply: str,
        agent_id: str = DEFAULT_AGENT_ID,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict[str, Any]:
        """Run the LLM evaluator and apply any returned action.

        Returns the parsed decision dict (with an ``applied`` boolean
        added) — the worker handler stores it in ``result_json`` so
        operators can inspect what the LLM decided.
        """
        traits = await self.list_active(agent_id=agent_id, tenant_id=tenant_id)
        prompt = EVOLUTION_PROMPT.format(
            traits=_format_traits_for_prompt(traits),
            user_message=user_message[:2000],
            assistant_reply=assistant_reply[:2000],
        )
        try:
            raw = await llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
        except Exception:
            logger.exception("personality evolution LLM call failed")
            return {"evolve": False, "applied": False, "error": "llm_failed"}

        decision = _parse_llm_json(raw) or {"evolve": False}
        if not decision.get("evolve"):
            return {**decision, "applied": False}

        action = decision.get("action")
        try:
            if action == "add":
                await self.add(
                    category=decision["category"],
                    trait_key=decision["trait_key"],
                    content=decision["content"],
                    reason=decision.get("reason"),
                    source="evolution",
                    agent_id=agent_id, tenant_id=tenant_id,
                )
            elif action == "update":
                await self.update(
                    trait_id=decision["trait_id"],
                    content=decision["content"],
                    reason=decision.get("reason"),
                    source="evolution",
                )
            elif action == "remove":
                await self.remove(
                    trait_id=decision["trait_id"],
                    reason=decision.get("reason"),
                    source="evolution",
                )
            else:
                logger.warning("personality evolution unknown action: %s", action)
                return {**decision, "applied": False, "error": "unknown_action"}
        except (KeyError, ValueError) as e:
            logger.warning("personality evolution apply failed: %r", e)
            return {**decision, "applied": False, "error": repr(e)}

        return {**decision, "applied": True}


def maybe_enqueue_evolution(
    user_message: str,
    assistant_reply: str,
    user_id: str,
    agent_id: str = DEFAULT_AGENT_ID,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> bool:
    """Probability gate + worker enqueue. Safe to fire-and-forget.

    Returns True iff a job was actually enqueued. Does NOT enqueue when
    chance is 0.0 (the default — feature opt-in via env).
    """
    chance = settings.personality_evolution_chance
    if chance <= 0:
        return False
    if random.random() > chance:  # noqa: S311 — not a security context
        return False
    # Local import to avoid worker-queue cycle at module import time.
    import asyncio

    from mypalace.workers.queue import enqueue

    async def _do():
        try:
            await enqueue(
                kind="personality_evolve",
                user_id=user_id,
                payload={
                    "user_message": user_message,
                    "assistant_reply": assistant_reply,
                    "agent_id": agent_id,
                },
                tenant_id=tenant_id,
            )
        except Exception:
            logger.exception("failed to enqueue personality_evolve job")

    asyncio.create_task(_do())
    return True


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("personality LLM non-JSON response: %.200s", text)
        return None
    if not isinstance(parsed, dict):
        logger.warning("personality LLM JSON not an object: %s", type(parsed).__name__)
        return None
    return parsed


personality_service = PersonalityService()
