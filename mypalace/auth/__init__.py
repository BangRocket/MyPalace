"""Auth: API keys, scopes, middleware (phase 3 slice 1)."""

from mypalace.auth.context import AuthContext
from mypalace.auth.key_service import key_service

__all__ = ["AuthContext", "key_service"]
