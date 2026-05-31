"""Prompt for LLM topic extraction.

Source: mypalclara/core/memory/context/topics.py:TOPIC_EXTRACTION_PROMPT.
"""

TOPIC_EXTRACTION_PROMPT = """Extract key topics from this conversation that might recur in future conversations.

**The conversation:**
{conversation}

**Conversation sentiment:** {sentiment:.2f} (scale: -1 negative to +1 positive)

**What to extract:**
For each topic, provide:
- topic: Normalized name using consistent, lowercase, singular forms. Prefer common phrasing (e.g., "job search" not "employment hunt" or "the job hunt", "mom" not "my mother")
- topic_type: "entity" (person, place, project, company) or "theme" (ongoing concern, interest, goal)
- context_snippet: Brief summary of how it came up (10-20 words)
- emotional_weight: "light" (casual mention), "moderate" (some feeling), "heavy" (significant emotion)

**Rules:**
1. Only extract topics with emotional significance OR specific enough to recur
2. Skip generic topics like "work", "life", "stuff", "things"
3. Use consistent normalization - same topic should always have the same name
4. Max 3 unique topics per conversation

**Respond in JSON:**
{{
    "topics": [
        {{
            "topic": "job search",
            "topic_type": "theme",
            "context_snippet": "frustrated about not hearing back from interviews",
            "emotional_weight": "heavy"
        }}
    ]
}}

If no significant topics, return: {{"topics": []}}"""  # noqa: E501
