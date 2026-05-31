"""Tests for the VADER compound-score helper."""
from __future__ import annotations

from mypalace._sentiment import compound_score


def test_positive_text_scores_positive():
    assert compound_score("I love this, it's wonderful!") > 0.3


def test_negative_text_scores_negative():
    assert compound_score("This is terrible and I hate it.") < -0.3


def test_empty_text_is_neutral():
    assert compound_score("") == 0.0
    assert compound_score("   ") == 0.0


def test_score_in_range():
    assert -1.0 <= compound_score("meh, okay I guess") <= 1.0
