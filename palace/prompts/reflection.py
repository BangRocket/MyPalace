"""Prompt constant for session reflection (episode extraction)."""

SESSION_REFLECTION_PROMPT = """You are analyzing a conversation to extract meaningful episodes.

Conversation:
{conversation_text}

Extract 1-5 distinct episodes from this conversation. For each episode, provide:
- summary: one sentence describing what happened
- topics: list of 1-5 short topic tags
- emotional_tone: one of [happy, sad, anxious, frustrated, curious, neutral, excited, contemplative]
- significance: float 0.0-1.0 indicating how meaningful this exchange was
- start_index, end_index: integer indices into the message list (inclusive, 0-based)

Return ONLY valid JSON in exactly this shape (no markdown fences, no commentary):
{{"episodes": [{{"summary": "...", "topics": ["..."], "emotional_tone": "neutral", "significance": 0.5, "start_index": 0, "end_index": 0}}]}}
"""  # noqa: E501
