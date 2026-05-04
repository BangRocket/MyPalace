"""Unit tests for tenant_id validation + AuthContext.resolve_tenant."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from palace.auth.context import AuthContext
from palace.auth.tenant import is_valid_tenant_id, validate_tenant_id


class TestValidateTenantId:
    def test_valid_basic(self):
        assert validate_tenant_id("default") == "default"
        assert validate_tenant_id("tenant_a") == "tenant_a"
        assert validate_tenant_id("abc123") == "abc123"

    def test_valid_max_length(self):
        long = "a" * 32
        assert validate_tenant_id(long) == long

    def test_invalid_uppercase(self):
        with pytest.raises(HTTPException) as exc:
            validate_tenant_id("Default")
        assert exc.value.status_code == 400

    def test_invalid_dash(self):
        with pytest.raises(HTTPException):
            validate_tenant_id("tenant-a")

    def test_invalid_space(self):
        with pytest.raises(HTTPException):
            validate_tenant_id("tenant a")

    def test_invalid_too_long(self):
        with pytest.raises(HTTPException):
            validate_tenant_id("a" * 33)

    def test_invalid_empty(self):
        with pytest.raises(HTTPException):
            validate_tenant_id("")

    def test_invalid_non_string(self):
        with pytest.raises(HTTPException):
            validate_tenant_id(123)  # type: ignore[arg-type]

    def test_is_valid_helper(self):
        assert is_valid_tenant_id("ok")
        assert not is_valid_tenant_id("BAD")
        assert not is_valid_tenant_id("")


class TestResolveTenant:
    def test_bound_key_returns_its_tenant(self):
        ctx = AuthContext(
            key_id="k1", label="t", scopes=frozenset({"read"}), tenant_id="acme",
        )
        assert ctx.resolve_tenant() == "acme"
        assert ctx.resolve_tenant(request_tenant=None) == "acme"
        assert ctx.resolve_tenant(request_tenant="acme") == "acme"

    def test_bound_key_rejects_conflicting_request(self):
        ctx = AuthContext(
            key_id="k1", label="t", scopes=frozenset({"read"}), tenant_id="acme",
        )
        with pytest.raises(HTTPException) as exc:
            ctx.resolve_tenant(request_tenant="other")
        assert exc.value.status_code == 403
        assert "cross-tenant" in str(exc.value.detail)

    def test_cross_tenant_admin_uses_request(self):
        ctx = AuthContext(
            key_id="k1", label="admin", scopes=frozenset({"admin"}), tenant_id=None,
        )
        assert ctx.resolve_tenant(request_tenant="acme") == "acme"

    def test_cross_tenant_admin_falls_back_to_default(self):
        ctx = AuthContext(
            key_id="k1", label="admin", scopes=frozenset({"admin"}), tenant_id=None,
        )
        # In tests PALACE_DEFAULT_TENANT_ID="test" (set in conftest)
        from palace.config import settings
        assert ctx.resolve_tenant() == settings.default_tenant_id

    def test_all_scopes_helper_inherits_default_tenant(self):
        ctx = AuthContext.all_scopes()
        from palace.config import settings
        assert ctx.tenant_id == settings.default_tenant_id
