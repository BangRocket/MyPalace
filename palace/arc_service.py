"""Narrative arc storage + LLM-driven synthesis."""

from __future__ import annotations

import json

from sqlalchemy import select

from palace._llm_utils import strip_json_fences
from palace.database import async_session
from palace.episode_service import episode_service
from palace.llm import llm
from palace.models import NarrativeArc, utcnow
from palace.prompts.synthesis import NARRATIVE_SYNTHESIS_PROMPT


class ArcService:
    """Business logic for narrative arcs."""

    async def get_active(
        self, user_id: str, limit: int = 10,
    ) -> list[NarrativeArc]:
        """Active arcs for a user, most-recently-updated first."""
        async with async_session() as db:
            from sqlalchemy import desc as sa_desc
            stmt = (
                select(NarrativeArc)
                .where(NarrativeArc.user_id == user_id)
                .where(NarrativeArc.status == "active")
                .order_by(sa_desc(NarrativeArc.updated_at))
                .limit(limit)
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def get(self, arc_id: str) -> NarrativeArc | None:
        async with async_session() as db:
            result = await db.execute(select(NarrativeArc).where(NarrativeArc.id == arc_id))
            return result.scalar_one_or_none()

    async def create(self, **fields) -> NarrativeArc:
        async with async_session() as db:
            arc = NarrativeArc(**fields)
            db.add(arc)
            await db.commit()
            await db.refresh(arc)
            return arc

    async def update(self, arc_id: str, **fields) -> NarrativeArc | None:
        async with async_session() as db:
            result = await db.execute(select(NarrativeArc).where(NarrativeArc.id == arc_id))
            arc = result.scalar_one_or_none()
            if not arc:
                return None
            for k, v in fields.items():
                setattr(arc, k, v)
            arc.updated_at = utcnow()
            await db.commit()
            await db.refresh(arc)
            return arc

    async def synthesize_narratives(
        self,
        user_id: str,
        agent_id: str | None = None,
        lookback_episodes: int = 20,
    ) -> list[NarrativeArc]:
        """Call the LLM with recent episodes + active arcs, parse arcs from
        the response, create new arcs or update existing ones.

        Raises ValueError if the LLM returns malformed JSON."""
        recent_episodes = await episode_service.get_recent(
            user_id=user_id, limit=lookback_episodes,
        )
        existing_arcs = await self.get_active(user_id=user_id)

        episodes_text = "\n".join(
            f"[{e.get('id')}] ({e.get('timestamp', '')}) {e.get('summary', '')}"
            for e in recent_episodes
        ) or "(none)"
        existing_arcs_text = "\n".join(
            f"[{a.id}] {a.title}: {a.summary} (status={a.status})"
            for a in existing_arcs
        ) or "(none)"

        prompt = NARRATIVE_SYNTHESIS_PROMPT.format(
            episodes_text=episodes_text,
            existing_arcs_text=existing_arcs_text,
        )

        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        try:
            parsed = json.loads(strip_json_fences(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned non-JSON for synthesis: {e}") from e

        extracted = parsed.get("arcs", [])
        if not isinstance(extracted, list):
            raise ValueError(f"LLM returned non-list 'arcs' field: {type(extracted).__name__}")

        results: list[NarrativeArc] = []
        for raw_arc in extracted:
            existing_id = raw_arc.get("existing_id")
            fields = {
                "title": raw_arc.get("title", ""),
                "summary": raw_arc.get("summary", ""),
                "status": raw_arc.get("status", "active"),
                "key_episode_ids": raw_arc.get("key_episode_ids", []),
                "emotional_trajectory": raw_arc.get("emotional_trajectory", ""),
            }
            if existing_id:
                arc = await self.update(existing_id, **fields)
                if arc:
                    results.append(arc)
            else:
                arc = await self.create(
                    user_id=user_id, agent_id=agent_id, **fields,
                )
                results.append(arc)
        return results


# Singleton
arc_service = ArcService()
