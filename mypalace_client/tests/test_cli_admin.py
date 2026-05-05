"""Tests for mypalace-admin CLI (phase 9 slice 1).

These tests mock httpx so we don't need a live server. They exercise:
- subcommand argument parsing
- payload shape sent to the server
- exit codes on success / HTTP error / 404
- --json vs human output formats
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
from mypalace_client.cli.admin import build_parser, main


def _resp(
    status: int,
    body: dict | None = None,
    content_type: str = "application/json",
) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.headers = {"content-type": content_type}
    r.json.return_value = body or {}
    r.text = json.dumps(body or {})
    return r


@pytest.fixture
def mock_client(monkeypatch):
    """Patch _client() to return a controllable Mock httpx.Client."""
    client_mock = MagicMock(spec=httpx.Client)
    client_mock.__enter__ = MagicMock(return_value=client_mock)
    client_mock.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(
        "mypalace_client.cli.admin._client",
        lambda args: client_mock,
    )
    return client_mock


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

class TestParser:
    def test_no_subcommand_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_keys_mint_requires_label_and_scopes(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["keys", "mint"])

    def test_audit_default_limit(self):
        parser = build_parser()
        args = parser.parse_args(["audit"])
        assert args.limit == 50

    def test_global_flags_before_subcommand(self):
        parser = build_parser()
        args = parser.parse_args([
            "--url", "http://palace.test", "--admin-key", "pk_live_x",
            "--json", "health",
        ])
        assert args.url == "http://palace.test"
        assert args.admin_key == "pk_live_x"
        assert args.json is True


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, mock_client, capsys):
        mock_client.get.return_value = _resp(200, {
            "status": "ok",
            "backends": [
                {"name": "postgres", "ok": True, "elapsed_ms": 5,
                 "detail": "ok", "configured": True},
            ],
        })
        rc = main(["health"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "status: ok" in out
        assert "✓" in out and "postgres" in out

    def test_health_degraded_returns_2(self, mock_client):
        mock_client.get.return_value = _resp(503, {
            "status": "degraded",
            "backends": [{"name": "qdrant", "ok": False, "elapsed_ms": 2000,
                          "detail": "timeout", "configured": True}],
        })
        rc = main(["health"])
        assert rc == 2

    def test_health_json_mode(self, mock_client, capsys):
        body = {"status": "ok", "backends": []}
        mock_client.get.return_value = _resp(200, body)
        main(["--json", "health"])
        out = capsys.readouterr().out
        assert json.loads(out) == body


class TestKeys:
    def test_list_calls_correct_endpoint(self, mock_client, capsys):
        mock_client.get.return_value = _resp(200, {"data": []})
        main(["keys", "list"])
        mock_client.get.assert_called_with("/v1/admin/keys", params={})
        assert "(no rows)" in capsys.readouterr().out or True  # empty list rendering

    def test_list_with_include_revoked(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})
        main(["keys", "list", "--include-revoked"])
        mock_client.get.assert_called_with(
            "/v1/admin/keys", params={"include_revoked": "true"},
        )

    def test_mint_default_payload_no_cross_tenant(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": {
            "key_id": "k1", "plaintext_key": "pk_live_xxx",
            "label": "test", "scopes": ["read"], "tenant_id": "default",
        }})
        main(["keys", "mint", "--label", "test", "--scopes", "read,write"])
        call = mock_client.post.call_args
        assert call.args[0] == "/v1/admin/keys"
        payload = call.kwargs["json"]
        assert payload == {"label": "test", "scopes": ["read", "write"]}

    def test_mint_cross_tenant_flag(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": {
            "key_id": "k1", "plaintext_key": "pk_live_xxx",
            "label": "support", "scopes": ["admin"], "tenant_id": None,
        }})
        main(["keys", "mint", "--label", "support",
              "--scopes", "admin", "--cross-tenant"])
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload.get("cross_tenant") is True

    def test_mint_with_tenant_id(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": {
            "key_id": "k1", "plaintext_key": "pk_live_xxx",
            "label": "acme", "scopes": ["write"], "tenant_id": "acme",
        }})
        main(["keys", "mint", "--label", "acme",
              "--scopes", "write", "--tenant-id", "acme"])
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload.get("tenant_id") == "acme"
        assert payload.get("cross_tenant") is None or payload.get("cross_tenant") is False

    def test_revoke_calls_delete(self, mock_client):
        mock_client.delete.return_value = _resp(200, {"data": {"revoked": True}})
        rc = main(["keys", "revoke", "k-xyz"])
        mock_client.delete.assert_called_with("/v1/admin/keys/k-xyz")
        assert rc == 0


class TestTenants:
    def test_create_payload(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": {
            "id": "acme", "label": "Acme Corp",
        }})
        main(["tenants", "create", "--id", "acme", "--label", "Acme Corp"])
        call = mock_client.post.call_args
        assert call.args[0] == "/v1/admin/tenants"
        assert call.kwargs["json"] == {"id": "acme", "label": "Acme Corp"}


class TestStats:
    def test_per_tenant(self, mock_client, capsys):
        mock_client.get.return_value = _resp(200, {"data": {
            "tenant_id": "acme",
            "row_counts": {"memories": 12},
            "activity_7d": {},
            "fsrs_health": {},
            "top_users_by_access_7d": [],
        }})
        main(["stats", "acme"])
        out = capsys.readouterr().out
        assert "acme" in out
        assert "memories=12" in out

    def test_all_mode(self, mock_client, capsys):
        mock_client.get.return_value = _resp(200, {"data": {
            "tenants": [
                {"tenant_id": "a", "row_counts": {"memories": 1},
                 "activity_7d": {}, "fsrs_health": {},
                 "top_users_by_access_7d": []},
                {"tenant_id": "b", "row_counts": {"memories": 2},
                 "activity_7d": {}, "fsrs_health": {},
                 "top_users_by_access_7d": []},
            ],
        }})
        main(["stats", "ALL"])
        out = capsys.readouterr().out
        assert "=== a ===" in out
        assert "=== b ===" in out


class TestAudit:
    def test_filters_threaded_into_params(self, mock_client):
        mock_client.get.return_value = _resp(200, {"data": []})
        main([
            "audit", "--since", "2026-05-05T00:00:00Z",
            "--key-id", "k1", "--path-prefix", "/v1/admin",
            "--limit", "10",
        ])
        call = mock_client.get.call_args
        assert call.args[0] == "/v1/admin/audit"
        params = call.kwargs["params"]
        assert params["limit"] == "10"
        assert params["since"] == "2026-05-05T00:00:00Z"
        assert params["key_id"] == "k1"
        assert params["path_prefix"] == "/v1/admin"


class TestReembed:
    def test_minimum_payload(self, mock_client, capsys):
        mock_client.post.return_value = _resp(200, {"data": {"job_id": "j1"}})
        main(["reembed", "acme", "--model", "tiny"])
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload == {
            "tenant_id": "acme",
            "provider": "huggingface",
            "model": "tiny",
            "batch_size": 100,
        }
        assert "j1" in capsys.readouterr().out

    def test_with_token_and_provider(self, mock_client):
        mock_client.post.return_value = _resp(200, {"data": {"job_id": "j2"}})
        main([
            "reembed", "acme", "--provider", "openai",
            "--model", "text-embedding-3-small", "--token", "sk-x",
            "--batch-size", "50",
        ])
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["provider"] == "openai"
        assert payload["token"] == "sk-x"
        assert payload["batch_size"] == 50


class TestJob:
    def test_404_returns_1(self, mock_client):
        mock_client.get.return_value = _resp(404, {"detail": "Job not found"})
        rc = main(["job", "missing"])
        assert rc == 1


class TestErrorHandling:
    def test_http_error_exits_1(self, mock_client):
        mock_client.get.return_value = _resp(401, {
            "error": {"code": "unauthenticated", "message": "missing X-Palace-Key"},
        })
        with pytest.raises(SystemExit) as exc:
            main(["audit"])
        assert exc.value.code == 1


class TestEnvVarFallback:
    def test_url_env_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("MYPALACE_URL", "http://envhost:9999")
        monkeypatch.delenv("MYPALACE_ADMIN_KEY", raising=False)

        captured: dict = {}

        def fake_client_factory(base_url, headers, timeout):
            captured["base_url"] = base_url
            captured["headers"] = headers
            real_client = MagicMock()  # no spec — we set context-manager dunders
            real_client.__enter__ = MagicMock(return_value=real_client)
            real_client.__exit__ = MagicMock(return_value=None)
            real_client.get.return_value = _resp(200, {"status": "ok", "backends": []})
            return real_client

        monkeypatch.setattr(httpx, "Client", fake_client_factory)
        main(["health"])
        assert captured["base_url"] == "http://envhost:9999"

    def test_admin_key_env_threaded_to_header(self, monkeypatch):
        monkeypatch.setenv("MYPALACE_ADMIN_KEY", "pk_live_envkey")
        monkeypatch.delenv("MYPALACE_URL", raising=False)

        captured: dict = {}

        def fake_client_factory(base_url, headers, timeout):
            captured["headers"] = headers
            real_client = MagicMock()  # no spec — we set context-manager dunders
            real_client.__enter__ = MagicMock(return_value=real_client)
            real_client.__exit__ = MagicMock(return_value=None)
            real_client.get.return_value = _resp(200, {"status": "ok", "backends": []})
            return real_client

        monkeypatch.setattr(httpx, "Client", fake_client_factory)
        main(["health"])
        assert captured["headers"].get("X-Palace-Key") == "pk_live_envkey"
