"""Auth: API keys, scopes, middleware (phase 3 slice 1)."""

from palace.auth.context import AuthContext
from palace.auth.key_service import key_service

__all__ = ["AuthContext", "key_service"]
