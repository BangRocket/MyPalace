"""Verbatim Chat History (VCH) search (phase 10 slice 5).

Source: mypalclara/core/memory/vch.py.

Postgres full-text search across the existing ``messages`` table. Returns
the matched message plus a context window of surrounding messages from
the same session — gives "what did we talk about last Tuesday" semantics
that pure semantic search misses.

Tenant-scoped via ``messages.tenant_id``. Uses the GIN expression index
``ix_messages_content_tsv`` from alembic 0009 for speed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text as sql_text

from mypalace.database import async_session
from mypalace.models import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)


# The matching message itself + ``context_window`` neighbors on each
# side. "Neighbor" = same session, ordered by created_at.
_MATCH_SQL = """
SELECT m.id, m.session_id, m.content, m.role, m.created_at,
       ts_rank(
           to_tsvector('english', m.content),
           plainto_tsquery('english', :query)
       ) AS rank
FROM messages m
JOIN sessions s ON s.id = m.session_id
WHERE s.user_id = :user_id
  AND m.tenant_id = :tenant_id
  AND length(m.content) > :min_len
  AND to_tsvector('english', m.content) @@ plainto_tsquery('english', :query)
ORDER BY rank DESC, m.created_at DESC
LIMIT :limit
"""

_CONTEXT_SQL = """
WITH match_pos AS (
    SELECT created_at FROM messages WHERE id = :msg_id
)
SELECT role, content, created_at
FROM messages
WHERE session_id = :session_id
  AND tenant_id = :tenant_id
  AND created_at BETWEEN
        (SELECT created_at - interval '5 minutes' FROM match_pos)
        AND
        (SELECT created_at + interval '5 minutes' FROM match_pos)
ORDER BY created_at ASC
LIMIT :max_context
"""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class VCHService:
    """Async verbatim chat history search."""

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        context_window: int = 2,
        min_content_length: int = 20,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict[str, Any]]:
        """Return matching message snippets ordered by relevance.

        Each snippet is::

            {
              "messages": [
                {"role": "...", "content": "...", "timestamp": "..."},
                ...
              ],
              "matched_content": "<the raw message that matched>",
              "rank": <float 0..1>,
              "timestamp": "<ISO timestamp of the match>",
            }

        Returns ``[]`` for empty/unhelpful queries instead of raising —
        VCH is a best-effort enrichment for the L2 retrieval layer.
        """
        if not query or not query.strip():
            return []

        try:
            async with async_session() as db:
                match_result = await db.execute(
                    sql_text(_MATCH_SQL),
                    {
                        "query": query,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                        "min_len": min_content_length,
                        "limit": limit,
                    },
                )
                matches = match_result.fetchall()
                if not matches:
                    return []

                # Dedupe near-overlapping snippets — if two matches land
                # in the same 10-minute window of the same session, only
                # surface one (their context windows overlap anyway).
                snippets: list[dict[str, Any]] = []
                seen: set[tuple[str, int]] = set()

                for row in matches:
                    msg_id, session_id, content, _role, created_at, rank = row
                    minute_bucket = (
                        int(created_at.timestamp()) // 600
                        if isinstance(created_at, datetime) else 0
                    )
                    dedupe_key = (session_id, minute_bucket)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    ctx_result = await db.execute(
                        sql_text(_CONTEXT_SQL),
                        {
                            "msg_id": msg_id,
                            "session_id": session_id,
                            "tenant_id": tenant_id,
                            "max_context": context_window * 2 + 1,
                        },
                    )
                    ctx_rows = ctx_result.fetchall()
                    snippets.append({
                        "messages": [
                            {
                                "role": r,
                                "content": c,
                                "timestamp": _iso(ts),
                            }
                            for r, c, ts in ctx_rows
                        ],
                        "matched_content": content,
                        "rank": float(rank),
                        "timestamp": _iso(created_at),
                    })
                return snippets
        except Exception:
            # FTS index may not exist yet on a fresh DB pre-0009, or
            # Postgres may be down — neither should block retrieval.
            logger.warning("VCH search failed", exc_info=True)
            return []


def format_for_context(
    snippets: list[dict[str, Any]],
    max_chars: int = 2000,
    assistant_label: str = "Assistant",
    user_label: str = "User",
) -> str:
    """Render snippets for prompt injection.

    Stops adding blocks once ``max_chars`` is exceeded. Returns "" when
    snippets is empty.
    """
    if not snippets:
        return ""
    parts: list[str] = []
    chars_used = 0
    for snippet in snippets:
        ts = (snippet.get("timestamp") or "")[:10]
        lines = [
            f"  {assistant_label if m['role'] == 'assistant' else user_label}: {m['content']}"
            for m in snippet["messages"]
        ]
        block = f"[{ts}]\n" + "\n".join(lines)
        if chars_used + len(block) > max_chars:
            break
        parts.append(block)
        chars_used += len(block)
    return "\n\n".join(parts)


vch_service = VCHService()
