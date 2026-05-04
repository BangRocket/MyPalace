"""Process-local debounce for last_used_at writes."""

from __future__ import annotations

import time


class UsageTracker:
    """Returns True at most once per `debounce_seconds` per key.

    Process-local. Multi-worker deployments will get N writes per minute
    in the worst case; that's acceptable — the column is a hint, not
    a counter.
    """

    def __init__(self, debounce_seconds: float = 60.0) -> None:
        self._debounce = debounce_seconds
        self._last: dict[str, float] = {}

    def should_update(self, key_id: str) -> bool:
        now = time.monotonic()
        last = self._last.get(key_id, 0.0)
        if now - last >= self._debounce:
            self._last[key_id] = now
            return True
        return False

    def reset(self) -> None:
        self._last.clear()


usage_tracker = UsageTracker()
