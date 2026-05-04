"""
Reference router for mypalclara: per-method delegation between remote
Palace (HTTP) and the embedded ClaraMemory + MemoryManager.

How to use:
    1. Install palace_client into mypalclara's environment:
         pip install -e /path/to/palace-memory/palace_client
       or via git+url:
         pip install "git+https://github.com/BangRocket/palace-memory.git@<sha>#subdirectory=palace_client"
    2. Copy this file into mypalclara as `mypalclara/core/memory/routed.py`
       and adjust the embedded imports to match mypalclara's layout.
    3. Replace every `from mypalclara.core.memory import PALACE` (and the
       analogous MemoryManager import) with imports from the new module.
    4. Toggle behavior at runtime via env vars:
         export USE_PALACE_SERVICE=true
         export PALACE_SERVICE_URL=http://palace.local:8000
         export PALACE_API_KEY=...

This router uses **explicit pass-throughs** (per phase-2 design D6): every
public method of the embedded ClaraMemory + MemoryManager has its own
entry. No __getattr__ fallthrough — adding a new method on the embedded
side requires adding an explicit entry here, otherwise calls raise
AttributeError loudly.

Slice-1 methods routed to remote when toggle is on:
    PALACE.add, .search, .get_all, .delete_all, .get, .delete, .update.
Everything else stays embedded until later slices land.
"""

from __future__ import annotations

import asyncio
import os

from palace_client import PalaceClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USE_PALACE_SERVICE = os.getenv("USE_PALACE_SERVICE", "false").lower() == "true"
PALACE_SERVICE_URL = os.getenv("PALACE_SERVICE_URL", "http://localhost:8000")
PALACE_API_KEY = os.getenv("PALACE_API_KEY")


# ---------------------------------------------------------------------------
# Embedded singletons (replace these imports for the mypalclara environment)
# ---------------------------------------------------------------------------
# In the real mypalclara repo:
#   from mypalclara.core.memory import PALACE as _EMBEDDED_PALACE
#   from mypalclara.core.memory_manager import MemoryManager as _EmbeddedMM
# This file is committed to the palace-memory repo as a reference, so we
# stub them here. Remove the stubs when copying into mypalclara.
class _EmbeddedStub:
    def __getattr__(self, name):
        raise NotImplementedError(
            f"_EmbeddedStub.{name}: replace this stub with the real "
            f"mypalclara import when copying this file in."
        )


_EMBEDDED_PALACE = _EmbeddedStub()
_EmbeddedMM = _EmbeddedStub()


# ---------------------------------------------------------------------------
# Remote proxies for sub-objects
# ---------------------------------------------------------------------------

class RemoteEpisodeStore:
    """Proxy that exposes ClaraMemory.episode_store's surface (search, get_recent,
    get_active_arcs) but routes to a remote PalaceClient."""

    def __init__(self, client: PalaceClient) -> None:
        self._client = client

    async def search(self, query: str, user_id: str, limit: int = 5, min_significance: float = 0.0):
        return await self._client.search_episodes(
            query=query, user_id=user_id, limit=limit, min_significance=min_significance,
        )

    async def get_recent(self, user_id: str, limit: int = 5):
        return await self._client.get_recent_episodes(user_id=user_id, limit=limit)

    async def get_active_arcs(self, user_id: str, limit: int = 10):
        return await self._client.get_active_arcs(user_id=user_id, limit=limit)


# ---------------------------------------------------------------------------
# Remote client (lazy)
# ---------------------------------------------------------------------------

_REMOTE: PalaceClient | None = None


def _remote() -> PalaceClient:
    global _REMOTE
    if _REMOTE is None:
        _REMOTE = PalaceClient(
            base_url=PALACE_SERVICE_URL, api_key=PALACE_API_KEY,
        )
    return _REMOTE


async def _maybe_await(value):
    """Embedded ClaraMemory is sync; PalaceClient is async. Router methods
    are async, so callers always `await`. This helper awaitifies sync
    return values so the same code path works either way."""
    if asyncio.iscoroutine(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# RoutedPalace — mirror of ClaraMemory's surface
# ---------------------------------------------------------------------------

class RoutedPalace:
    """Looks like ClaraMemory; explicit per-method routing."""

    # ---- Slice 1: remote-eligible ----

    async def add(self, messages, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().add(messages, user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.add(messages, user_id=user_id, **kw),
        )

    async def search(self, query, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().search(query, user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.search(query, user_id=user_id, **kw),
        )

    async def get_all(self, user_id=None, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().get_all(user_id=user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.get_all(user_id=user_id, **kw),
        )

    async def delete_all(self, user_id, **kw):
        if USE_PALACE_SERVICE:
            return await _remote().delete_all(user_id, **kw)
        return await _maybe_await(
            _EMBEDDED_PALACE.delete_all(user_id=user_id, **kw),
        )

    async def get(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().get(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.get(memory_id))

    async def delete(self, memory_id):
        if USE_PALACE_SERVICE:
            return await _remote().delete(memory_id)
        return await _maybe_await(_EMBEDDED_PALACE.delete(memory_id))

    async def update(self, memory_id, **fields):
        if USE_PALACE_SERVICE:
            return await _remote().update(memory_id, **fields)
        return await _maybe_await(_EMBEDDED_PALACE.update(memory_id, **fields))

    # ---- Slice 2+ candidates: embedded only for now ----

    async def history(self, memory_id):
        # Slice 2 candidate (memory history endpoint).
        return await _maybe_await(_EMBEDDED_PALACE.history(memory_id))

    async def update_memory_visibility(self, memory_id, visibility):
        # Slice 2 candidate.
        return await _maybe_await(
            _EMBEDDED_PALACE.update_memory_visibility(memory_id, visibility),
        )

    # ---- Sub-objects: embedded only in slice 1 ----
    # These are direct attribute accesses (not methods); callers reach into
    # PALACE.embedding_model.embed(...) and PALACE.graph.search(...). When
    # USE_PALACE_SERVICE is on, these still resolve to the embedded objects
    # because there are no remote endpoints for them yet. Slice 2+ may add
    # POST /v1/embeddings and a graph API; this section is the natural place
    # to introduce remote-aware proxies later.

    @property
    def embedding_model(self):
        return _EMBEDDED_PALACE.embedding_model

    @property
    def graph(self):
        return _EMBEDDED_PALACE.graph

    @property
    def episode_store(self):
        if USE_PALACE_SERVICE:
            return RemoteEpisodeStore(_remote())
        return _EMBEDDED_PALACE.episode_store


# ---------------------------------------------------------------------------
# RoutedMemoryManager — mirror of MemoryManager's surface
# ---------------------------------------------------------------------------
# Every public method gets an explicit entry. Slice-1 routes none of these
# (they all stay embedded); branches will be added as slices 2-5 land.

class RoutedMemoryManager:
    """Looks like MemoryManager; every method explicit pass-through to
    embedded in slice 1. Branches added in slices 3-5 as endpoints land.

    Note: Many MemoryManager methods take an SQLAlchemy `db` session as the
    first arg. Those stay embedded indefinitely — there is no plan to send
    a remote DB session over HTTP. They are listed here for completeness so
    that the router shape mirrors the embedded API exactly.
    """

    # ---- Singleton lifecycle ----

    @classmethod
    def initialize(cls, llm_callable, agent_id=None, on_memory_event=None):
        return _EmbeddedMM.initialize(llm_callable, agent_id, on_memory_event)

    @classmethod
    def get_instance(cls):
        return _EmbeddedMM.get_instance()

    @classmethod
    def reset(cls):
        return _EmbeddedMM.reset()

    # ---- Session management (DB-bound, embedded indefinitely) ----

    def get_or_create_session(self, db, user_id, context_id, project_id, title):
        return _EmbeddedMM.get_instance().get_or_create_session(
            db, user_id, context_id, project_id, title,
        )

    def get_thread(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_thread(db, thread_id)

    def get_recent_messages(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_recent_messages(db, thread_id)

    def get_message_count(self, db, thread_id):
        return _EmbeddedMM.get_instance().get_message_count(db, thread_id)

    def store_message(self, db, thread_id, user_id, role, content):
        return _EmbeddedMM.get_instance().store_message(
            db, thread_id, user_id, role, content,
        )

    def should_update_summary(self, db, thread_id):
        return _EmbeddedMM.get_instance().should_update_summary(db, thread_id)

    def update_thread_summary(self, db, thread):
        return _EmbeddedMM.get_instance().update_thread_summary(db, thread)

    # ---- Memory retrieval & writing ----

    def fetch_context(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_context(*args, **kw)

    def add_to_palace(self, *args, **kw):
        return _EmbeddedMM.get_instance().add_to_palace(*args, **kw)

    def add_to_memory(self, *args, **kw):
        return _EmbeddedMM.get_instance().add_to_memory(*args, **kw)

    # ---- Prompt building ----

    def fetch_emotional_context(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_emotional_context(*args, **kw)

    def build_prompt(self, *args, **kw):
        return _EmbeddedMM.get_instance().build_prompt(*args, **kw)

    async def build_prompt_layered(self, *args, **kw):
        """Slice 5: routes to /v1/context/layered when toggle is on.

        IMPORTANT: the routed return type is a structured dict (LayeredContext
        with l1_user_profile / l2_relevant_context / recent_messages /
        char_counts), NOT the typed Messages list returned by the embedded
        PromptBuilder.build_prompt_layered. Consumers must adapt — the routed
        path drops Discord-specific layers (L0 SOUL.md, channel_context, vault
        snapshots) per Palace phase-2 design D1, and the caller is
        responsible for composing the dict into the actual prompt Messages.

        Common kwargs accepted by both: ``user_id`` (positional or kw),
        ``query``/``user_message`` (the message text), ``session_id``,
        ``use_fsrs``, ``memory_limit``, ``episode_limit``.
        """
        if USE_PALACE_SERVICE:
            user_id = kw.pop("user_id", None) or (args[0] if args else None)
            query = (
                kw.pop("query", None)
                or kw.pop("user_message", None)
                or (args[1] if len(args) > 1 else "")
            )
            return await _remote().assemble_layered_context(
                user_id=user_id,
                query=query,
                agent_id=kw.pop("agent_id", None),
                session_id=kw.pop("session_id", None),
                use_fsrs=kw.pop("use_fsrs", True),
                memory_limit=kw.pop("memory_limit", 10),
                episode_limit=kw.pop("episode_limit", 5),
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().build_prompt_layered(*args, **kw),
        )

    def fetch_topic_recurrence(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_topic_recurrence(*args, **kw)

    async def load_user_workspace(self, user_id, vm_manager):
        return await _maybe_await(
            _EmbeddedMM.get_instance().load_user_workspace(user_id, vm_manager),
        )

    # ---- FSRS dynamics (slice 3) ----
    # promote_memory, demote_memory, get_memory_dynamics, calculate_memory_score
    # and prune_old_access_logs all have remote endpoints in slice 3.
    # ensure_memory_dynamics stays embedded — promote/score auto-create the
    # row server-side, so callers rarely need it directly. Slice-3 design D4:
    # get_last_retrieved_memory_ids stays embedded (caller-side cache; the
    # HTTP service is stateless between requests).

    async def get_memory_dynamics(self, memory_id, user_id):
        if USE_PALACE_SERVICE:
            return await _remote().get_dynamics(memory_id, user_id=user_id)
        return await _maybe_await(
            _EmbeddedMM.get_instance().get_memory_dynamics(memory_id, user_id),
        )

    def ensure_memory_dynamics(self, memory_id, user_id, is_key):
        # No remote endpoint — promote/score auto-create the row server-side.
        return _EmbeddedMM.get_instance().ensure_memory_dynamics(
            memory_id, user_id, is_key,
        )

    async def promote_memory(self, memory_id, user_id, grade=3, signal_type="used_in_response"):
        if USE_PALACE_SERVICE:
            return await _remote().promote_memory(
                memory_id, user_id=user_id, grade=grade, signal_type=signal_type,
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().promote_memory(
                memory_id, user_id, grade, signal_type,
            ),
        )

    async def demote_memory(self, memory_id, user_id, reason="user_correction"):
        if USE_PALACE_SERVICE:
            return await _remote().demote_memory(
                memory_id, user_id=user_id, reason=reason,
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().demote_memory(memory_id, user_id, reason),
        )

    async def calculate_memory_score(self, memory_id, user_id, semantic_score):
        if USE_PALACE_SERVICE:
            breakdown = await _remote().score_memory(
                memory_id, user_id=user_id, semantic_score=semantic_score,
            )
            return breakdown.composite_score
        return await _maybe_await(
            _EmbeddedMM.get_instance().calculate_memory_score(
                memory_id, user_id, semantic_score,
            ),
        )

    def get_last_retrieved_memory_ids(self, user_id):
        # Stays embedded (slice-3 design D4) — caller-side cache; the HTTP
        # service is stateless across requests/workers.
        return _EmbeddedMM.get_instance().get_last_retrieved_memory_ids(user_id)

    async def prune_old_access_logs(self, db, retention_days=90):
        if USE_PALACE_SERVICE:
            # `db` is unused remotely (server owns its own session).
            return await _remote().prune_access_logs(retention_days=retention_days)
        return await _maybe_await(
            _EmbeddedMM.get_instance().prune_old_access_logs(db, retention_days),
        )

    # ---- Intentions (slice 4) ----
    # Endpoints: set_intention, check_intentions, format_intentions_for_prompt
    # all have remote equivalents in slice 4. Trigger matching is deterministic
    # (no LLM) — purely structural keyword/topic/time/context matching.

    async def set_intention(
        self,
        user_id,
        content,
        trigger_conditions,
        expires_at=None,
        source_memory_id=None,
    ):
        if USE_PALACE_SERVICE:
            intention = await _remote().set_intention(
                user_id=user_id,
                content=content,
                trigger_conditions=trigger_conditions,
                expires_at=expires_at,
                source_memory_id=source_memory_id,
            )
            return intention.id
        return await _maybe_await(
            _EmbeddedMM.get_instance().set_intention(
                user_id, content, trigger_conditions, expires_at, source_memory_id,
            ),
        )

    async def check_intentions(self, user_id, message, context=None):
        if USE_PALACE_SERVICE:
            fired = await _remote().check_intentions(
                user_id=user_id, message=message, context=context,
            )
            # Embedded contract returns list[dict]; mirror that.
            return [f.model_dump() for f in fired]
        return await _maybe_await(
            _EmbeddedMM.get_instance().check_intentions(user_id, message, context),
        )

    async def format_intentions_for_prompt(self, fired_intentions):
        if USE_PALACE_SERVICE:
            return await _remote().format_intentions(intentions=fired_intentions)
        return await _maybe_await(
            _EmbeddedMM.get_instance().format_intentions_for_prompt(fired_intentions),
        )

    # ---- Reflection (slice 4) ----

    async def reflect_on_session(self, messages, user_id, session_id):
        if USE_PALACE_SERVICE:
            # Use sync mode so the call shape (returns list of episodes) matches
            # the embedded ClaraMemory contract. Async mode would change the
            # return type and break callers.
            return await _remote().reflect_session(
                messages=messages, user_id=user_id, session_id=session_id, mode="sync",
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().reflect_on_session(
                messages, user_id, session_id,
            ),
        )

    async def run_narrative_synthesis(self, user_id):
        if USE_PALACE_SERVICE:
            return await _remote().synthesize_narratives(user_id=user_id, mode="sync")
        return await _maybe_await(
            _EmbeddedMM.get_instance().run_narrative_synthesis(user_id),
        )

    # ---- Smart ingestion (slice 5) ----

    async def smart_ingest(self, messages, user_id, agent_id=None, **kw):
        """Routes to POST /v1/memories/batch with infer=True when toggle is on.

        The remote pipeline runs LLM extraction + vector dedup + heuristic
        supersede server-side; the response carries written memories plus
        ``meta.supersessions`` and ``meta.skipped`` debug data. The embedded
        equivalent is mypalclara's MemoryIngestionManager.smart_ingest which
        does the same work in-process. Consumers reading meta fields will
        need to switch from the embedded return shape to the routed one.
        """
        if USE_PALACE_SERVICE:
            return await _remote().add(
                messages=messages,
                user_id=user_id,
                agent_id=agent_id,
                infer=True,
                **kw,
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().smart_ingest(
                messages, user_id=user_id, agent_id=agent_id, **kw,
            ),
        )

    async def supersede_memory(
        self,
        old_memory_id,
        new_content,
        user_id,
        reason="manual_correction",
        metadata=None,
    ):
        """Routes to POST /v1/memories/{id}/supersede when toggle is on."""
        if USE_PALACE_SERVICE:
            return await _remote().supersede_memory(
                memory_id=old_memory_id,
                user_id=user_id,
                new_content=new_content,
                reason=reason,
                metadata=metadata,
            )
        return await _maybe_await(
            _EmbeddedMM.get_instance().supersede_memory(
                old_memory_id, new_content, user_id, reason, metadata,
            ),
        )


# ---------------------------------------------------------------------------
# Public singletons — these are what mypalclara should import.
# ---------------------------------------------------------------------------

PALACE = RoutedPalace()
MM = RoutedMemoryManager()
