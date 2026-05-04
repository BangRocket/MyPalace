"""IntentionService — DB-touching wrapper around trigger evaluation.

Mirrors mypalclara's IntentionManager facade. All methods are async and use
``async_session`` from ``palace.database``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select

from palace.database import async_session
from palace.intentions.triggers import evaluate_trigger
from palace.models import DEFAULT_TENANT_ID, Intention, utcnow


def _now_naive() -> datetime:
    """Trigger matchers use naive UTC for time comparisons."""
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class IntentionService:
    """Intention service. All methods async; use async_session."""

    async def set(
        self,
        user_id: str,
        content: str,
        trigger_conditions: dict,
        agent_id: str = "clara",
        expires_at: datetime | None = None,
        source_memory_id: str | None = None,
        priority: int = 0,
        fire_once: bool = True,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Intention:
        async with async_session() as db:
            intention = Intention(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                content=content,
                trigger_conditions=trigger_conditions,
                priority=priority,
                fire_once=fire_once,
                expires_at=expires_at,
                source_memory_id=source_memory_id,
            )
            db.add(intention)
            await db.commit()
            await db.refresh(intention)
            return intention

    async def check(
        self,
        user_id: str,
        message: str,
        context: dict | None = None,
        agent_id: str = "clara",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        """Evaluate all unfired+unexpired intentions and return fired matches.

        Marks fired intentions as fired/fired_at; deletes any with
        ``fire_once=True``. Returns dicts sorted by priority (highest first).
        """
        async with async_session() as db:
            now_naive = _now_naive()
            result = await db.execute(
                select(Intention).where(
                    Intention.user_id == user_id,
                    Intention.agent_id == agent_id,
                    Intention.tenant_id == tenant_id,
                    Intention.fired == False,  # noqa: E712
                ),
            )
            all_intentions = result.scalars().all()

            # Filter expired (TZ-aware DB column → naive for comparison).
            intentions = [
                i for i in all_intentions
                if i.expires_at is None or _to_naive(i.expires_at) > now_naive
            ]

            if not intentions:
                return []

            fired: list[dict] = []
            for intention in intentions:
                should_fire, match_details = evaluate_trigger(
                    message=message,
                    trigger_conditions=intention.trigger_conditions,
                    context=context,
                    now=now_naive,
                )
                if not should_fire:
                    continue

                trigger_type = intention.trigger_conditions.get("type", "keyword")
                fired.append(
                    {
                        "id": intention.id,
                        "content": intention.content,
                        "trigger_type": trigger_type,
                        "priority": intention.priority,
                        "match_details": match_details,
                        "source_memory_id": intention.source_memory_id,
                    },
                )

                # Mark fired; delete if fire_once.
                intention.fired = True
                intention.fired_at = utcnow()
                if intention.fire_once:
                    await db.delete(intention)

            await db.commit()

            fired.sort(key=lambda x: x["priority"], reverse=True)
            return fired

    def format_for_prompt(
        self,
        fired_intentions: list[dict],
        max_intentions: int = 3,
    ) -> str:
        """Render fired intentions as a markdown bullet list for prompt
        injection. Returns empty string if no intentions."""
        if not fired_intentions:
            return ""

        lines = ["## Reminders"]
        for intention in fired_intentions[:max_intentions]:
            lines.append(f"- {intention['content']}")
        return "\n".join(lines)

    async def list_for_user(
        self,
        user_id: str,
        fired_filter: str = "all",
        limit: int = 50,
        agent_id: str = "clara",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[Intention]:
        """List intentions for a user. ``fired_filter`` is "true" / "false" /
        "all"."""
        async with async_session() as db:
            stmt = select(Intention).where(
                Intention.user_id == user_id,
                Intention.agent_id == agent_id,
                Intention.tenant_id == tenant_id,
            )
            if fired_filter == "true":
                stmt = stmt.where(Intention.fired == True)  # noqa: E712
            elif fired_filter == "false":
                stmt = stmt.where(Intention.fired == False)  # noqa: E712

            stmt = stmt.order_by(Intention.priority.desc()).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def delete(
        self,
        intention_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> bool:
        async with async_session() as db:
            result = await db.execute(
                select(Intention).where(
                    Intention.id == intention_id,
                    Intention.tenant_id == tenant_id,
                ),
            )
            intention = result.scalar_one_or_none()
            if intention is None:
                return False
            await db.delete(intention)
            await db.commit()
            return True

    async def cleanup_expired(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> int:
        """Delete all intentions whose expires_at is in the past. Returns
        deleted count."""
        async with async_session() as db:
            now = datetime.now(UTC)
            stmt = delete(Intention).where(
                Intention.expires_at.isnot(None),
                Intention.expires_at < now,
                Intention.tenant_id == tenant_id,
            )
            result = await db.execute(stmt)
            await db.commit()
            return int(result.rowcount or 0)


# Singleton — matches the slice 1/2/3 service pattern.
intention_service = IntentionService()
