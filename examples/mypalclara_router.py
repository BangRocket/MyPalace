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

    def build_prompt_layered(self, *args, **kw):
        # Slice 5 candidate.
        return _EmbeddedMM.get_instance().build_prompt_layered(*args, **kw)

    def fetch_topic_recurrence(self, *args, **kw):
        return _EmbeddedMM.get_instance().fetch_topic_recurrence(*args, **kw)

    async def load_user_workspace(self, user_id, vm_manager):
        return await _maybe_await(
            _EmbeddedMM.get_instance().load_user_workspace(user_id, vm_manager),
        )

    # ---- FSRS dynamics (slice 3) ----

    def get_memory_dynamics(self, memory_id, user_id):
        return _EmbeddedMM.get_instance().get_memory_dynamics(memory_id, user_id)

    def ensure_memory_dynamics(self, memory_id, user_id, is_key):
        return _EmbeddedMM.get_instance().ensure_memory_dynamics(
            memory_id, user_id, is_key,
        )

    def promote_memory(self, memory_id, user_id, grade, signal_type):
        return _EmbeddedMM.get_instance().promote_memory(
            memory_id, user_id, grade, signal_type,
        )

    def demote_memory(self, memory_id, user_id, reason):
        return _EmbeddedMM.get_instance().demote_memory(memory_id, user_id, reason)

    def calculate_memory_score(self, memory_id, user_id, semantic_score):
        return _EmbeddedMM.get_instance().calculate_memory_score(
            memory_id, user_id, semantic_score,
        )

    def get_last_retrieved_memory_ids(self, user_id):
        return _EmbeddedMM.get_instance().get_last_retrieved_memory_ids(user_id)

    def prune_old_access_logs(self, db, retention_days):
        return _EmbeddedMM.get_instance().prune_old_access_logs(db, retention_days)

    # ---- Intentions (slice 4) ----

    def set_intention(self, *args, **kw):
        return _EmbeddedMM.get_instance().set_intention(*args, **kw)

    def check_intentions(self, *args, **kw):
        return _EmbeddedMM.get_instance().check_intentions(*args, **kw)

    def format_intentions_for_prompt(self, fired_intentions):
        return _EmbeddedMM.get_instance().format_intentions_for_prompt(
            fired_intentions,
        )

    # ---- Reflection (slice 4) ----

    async def reflect_on_session(self, messages, user_id, session_id):
        return await _maybe_await(
            _EmbeddedMM.get_instance().reflect_on_session(
                messages, user_id, session_id,
            ),
        )

    async def run_narrative_synthesis(self, user_id):
        return await _maybe_await(
            _EmbeddedMM.get_instance().run_narrative_synthesis(user_id),
        )

    # ---- Smart ingestion (slice 5) ----

    def smart_ingest(self, *args, **kw):
        return _EmbeddedMM.get_instance().smart_ingest(*args, **kw)

    def supersede_memory(self, *args, **kw):
        return _EmbeddedMM.get_instance().supersede_memory(*args, **kw)


# ---------------------------------------------------------------------------
# Public singletons — these are what mypalclara should import.
# ---------------------------------------------------------------------------

PALACE = RoutedPalace()
MM = RoutedMemoryManager()
