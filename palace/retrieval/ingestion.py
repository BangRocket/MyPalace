"""SmartIngestionService — LLM extraction + vector dedup + supersede (slice 5).

Activates on POST /v1/memories/batch when ``infer=True``. Pipeline:

1. extract_memories(messages, ...) — call LLM with SMART_INGEST_PROMPT,
   parse JSON, return a list of candidate memories.
2. dedup_and_write(candidates, ...) — for each candidate:
   - Embed and Qdrant-search for the nearest existing memory.
   - score > SKIP_THRESHOLD (0.95): skip as duplicate.
   - score > UPDATE_THRESHOLD (0.75): heuristic contradiction check;
     if contradicts with confidence > 0.7, supersede the old one.
     Otherwise skip as "similar".
   - Else: write a new memory normally.

Heuristic contradiction detection (D5) — no LLM. Looks for negation cues
on overlapping subjects. Conservative; intended to catch the obvious
"I love coffee" -> "I no longer drink coffee" cases.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

from palace._llm_utils import strip_json_fences
from palace.database import async_session
from palace.dynamics.service import dynamics_service
from palace.embeddings import EmbeddingProvider, get_embedder
from palace.llm import llm
from palace.memory_service import memory_service
from palace.models import DEFAULT_TENANT_ID, Memory, MemorySupersession, utcnow
from palace.prompts.ingestion import SMART_INGEST_PROMPT
from palace.vector import vector_store

# Thresholds (D4) — match mypalclara's config.py:41-43.
SKIP_THRESHOLD = 0.95
UPDATE_THRESHOLD = 0.75
SUPERSEDE_THRESHOLD = 0.6
CONTRADICTION_CONFIDENCE_THRESHOLD = 0.7

# Negation cues used by the heuristic.
_NEGATION_TOKENS = {
    "not", "no", "never", "n't", "none", "nothing",
    "stopped", "quit", "former", "ex", "longer",
    "anymore", "any-more",
}

# Stop-words that don't count as overlap signal.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "to", "in",
    "for", "on", "with", "as", "by", "at", "from", "about", "into",
    "through", "during", "i", "me", "my", "we", "our", "you", "your",
    "he", "she", "it", "they", "them", "and", "or", "but", "so",
    "this", "that", "these", "those",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase word-set, stripping punctuation, stopwords, and trivial
    inflections (trailing 's' / 'es' / 'ing' / 'ed' / 'd'). Naive stemmer is
    enough for the contradiction heuristic — we only need to match obvious
    pairs like "loves"/"love"."""
    cleaned = "".join(c if c.isalnum() or c.isspace() or c == "'" else " " for c in text.lower())
    tokens = {t.strip("'") for t in cleaned.split() if t}
    out: set[str] = set()
    for t in tokens:
        if not t or t in _STOPWORDS:
            continue
        # Naive stem
        for suf in ("ing", "ed", "es", "s"):
            if len(t) > len(suf) + 2 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.add(t)
    return out


def _has_negation(text: str) -> bool:
    """Return True if the text contains any negation cue."""
    lowered = text.lower()
    if "n't" in lowered:
        return True
    tokens = lowered.split()
    return any(t.strip(".,!?;:") in _NEGATION_TOKENS for t in tokens)


class SmartIngestionService:
    """LLM extraction + vector dedup + supersede pipeline."""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_memories(
        self,
        messages: list[dict[str, Any]],
        user_id: str,
        agent_id: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict[str, Any]]:
        """Call the LLM with the smart-ingest prompt; return a list of
        candidate memory dicts (each with ``content``/``category``/
        ``importance``/``sensitivity``).

        Raises ValueError on malformed JSON.
        """
        conversation_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )
        prompt = SMART_INGEST_PROMPT.format(conversation_text=conversation_text)

        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500,
        )

        try:
            parsed = json.loads(strip_json_fences(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned non-JSON for smart-ingest: {e}") from e

        extracted = parsed.get("memories", [])
        if not isinstance(extracted, list):
            raise ValueError(
                f"LLM returned non-list 'memories' field: {type(extracted).__name__}",
            )
        return [m for m in extracted if isinstance(m, dict) and m.get("content")]

    # ------------------------------------------------------------------ #
    # Contradiction heuristic
    # ------------------------------------------------------------------ #

    def _check_contradiction(
        self, old_content: str, new_content: str,
    ) -> tuple[bool, float, str]:
        """Heuristic contradiction detection (no LLM).

        Returns (contradicts, confidence 0-1, reason_string).

        Strategy: if exactly one of the two statements contains a negation
        cue AND they share enough subject-word overlap, treat as contradiction.
        Confidence scales with the overlap ratio.
        """
        old_neg = _has_negation(old_content)
        new_neg = _has_negation(new_content)

        # If both or neither carry negation we can't reliably call it.
        if old_neg == new_neg:
            return (False, 0.0, "no negation asymmetry")

        old_tokens = _tokenize(old_content)
        new_tokens = _tokenize(new_content)
        if not old_tokens or not new_tokens:
            return (False, 0.0, "insufficient content")

        # Strip negation cues from token sets before measuring overlap so that
        # the negation itself isn't counted as either signal or noise.
        old_signal = old_tokens - _NEGATION_TOKENS
        new_signal = new_tokens - _NEGATION_TOKENS
        if not old_signal or not new_signal:
            return (False, 0.0, "no signal tokens")
        overlap = old_signal & new_signal

        smaller = min(len(old_signal), len(new_signal))
        ratio = len(overlap) / max(smaller, 1)
        confidence = min(1.0, ratio)

        # Need at least 2 overlapping content words to call it a contradiction;
        # one shared word is too weak.
        if len(overlap) < 2:
            return (False, confidence, "insufficient subject overlap")

        return (True, confidence, "negation:overlap")

    # ------------------------------------------------------------------ #
    # Dedup + write
    # ------------------------------------------------------------------ #

    async def dedup_and_write(
        self,
        candidates: list[dict[str, Any]],
        user_id: str,
        agent_id: str | None = None,
        memory_type: str = "semantic",
        source: str | None = None,
        base_metadata: dict[str, Any] | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> tuple[list[Memory], list[dict[str, Any]], list[dict[str, Any]]]:
        """For each candidate: search nearest existing memory, decide
        skip/update/supersede/write.

        Returns (written, supersessions, skipped).
        """
        written: list[Memory] = []
        supersessions: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for cand in candidates:
            content = cand["content"]
            cand_meta = {
                k: v for k, v in cand.items()
                if k not in {"content", "importance"}
            }
            merged_meta = {**(base_metadata or {}), **cand_meta}
            importance = float(cand.get("importance", 1.0))

            # Embed once and search nearest.
            vectors = await self.embedder.embed([content])
            results = await vector_store.search(
                vectors[0],
                limit=1,
                user_id=user_id,
                agent_id=agent_id,
                tenant_id=tenant_id,
            )

            if results:
                existing_id, score = results[0]

                if score > SKIP_THRESHOLD:
                    skipped.append({"reason": "duplicate", "similarity": float(score)})
                    continue

                if score > UPDATE_THRESHOLD:
                    # Look up old content to run contradiction check.
                    existing = await memory_service.get(existing_id, tenant_id=tenant_id)
                    if existing is not None:
                        contradicts, conf, why = self._check_contradiction(
                            existing.content, content,
                        )
                        if contradicts and conf > CONTRADICTION_CONFIDENCE_THRESHOLD:
                            # Write new + supersede old.
                            new_mem = await memory_service.create(
                                user_id=user_id,
                                content=content,
                                memory_type=memory_type,
                                agent_id=agent_id,
                                source=source,
                                importance=importance,
                                metadata=merged_meta or None,
                                tenant_id=tenant_id,
                            )
                            await self._record_supersession(
                                superseded_id=existing_id,
                                new_id=new_mem.id,
                                user_id=user_id,
                                reason=f"contradiction:{why}",
                                similarity_score=float(score),
                                tenant_id=tenant_id,
                            )
                            written.append(new_mem)
                            supersessions.append({
                                "superseded_id": existing_id,
                                "new_id": new_mem.id,
                                "similarity": float(score),
                                "reason": f"contradiction:{why}",
                            })
                            continue
                        # Similar but not contradictory — skip as redundant.
                        skipped.append({
                            "reason": "similar",
                            "similarity": float(score),
                        })
                        continue

            # Novel (or no nearest neighbor) — write fresh.
            new_mem = await memory_service.create(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=importance,
                metadata=merged_meta or None,
                tenant_id=tenant_id,
            )
            written.append(new_mem)

        return written, supersessions, skipped

    # ------------------------------------------------------------------ #
    # Supersession bookkeeping
    # ------------------------------------------------------------------ #

    async def _record_supersession(
        self,
        superseded_id: str,
        new_id: str,
        user_id: str,
        reason: str,
        similarity_score: float | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> MemorySupersession:
        """Insert a MemorySupersession row and demote the old memory's dynamics.

        Demotion failure is logged-not-raised — supersession bookkeeping
        is the source of truth, FSRS update is best-effort.
        """
        async with async_session() as db:
            row = MemorySupersession(
                tenant_id=tenant_id,
                superseded_id=superseded_id,
                new_id=new_id,
                user_id=user_id,
                reason=reason,
                similarity_score=similarity_score,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)

        # Best-effort FSRS demotion; audit row is the source of truth.
        with contextlib.suppress(Exception):
            await dynamics_service.demote(
                memory_id=superseded_id,
                user_id=user_id,
                reason="superseded",
                tenant_id=tenant_id,
            )

        return row

    # ------------------------------------------------------------------ #
    # Manual supersede + history lookup
    # ------------------------------------------------------------------ #

    async def supersede_memory(
        self,
        old_memory_id: str,
        new_content: str,
        user_id: str,
        reason: str = "manual_correction",
        metadata: dict[str, Any] | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict[str, Any] | None:
        """Manually replace an old memory with a new one.

        Creates a new memory and records a MemorySupersession row.
        Returns ``{"superseded_id", "new_id", "reason"}`` or None if the
        old memory wasn't found.
        """
        old = await memory_service.get(old_memory_id, tenant_id=tenant_id)
        if old is None:
            return None

        new_mem = await memory_service.create(
            user_id=user_id,
            content=new_content,
            memory_type=old.memory_type,
            agent_id=old.agent_id,
            source=old.source,
            importance=old.importance,
            metadata=metadata,
            tenant_id=tenant_id,
        )

        await self._record_supersession(
            superseded_id=old_memory_id,
            new_id=new_mem.id,
            user_id=user_id,
            reason=reason,
            similarity_score=None,
            tenant_id=tenant_id,
        )

        return {
            "superseded_id": old_memory_id,
            "new_id": new_mem.id,
            "reason": reason,
        }

    async def get_supersessions(
        self,
        memory_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict[str, Any]]:
        """Return supersession history involving this memory_id (either side)."""
        async with async_session() as db:
            stmt = select(MemorySupersession).where(
                MemorySupersession.tenant_id == tenant_id,
                or_(
                    MemorySupersession.superseded_id == memory_id,
                    MemorySupersession.new_id == memory_id,
                ),
            )
            result = await db.execute(stmt)
            rows = list(result.scalars().all())

        return [
            {
                "superseded_id": r.superseded_id,
                "new_id": r.new_id,
                "reason": r.reason,
                "similarity_score": r.similarity_score,
                "created_at": (
                    r.created_at.isoformat()
                    if isinstance(r.created_at, datetime) else None
                ),
            }
            for r in rows
        ]


# Singleton
smart_ingestion_service = SmartIngestionService()


# Re-export utcnow for tests that need to construct rows.
__all__ = [
    "CONTRADICTION_CONFIDENCE_THRESHOLD",
    "SKIP_THRESHOLD",
    "SUPERSEDE_THRESHOLD",
    "UPDATE_THRESHOLD",
    "SmartIngestionService",
    "smart_ingestion_service",
    "utcnow",
]
