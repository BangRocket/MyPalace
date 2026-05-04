"""LLM prompt for smart memory extraction (slice 5)."""

SMART_INGEST_PROMPT = """\
Extract durable factual memories from the conversation below.

Rules:
- Extract only stable facts, preferences, beliefs, decisions, and goals.
  Skip greetings, small talk, and ephemeral status.
- Each memory should be self-contained and understandable on its own.
- Do not include opinions about the conversation itself.
- Categorize each memory: "fact" | "preference" | "goal" | "belief" |
  "skill" | "relationship" | "other".
- Importance 0.0-1.0 (1.0 = critical, 0.5 = useful, 0.1 = trivia).
- Sensitivity "low" | "medium" | "high".

Return STRICT JSON only (no markdown, no commentary):

{{
  "memories": [
    {{
      "content": "<the memory as a single declarative sentence>",
      "category": "<one of the categories>",
      "importance": <float 0.0-1.0>,
      "sensitivity": "<low|medium|high>"
    }}
  ]
}}

If no memories worth keeping, return {{"memories": []}}.

Conversation:
{conversation_text}
"""
