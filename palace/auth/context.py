"""AuthContext — request-scoped identity and scope carrier."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

VALID_SCOPES: frozenset[str] = frozenset({"read", "write", "admin"})


@dataclass(frozen=True)
class AuthContext:
    """Identity attached to an authenticated request.

    `scopes` is an explicit set — admin does NOT auto-include write/read.
    Callers must request all scopes they want when minting a key, which
    forces intentional issuance.
    """

    key_id: str
    label: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"forbidden: requires scope '{scope}'",
            )

    @classmethod
    def all_scopes(cls, key_id: str = "disabled", label: str = "auth-disabled") -> AuthContext:
        return cls(key_id=key_id, label=label, scopes=frozenset(VALID_SCOPES))


def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency: pull the AuthContext attached by middleware."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return auth
