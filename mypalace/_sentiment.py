"""VADER sentiment helper — fast rule-based compound scoring.

Mirrors mypalclara/core/sentiment.py. Only the compound score is needed
by the emotional-context service, so the surface is intentionally tiny.
"""

from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def compound_score(text: str) -> float:
    """Return the VADER compound score (-1..+1). Empty text → 0.0."""
    if not text or not text.strip():
        return 0.0
    return _get_analyzer().polarity_scores(text)["compound"]
