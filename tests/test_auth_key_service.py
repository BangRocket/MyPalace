"""Unit tests for KeyService logic that doesn't need DB."""

from __future__ import annotations

from mypalace.auth.key_service import (
    KEY_PREFIX_LITERAL,
    PREFIX_INDEX_LEN,
    RANDOM_PART_LEN,
    _gen_random,
    _hash,
    _split,
    _validate_scopes,
    _verify,
)
from mypalace.auth.usage import UsageTracker


class TestRandomGen:
    def test_random_length(self):
        for _ in range(20):
            assert len(_gen_random()) == RANDOM_PART_LEN

    def test_random_uses_alphanumeric_only(self):
        import string
        allowed = set(string.ascii_letters + string.digits)
        for _ in range(20):
            assert set(_gen_random()) <= allowed

    def test_random_is_unique(self):
        # Birthday paradox at 32-char base62 → essentially impossible to collide
        assert len({_gen_random() for _ in range(100)}) == 100


class TestSplit:
    def test_split_valid(self):
        plaintext = KEY_PREFIX_LITERAL + "a" * RANDOM_PART_LEN
        result = _split(plaintext)
        assert result is not None
        prefix_index, random_part = result
        assert prefix_index == "a" * PREFIX_INDEX_LEN
        assert random_part == "a" * RANDOM_PART_LEN

    def test_split_wrong_prefix(self):
        assert _split("pk_test_" + "a" * RANDOM_PART_LEN) is None
        assert _split("a" * 40) is None

    def test_split_wrong_length(self):
        assert _split(KEY_PREFIX_LITERAL + "abc") is None
        assert _split(KEY_PREFIX_LITERAL + "a" * (RANDOM_PART_LEN + 1)) is None

    def test_split_empty(self):
        assert _split("") is None


class TestHashVerify:
    def test_hash_then_verify(self):
        plaintext = "pk_live_" + "x" * RANDOM_PART_LEN
        h = _hash(plaintext)
        assert _verify(plaintext, h) is True

    def test_verify_wrong_password(self):
        h = _hash("pk_live_" + "x" * RANDOM_PART_LEN)
        assert _verify("pk_live_" + "y" * RANDOM_PART_LEN, h) is False

    def test_verify_malformed_hash(self):
        assert _verify("anything", "not-a-bcrypt-hash") is False


class TestValidateScopes:
    def test_valid_scopes_accepted(self):
        assert _validate_scopes(["read"]) == frozenset({"read"})
        assert _validate_scopes(["read", "write", "admin"]) == frozenset(
            {"read", "write", "admin"},
        )

    def test_invalid_scope_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="invalid scopes"):
            _validate_scopes(["read", "superuser"])

    def test_empty_scopes_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="at least one scope"):
            _validate_scopes([])


class TestUsageTracker:
    def test_first_call_returns_true(self):
        t = UsageTracker(debounce_seconds=60.0)
        assert t.should_update("k1") is True

    def test_second_call_within_debounce_returns_false(self):
        t = UsageTracker(debounce_seconds=60.0)
        t.should_update("k1")
        assert t.should_update("k1") is False

    def test_different_keys_independent(self):
        t = UsageTracker(debounce_seconds=60.0)
        assert t.should_update("k1") is True
        assert t.should_update("k2") is True

    def test_after_debounce_returns_true(self):
        t = UsageTracker(debounce_seconds=0.0)
        t.should_update("k1")
        # debounce of 0 should always return True (>= 0)
        assert t.should_update("k1") is True

    def test_reset(self):
        t = UsageTracker(debounce_seconds=60.0)
        t.should_update("k1")
        t.reset()
        assert t.should_update("k1") is True
