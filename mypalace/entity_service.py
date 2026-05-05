"""Entity resolver — platform IDs → human-readable names.

Source: mypalclara/core/memory/entity_resolver.py.

Maps identifiers like ``discord-271274659385835521`` to ``Josh`` so
graph node labels and any other display surface render real names.
Per-tenant cache keeps lookups O(1) after first load.

Optional LLM-driven name extraction from a recent conversation transcript
populates the registry without manual intervention.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mypalace.database import async_session
from mypalace.llm import llm
from mypalace.models import DEFAULT_TENANT_ID, EntityAlias, utcnow

logger = logging.getLogger(__name__)

# Platform-prefixed identifier shapes observed in mypalclara + likely
# future surfaces. Stripping the prefix lets a single canonical name
# apply across e.g. discord-123 and slack-abc that point to the same
# human.
_PLATFORM_PREFIX_RE = re.compile(
    r"^(discord|teams|slack|telegram|matrix|signal|whatsapp)-(.+)$",
)

_NAME_EXTRACTION_PROMPT = """\
Given this conversation, identify any real names the user mentions for themselves \
or others.

Return JSON:
{
  "user_name": "Josh" or null,
  "mentioned_people": [
    {"name": "Kinsey", "relationship": "therapist"},
    {"name": "Anne", "relationship": "daughter"}
  ]
}

Only include names you're confident about. Don't guess."""


def strip_platform_prefix(identifier: str) -> str | None:
    """Return the bare id if ``identifier`` carries a platform prefix, else None."""
    match = _PLATFORM_PREFIX_RE.match(identifier)
    return match.group(2) if match else None


class EntityService:
    """Async resolver with per-tenant in-memory cache.

    The cache is loaded lazily on first lookup for a tenant and refreshed
    on every register() call. Cross-process consistency is best-effort —
    multiple workers may briefly serve stale names until the next
    register() round-trips through the DB. That's acceptable: names
    rarely change, and the canonical row is always in Postgres.
    """

    def __init__(self) -> None:
        # tenant_id -> {identifier: canonical_name}
        self._cache: dict[str, dict[str, str]] = {}

    async def _load_tenant(self, tenant_id: str) -> dict[str, str]:
        """Pull every alias for ``tenant_id`` into the cache."""
        async with async_session() as db:
            result = await db.execute(
                select(EntityAlias.identifier, EntityAlias.canonical_name)
                .where(EntityAlias.tenant_id == tenant_id),
            )
            mapping = {row[0]: row[1] for row in result.all()}
        self._cache[tenant_id] = mapping
        return mapping

    async def _ensure_loaded(self, tenant_id: str) -> dict[str, str]:
        cached = self._cache.get(tenant_id)
        if cached is not None:
            return cached
        return await self._load_tenant(tenant_id)

    async def resolve(
        self, identifier: str, tenant_id: str = DEFAULT_TENANT_ID,
    ) -> str:
        """Return canonical name for ``identifier``, or the identifier unchanged.

        Tries the identifier as-is first, then falls back to the bare id
        with any platform prefix stripped (so a single ``Josh`` mapping
        covers ``discord-Josh`` and bare ``Josh`` alike).
        """
        mapping = await self._ensure_loaded(tenant_id)
        if (name := mapping.get(identifier)) is not None:
            return name
        bare = strip_platform_prefix(identifier)
        if bare is not None and (name := mapping.get(bare)) is not None:
            return name
        return identifier

    async def register(
        self,
        identifier: str,
        canonical_name: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        source: str = "manual",
    ) -> EntityAlias:
        """Upsert (tenant_id, identifier) → canonical_name."""
        now = utcnow()
        async with async_session() as db:
            stmt = pg_insert(EntityAlias).values(
                tenant_id=tenant_id,
                identifier=identifier,
                canonical_name=canonical_name,
                source=source,
                created_at=now,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["tenant_id", "identifier"],
                set_={
                    "canonical_name": canonical_name,
                    "source": source,
                    "updated_at": now,
                },
            ).returning(EntityAlias)
            result = await db.execute(stmt)
            row = result.scalar_one()
            await db.commit()

        # Refresh the cache slot for this tenant.
        self._cache.setdefault(tenant_id, {})[identifier] = canonical_name
        logger.info(
            "entity alias registered tenant=%s identifier=%s name=%s source=%s",
            tenant_id, identifier, canonical_name, source,
        )
        return row

    async def list_for_canonical(
        self, canonical_name: str, tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[str]:
        """Return every identifier that resolves to ``canonical_name`` (case-insensitive)."""
        mapping = await self._ensure_loaded(tenant_id)
        target = canonical_name.lower()
        return sorted(
            ident for ident, name in mapping.items() if name.lower() == target
        )

    async def register_from_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict[str, Any]:
        """Run the LLM name-extraction prompt against ``messages`` and register results.

        Returns the parsed extraction dict (``user_name`` + ``mentioned_people``)
        even when registration is partial. Failures swallow into an empty dict
        so callers can fire-and-forget from the ingestion path.
        """
        if not messages:
            return {}

        conversation = _format_conversation(messages)
        prompt = [
            {"role": "system", "content": _NAME_EXTRACTION_PROMPT},
            {"role": "user", "content": (
                "Extract names from this conversation. "
                "Respond ONLY with the JSON object, nothing else.\n\n"
                f"<conversation>\n{conversation}\n</conversation>"
            )},
        ]

        try:
            raw = await llm.complete(prompt, temperature=0.0, max_tokens=400)
        except Exception:
            logger.exception("entity LLM extraction failed")
            return {}

        extracted = _parse_llm_json(raw) or {}
        user_name = extracted.get("user_name")
        if isinstance(user_name, str) and user_name.strip():
            await self.register(
                user_id, user_name.strip(),
                tenant_id=tenant_id, source="conversation",
            )
        return extracted

    def invalidate_cache(self, tenant_id: str | None = None) -> None:
        """Drop the in-memory cache. Tests + admin tools use this."""
        if tenant_id is None:
            self._cache.clear()
        else:
            self._cache.pop(tenant_id, None)


def _format_conversation(
    messages: list[dict[str, str]], max_messages: int = 20,
) -> str:
    lines: list[str] = []
    for msg in messages[-max_messages:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of the LLM response, tolerating ```json``` fences."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("entity LLM returned non-JSON: %.200s", text)
        return None
    if not isinstance(parsed, dict):
        logger.warning("entity LLM JSON is not an object: %s", type(parsed).__name__)
        return None
    return parsed


entity_service = EntityService()
