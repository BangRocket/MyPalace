"""Stable event-type constants. Clients filter via ``?topics=...``."""

MEMORY_CREATED = "memory.created"
MEMORY_UPDATED = "memory.updated"
MEMORY_DELETED = "memory.deleted"
MEMORY_SUPERSEDED = "memory.superseded"
EPISODE_CREATED = "episode.created"
INTENTION_FIRED = "intention.fired"
ARC_SYNTHESIZED = "arc.synthesized"

KNOWN_EVENT_TYPES = frozenset({
    MEMORY_CREATED,
    MEMORY_UPDATED,
    MEMORY_DELETED,
    MEMORY_SUPERSEDED,
    EPISODE_CREATED,
    INTENTION_FIRED,
    ARC_SYNTHESIZED,
})
