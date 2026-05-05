"""Tests for the /admin/* SPA mount + public-path classification (phase 13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mypalace.auth.scopes import is_public

UI_DIST = Path(__file__).parent.parent / "apps" / "admin-ui" / "dist"


class TestPublicPathClassification:
    @pytest.mark.parametrize(
        "path",
        [
            "/admin",
            "/admin/",
            "/admin/login",
            "/admin/tenants",
            "/admin/assets/index-abc.js",
            "/admin/assets/index-abc.css",
        ],
    )
    def test_admin_paths_are_public(self, path):
        # The page itself must load before auth so the operator can
        # see the login form. The /v1/admin/* API calls the UI makes
        # afterwards still require admin scope.
        assert is_public(path)

    def test_v1_admin_remains_authed(self):
        # Tripwire: a refactor that broadened the admin allowlist to
        # include the API would leak the entire admin surface.
        assert not is_public("/v1/admin/tenants")
        assert not is_public("/v1/admin/keys")


class TestSpaServing:
    @pytest.mark.skipif(
        not (UI_DIST / "index.html").exists(),
        reason="UI bundle not built — run `cd apps/admin-ui && npm run build`",
    )
    def test_unknown_admin_path_serves_index(self, client):
        # SPA routing: any unknown path under /admin returns the same
        # index.html so React Router can take over.
        r = client.get("/admin/some/deep/nonexistent/route")
        assert r.status_code == 200
        assert "<!doctype html>" in r.text.lower()
        assert "<div id=\"root\">" in r.text

    @pytest.mark.skipif(
        not (UI_DIST / "index.html").exists(),
        reason="UI bundle not built",
    )
    def test_root_admin_serves_index(self, client):
        r = client.get("/admin/")
        assert r.status_code == 200
        assert "<!doctype html>" in r.text.lower()
