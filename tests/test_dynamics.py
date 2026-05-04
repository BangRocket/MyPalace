"""Slice-3 tests: FSRS math + DynamicsService routes (mock-based).

Math tests pin known input -> output to catch porting drift from
mypalclara's fsrs.py. Route tests use the slice-1/2 mock client pattern.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from palace.dynamics.fsrs import (
    FsrsParams,
    Grade,
    MemoryState,
    calculate_memory_score,
    infer_grade_from_signal,
    initial_difficulty,
    initial_stability,
    retrievability,
    review,
    update_stability_success,
)

# ---------------------------------------------------------------------------
# FSRS math — deterministic regression net (pin against mypalclara port)
# ---------------------------------------------------------------------------


def test_fsrs_initial_stability_per_grade():
    p = FsrsParams()
    # w[0..3] map directly to AGAIN/HARD/GOOD/EASY initial stability.
    assert initial_stability(Grade.AGAIN, p) == pytest.approx(0.212)
    assert initial_stability(Grade.HARD, p) == pytest.approx(1.2931)
    assert initial_stability(Grade.GOOD, p) == pytest.approx(2.3065)
    assert initial_stability(Grade.EASY, p) == pytest.approx(8.2956)


def test_fsrs_initial_difficulty_for_good():
    p = FsrsParams()
    # D0 = w[4] - exp(w[5] * (3-1)) + 1 = 6.4133 - exp(1.6668) + 1
    assert initial_difficulty(Grade.GOOD, p) == pytest.approx(2.118103970459015)


def test_fsrs_retrievability_at_zero_and_at_stability():
    # R(0, S) == 1.0 by definition (no time elapsed).
    assert retrievability(0.0, 5.0) == 1.0
    # By construction: R(S, S) == 0.9 (the 90% retention definition).
    assert retrievability(5.0, 5.0) == pytest.approx(0.9, rel=1e-12)
    # And monotonically decreasing past S.
    assert retrievability(10.0, 5.0) == pytest.approx(0.8458846451494336)


def test_fsrs_calculate_memory_score_formula():
    # base = 0.7 * R + 0.3 * R_s = 0.71 for (0.8, 0.5).
    assert calculate_memory_score(0.8, 0.5) == pytest.approx(0.71)
    # importance_weight multiplies through.
    assert calculate_memory_score(0.8, 0.5, 2.0) == pytest.approx(1.42)


def test_fsrs_infer_grade_from_signal_canonical_signals():
    assert infer_grade_from_signal("used_in_response") == Grade.GOOD
    assert infer_grade_from_signal("user_correction") == Grade.AGAIN
    assert infer_grade_from_signal("task_completed") == Grade.EASY
    # Unknown signals default to GOOD (from mypalclara).
    assert infer_grade_from_signal("totally-unknown") == Grade.GOOD


def test_fsrs_review_fresh_memory_initialises_state():
    """First review of a never-seen memory: stability/difficulty get the
    initial-from-grade values, current_r is 1.0 (no decay), review_count=1."""
    state = MemoryState()
    result = review(state, Grade.GOOD, review_time=datetime(2026, 1, 1))

    assert result.new_state.review_count == 1
    assert result.new_state.stability == pytest.approx(2.3065)
    assert result.new_state.difficulty == pytest.approx(2.118103970459015)
    assert result.retrievability_before == 1.0
    assert result.next_review_days == pytest.approx(2.3065)


def test_fsrs_update_stability_success_known_value():
    """Pin the success-update math so we'd notice a porting drift."""
    p = FsrsParams()
    d_good = initial_difficulty(Grade.GOOD, p)
    # S=2.3065 (initial GOOD), D=2.1181, R=0.9, grade=GOOD
    new_s = update_stability_success(2.3065, d_good, 0.9, Grade.GOOD, p)
    assert new_s == pytest.approx(88.61341362965777, rel=1e-9)


# ---------------------------------------------------------------------------
# Routes — mock-based (covers wiring + envelope)
# ---------------------------------------------------------------------------


def _fake_dynamics(memory_id: str = "m1", user_id: str = "u1", **overrides):
    base = MagicMock()
    base.memory_id = memory_id
    base.user_id = user_id
    base.stability = 2.3065
    base.difficulty = 2.118
    base.retrieval_strength = 1.0
    base.storage_strength = 0.5
    base.is_key = False
    base.importance_weight = 1.0
    base.category = None
    base.tags = None
    base.last_accessed_at = None
    base.access_count = 1
    base.created_at = datetime(2026, 5, 3)
    base.updated_at = datetime(2026, 5, 3)
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_promote_route_calls_service_and_returns_dynamics(client, mock_dynamics_service):
    mock_dynamics_service.promote.return_value = _fake_dynamics(access_count=1)
    resp = client.post(
        "/v1/memories/m1/promote",
        json={"user_id": "u1", "grade": 3, "signal_type": "used_in_response"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["memory_id"] == "m1"
    assert data["access_count"] == 1
    mock_dynamics_service.promote.assert_awaited_once_with(
        memory_id="m1", user_id="u1", grade=3, signal_type="used_in_response",
    )


def test_demote_route_calls_service(client, mock_dynamics_service):
    mock_dynamics_service.demote.return_value = _fake_dynamics(access_count=2)
    resp = client.post(
        "/v1/memories/m1/demote",
        json={"user_id": "u1", "reason": "user_correction"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["access_count"] == 2
    mock_dynamics_service.demote.assert_awaited_once_with(
        memory_id="m1", user_id="u1", reason="user_correction",
    )


def test_get_dynamics_route_404_when_missing(client, mock_dynamics_service):
    mock_dynamics_service.get_dynamics.return_value = None
    resp = client.get("/v1/memories/missing/dynamics?user_id=u1")
    assert resp.status_code == 404


def test_get_dynamics_route_returns_payload(client, mock_dynamics_service):
    mock_dynamics_service.get_dynamics.return_value = _fake_dynamics()
    resp = client.get("/v1/memories/m1/dynamics?user_id=u1")
    assert resp.status_code == 200
    assert resp.json()["data"]["memory_id"] == "m1"


def test_score_route_returns_breakdown(client, mock_dynamics_service):
    mock_dynamics_service.score.return_value = {
        "composite_score": 0.79,
        "fsrs_score": 0.65,
        "retrievability": 0.82,
        "storage_strength": 0.5,
    }
    resp = client.post(
        "/v1/memories/m1/score",
        json={"user_id": "u1", "semantic_score": 0.87},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["composite_score"] == pytest.approx(0.79)
    assert data["fsrs_score"] == pytest.approx(0.65)
    mock_dynamics_service.score.assert_awaited_once_with(
        memory_id="m1", user_id="u1", semantic_score=0.87,
    )


def test_prune_access_logs_route_returns_count(client, mock_dynamics_service):
    mock_dynamics_service.prune_access_logs.return_value = 7
    resp = client.post("/v1/maintenance/prune-access-logs?retention_days=30")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 7
    mock_dynamics_service.prune_access_logs.assert_awaited_once_with(retention_days=30)


def test_promote_route_rejects_invalid_grade(client, mock_dynamics_service):
    resp = client.post(
        "/v1/memories/m1/promote",
        json={"user_id": "u1", "grade": 9, "signal_type": "used_in_response"},
    )
    assert resp.status_code == 400
    mock_dynamics_service.promote.assert_not_awaited()
