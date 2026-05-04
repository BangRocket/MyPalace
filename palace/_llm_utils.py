"""Shared LLM response helpers."""

from __future__ import annotations

import re

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def strip_json_fences(raw: str) -> str:
    """Strip a single ```json ... ``` (or plain ``` ... ```) wrapper from a
    string, if present. No-op otherwise. Idempotent."""
    if not raw:
        return raw
    match = _FENCE_RE.match(raw.strip())
    if match:
        return match.group(1).strip()
    return raw.strip()
