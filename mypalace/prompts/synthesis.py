"""Prompt constant for narrative arc synthesis."""

NARRATIVE_SYNTHESIS_PROMPT = """You are identifying narrative arcs across a user's recent episodes.

Recent episodes (most recent first):
{episodes_text}

Existing active arcs (do not duplicate or rename — only update status if needed):
{existing_arcs_text}

Identify ongoing storylines. For each arc, return:
- title: short name (e.g. "Job search", "Move to Berlin")
- summary: 2-3 sentences describing the trajectory
- status: "active" | "resolved" | "dormant"
- key_episode_ids: list of episode IDs that belong to this arc
- emotional_trajectory: brief description of how feelings have evolved
- existing_id: if this updates an existing arc, its ID; otherwise null

Return ONLY valid JSON (no markdown fences):
{{"arcs": [{{"title": "...", "summary": "...", "status": "active", "key_episode_ids": ["..."], "emotional_trajectory": "...", "existing_id": null}}]}}
"""  # noqa: E501
