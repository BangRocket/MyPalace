"""AuthContext — request-scoped identity and scope carrier."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

VALID_SCOPES: frozenset[str] = frozenset({"read", "write", "admin", "unlimited"})


@dataclass(frozen=True)
class AuthContext:
    """Identity attached to an authenticated request.

    `scopes` is an explicit set — admin does NOT auto-include write/read.
    Callers must request all scopes they want when minting a key, which
    forces intentional issuance.

    `tenant_id` (slice 2):
      - For tenant-bound keys: set from the key row; cannot be overridden.
      - For cross-tenant admin keys (key.tenant_id is None): None on the
        AuthContext, and the route handler must accept tenant_id from the
        request body/query (or fall back to settings.default_tenant_id).
      - When auth is disabled (test bypass): set to settings.default_tenant_id.
    """

    key_id: str
    label: str
    scopes: frozenset[str]
    tenant_id: str | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"forbidden: requires scope '{scope}'",
            )

    def resolve_tenant(self, request_tenant: str | None = None) -> str:
        """Return the effective tenant for this request.

        - Tenant-bound key: key tenant wins; conflicting request_tenant → 403.
        - Cross-tenant admin (tenant_id is None): use request_tenant;
          fall back to settings.default_tenant_id if absent.

        Phase 12: also seats the resolved tenant in
        ``mypalace.tenancy.current_tenant`` so any subsequent DB query
        in this request runs against the right schema. Idempotent —
        calling repeatedly with the same value is fine; calling with a
        different value (e.g. cross-tenant admin querying multiple
        tenants in one request) reseats it for the next query.
        """
        from mypalace.config import settings
        from mypalace.tenancy import set_current_tenant

        if self.tenant_id is not None:
            if request_tenant is not None and request_tenant != self.tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"cross-tenant access denied: key bound to "
                        f"'{self.tenant_id}', request specified '{request_tenant}'"
                    ),
                )
            resolved = self.tenant_id
        else:
            resolved = request_tenant or settings.default_tenant_id

        set_current_tenant(resolved)
        return resolved

    @classmethod
    def all_scopes(
        cls,
        key_id: str = "disabled",
        label: str = "auth-disabled",
        tenant_id: str | None = None,
    ) -> AuthContext:
        from mypalace.config import settings
        return cls(
            key_id=key_id,
            label=label,
            scopes=frozenset(VALID_SCOPES),
            tenant_id=tenant_id if tenant_id is not None else settings.default_tenant_id,
        )


def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency: pull the AuthContext attached by middleware."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return auth
