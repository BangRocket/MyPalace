"""Unit tests for the route → scope mapping table."""

from mypalace.auth.scopes import is_public, required_scope


class TestPublicPaths:
    def test_health_is_public(self):
        assert is_public("/health")

    def test_docs_is_public(self):
        assert is_public("/docs")
        assert is_public("/redoc")
        assert is_public("/openapi.json")

    def test_docs_assets_are_public(self):
        assert is_public("/docs/swagger-ui-bundle.js")
        assert is_public("/redoc/something")

    def test_unrelated_path_not_public(self):
        assert not is_public("/v1/memories")
        assert not is_public("/v1/admin/keys")


class TestRequiredScope:
    def test_admin_paths_require_admin(self):
        assert required_scope("POST", "/v1/admin/keys") == "admin"
        assert required_scope("GET", "/v1/admin/keys") == "admin"
        assert required_scope("DELETE", "/v1/admin/keys/abc") == "admin"

    def test_maintenance_requires_admin(self):
        assert required_scope("POST", "/v1/maintenance/cleanup-intentions") == "admin"
        assert required_scope("POST", "/v1/maintenance/prune-access-logs") == "admin"

    def test_search_endpoints_are_read(self):
        assert required_scope("POST", "/v1/memories/search") == "read"
        assert required_scope("POST", "/v1/memories/list") == "read"
        assert required_scope("POST", "/v1/episodes/search") == "read"

    def test_get_endpoints_are_read(self):
        assert required_scope("GET", "/v1/memories/abc") == "read"
        assert required_scope("GET", "/v1/users/u1/memories") == "read"

    def test_context_assembly_is_read(self):
        assert required_scope("POST", "/v1/context") == "read"
        assert required_scope("POST", "/v1/context/layered") == "read"

    def test_intentions_check_is_read(self):
        assert required_scope("POST", "/v1/intentions/check") == "read"
        assert required_scope("POST", "/v1/intentions/format") == "read"

    def test_create_endpoints_require_write(self):
        assert required_scope("POST", "/v1/memories") == "write"
        assert required_scope("PATCH", "/v1/memories/abc") == "write"
        assert required_scope("DELETE", "/v1/memories/abc") == "write"
        assert required_scope("POST", "/v1/sessions") == "write"
        assert required_scope("POST", "/v1/intentions") == "write"

    def test_unknown_path_defaults_to_write(self):
        assert required_scope("POST", "/v1/something/new") == "write"
