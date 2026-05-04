"""Slice-4 tests: trigger matchers + IntentionService routes (mock-based).

Trigger tests pin deterministic input -> output to catch porting drift from
mypalclara's core/intentions.py. Route tests use the slice-1/2/3 mock client
pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from palace.intentions.triggers import (
    _check_context_trigger,
    _check_keyword_trigger,
    _check_time_trigger,
    _check_topic_trigger,
    evaluate_trigger,
)

# ---------------------------------------------------------------------------
# Trigger matchers — deterministic regression net
# ---------------------------------------------------------------------------


def test_keyword_trigger_case_insensitive_default():
    fired, details = _check_keyword_trigger(
        "When is the MEETING tomorrow?",
        {"keywords": ["meeting"]},
    )
    assert fired is True
    assert details["matched_keywords"] == ["meeting"]


def test_keyword_trigger_case_sensitive_no_match():
    fired, _ = _check_keyword_trigger(
        "When is the MEETING tomorrow?",
        {"keywords": ["meeting"], "case_sensitive": True},
    )
    assert fired is False


def test_keyword_trigger_regex_pattern_matches():
    fired, details = _check_keyword_trigger(
        "Let's review PR-1234 today",
        {"keywords": [], "regex": r"PR-\d+"},
    )
    assert fired is True
    assert any(k.startswith("regex:") for k in details["matched_keywords"])


def test_topic_trigger_word_overlap_above_threshold():
    fired, details = _check_topic_trigger(
        "I missed the project deadline yesterday",
        {"topic": "project deadline", "threshold": 0.5},
    )
    assert fired is True
    assert details["topic"] == "project deadline"
    assert details["similarity"] >= 0.5


def test_topic_trigger_below_threshold_does_not_fire():
    fired, _ = _check_topic_trigger(
        "Hello, how are you doing today?",
        {"topic": "project deadline", "threshold": 0.7},
    )
    assert fired is False


def test_time_trigger_at_in_the_past_fires():
    past = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None).isoformat() + "Z"
    fired, details = _check_time_trigger(
        datetime.now(UTC).replace(tzinfo=None),
        {"at": past},
    )
    assert fired is True
    assert details["type"] == "at"


def test_time_trigger_after_in_the_future_does_not_fire():
    future = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat() + "Z"
    fired, _ = _check_time_trigger(
        datetime.now(UTC).replace(tzinfo=None),
        {"after": future},
    )
    assert fired is False


def test_context_trigger_partial_match_via_channel_substring():
    fired, details = _check_context_trigger(
        {"channel_name": "general-chat", "is_dm": False},
        {"conditions": {"channel_name": "general"}},
    )
    assert fired is True
    assert details["matched_conditions"]["channel_name"] == "general-chat"


def test_context_trigger_is_dm_mismatch_fails():
    fired, _ = _check_context_trigger(
        {"is_dm": True},
        {"conditions": {"is_dm": False}},
    )
    assert fired is False


def test_evaluate_trigger_dispatches_by_type():
    fired_kw, _ = evaluate_trigger(
        "meeting at 3", {"type": "keyword", "keywords": ["meeting"]}, {},
    )
    assert fired_kw is True

    fired_tt, _ = evaluate_trigger(
        "ping",
        {"type": "topic", "topic": "deadline", "threshold": 0.7},
        {},
    )
    assert fired_tt is False  # quick_keywords absent → falls through to topic; no overlap


def test_evaluate_trigger_topic_quick_keyword_filter_skips_when_absent():
    # quick_keywords present, none in message → short-circuit to no-fire even
    # if word-overlap would have matched.
    fired, _ = evaluate_trigger(
        "deadline",
        {
            "type": "topic",
            "topic": "deadline",
            "threshold": 0.5,
            "quick_keywords": ["xyzzy"],
        },
        {},
    )
    assert fired is False


# ---------------------------------------------------------------------------
# Route tests — mock IntentionService
# ---------------------------------------------------------------------------


def _fake_intention(
    intention_id: str = "i1",
    user_id: str = "u1",
    fired: bool = False,
):
    """Build a stand-in object with the attributes IntentionOut.from_intention reads."""
    return type(
        "Intention",
        (),
        {
            "id": intention_id,
            "user_id": user_id,
            "agent_id": "clara",
            "content": "Remind about meeting",
            "source_memory_id": None,
            "trigger_conditions": {"type": "keyword", "keywords": ["meeting"]},
            "priority": 0,
            "fired": fired,
            "fire_once": True,
            "created_at": datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
            "expires_at": None,
            "fired_at": None,
        },
    )()


def test_set_intention_route_calls_service(client, mock_intention_service):
    mock_intention_service.set.return_value = _fake_intention()
    resp = client.post(
        "/v1/intentions",
        json={
            "user_id": "u1",
            "content": "Remind about meeting",
            "trigger_conditions": {"type": "keyword", "keywords": ["meeting"]},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "i1"
    mock_intention_service.set.assert_awaited_once()


def test_check_intentions_route_returns_fired_list(client, mock_intention_service):
    mock_intention_service.check.return_value = [
        {
            "id": "i1",
            "content": "Remind about meeting",
            "trigger_type": "keyword",
            "priority": 5,
            "match_details": {"matched_keywords": ["meeting"]},
            "source_memory_id": None,
        },
    ]
    resp = client.post(
        "/v1/intentions/check",
        json={"user_id": "u1", "message": "When is the meeting?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["count"] == 1
    assert body["data"][0]["trigger_type"] == "keyword"


def test_format_intentions_route_returns_text(client, mock_intention_service):
    mock_intention_service.format_for_prompt.return_value = "## Reminders\n- a\n- b"
    resp = client.post(
        "/v1/intentions/format",
        json={
            "intentions": [
                {"id": "i1", "content": "a", "trigger_type": "keyword",
                 "priority": 0, "match_details": {}, "source_memory_id": None},
            ],
            "max": 3,
        },
    )
    assert resp.status_code == 200
    assert "Reminders" in resp.json()["data"]["text"]


def test_list_user_intentions_route(client, mock_intention_service):
    mock_intention_service.list_for_user.return_value = [_fake_intention()]
    resp = client.get("/v1/users/u1/intentions?fired=false&limit=10")
    assert resp.status_code == 200
    assert resp.json()["meta"]["count"] == 1
    mock_intention_service.list_for_user.assert_awaited_once_with(
        user_id="u1", fired_filter="false", limit=10,
    )


def test_delete_intention_route_404_when_missing(client, mock_intention_service):
    mock_intention_service.delete.return_value = False
    resp = client.delete("/v1/intentions/missing")
    assert resp.status_code == 404


def test_delete_intention_route_deletes(client, mock_intention_service):
    mock_intention_service.delete.return_value = True
    resp = client.delete("/v1/intentions/i1")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_cleanup_intentions_route(client, mock_intention_service):
    mock_intention_service.cleanup_expired.return_value = 4
    resp = client.post("/v1/maintenance/cleanup-intentions")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 4
