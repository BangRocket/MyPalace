"""Tests for the /v1/admin/keys endpoints (with auth bypassed)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from palace.auth.key_service import CreatedKey
from palace.models import ApiKey


def _row(
    *,
    key_id: str = "k1",
    label: str = "test",
    scopes: list[str] | None = None,
    revoked: bool = False,
) -> ApiKey:
    row = MagicMock(spec=ApiKey)
    row.id = key_id
    row.key_prefix = "abcd1234"
    row.label = label
    row.scopes = scopes or ["read"]
    row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row.last_used_at = None
    row.revoked_at = datetime(2026, 1, 2, tzinfo=UTC) if revoked else None
    return row


class TestCreateKey:
    def test_create_key_returns_plaintext(self, client, mock_key_service):
        api_row = _row(key_id="new1", label="new-key", scopes=["read", "write"])
        mock_key_service.create_key.return_value = CreatedKey(
            api_key=api_row,
            plaintext="pk_live_secretsecretsecretsecretsec1",
        )
        r = client.post(
            "/v1/admin/keys",
            json={"label": "new-key", "scopes": ["read", "write"]},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["key_id"] == "new1"
        assert data["plaintext_key"].startswith("pk_live_")
        assert data["label"] == "new-key"
        assert data["scopes"] == ["read", "write"]
        mock_key_service.create_key.assert_awaited_once_with(
            label="new-key", scopes=["read", "write"],
        )

    def test_create_key_invalid_scope_returns_422(self, client, mock_key_service):
        mock_key_service.create_key.side_effect = ValueError("invalid scopes: ['superuser']")
        r = client.post(
            "/v1/admin/keys",
            json={"label": "bad", "scopes": ["superuser"]},
        )
        assert r.status_code == 422

    def test_create_key_empty_scopes_rejected_by_pydantic(self, client):
        r = client.post(
            "/v1/admin/keys",
            json={"label": "bad", "scopes": []},
        )
        assert r.status_code == 422


class TestListKeys:
    def test_list_keys_default_excludes_revoked(self, client, mock_key_service):
        mock_key_service.list_keys.return_value = [_row(key_id="k1")]
        r = client.get("/v1/admin/keys")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["key_id"] == "k1"
        # No plaintext, no hash anywhere
        assert "plaintext_key" not in data[0]
        assert "key_hash" not in data[0]
        mock_key_service.list_keys.assert_awaited_once_with(include_revoked=False)

    def test_list_keys_can_include_revoked(self, client, mock_key_service):
        mock_key_service.list_keys.return_value = [
            _row(key_id="k1"),
            _row(key_id="k2", revoked=True),
        ]
        r = client.get("/v1/admin/keys?include_revoked=true")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        mock_key_service.list_keys.assert_awaited_once_with(include_revoked=True)


class TestRevokeKey:
    def test_revoke_existing_key(self, client, mock_key_service):
        mock_key_service.revoke.return_value = True
        r = client.delete("/v1/admin/keys/k1")
        assert r.status_code == 200
        assert r.json()["data"]["revoked"] is True
        mock_key_service.revoke.assert_awaited_once_with("k1")

    def test_revoke_missing_key_returns_404(self, client, mock_key_service):
        mock_key_service.revoke.return_value = False
        r = client.delete("/v1/admin/keys/nope")
        assert r.status_code == 404
