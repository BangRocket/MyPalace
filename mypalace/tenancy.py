"""Per-request tenant context (phase 12 slice 1).

A single ``ContextVar`` carries the resolved tenant id for the current
request / worker job. Two consumers read it:

- ``mypalace.database`` — installs an ``after_begin`` SQLAlchemy event
  that runs ``SET LOCAL search_path`` when ``settings.tenant_schema_mode``
  is ``"schema"``.
- Any future code that wants to know "which tenant am I serving right
  now" without threading it through every signature.

Default mode (``"table"``) is the existing table-level isolation: the
contextvar is still populated for diagnostics but no SQL behavior
changes. Operators flip the flag in 12.3 once shadow-copied data and
schemas are in place (see docs/per-tenant-schemas-design.md).
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager

# Default None so callers can distinguish "not set yet" from "explicit
# default tenant" — the latter is a deliberate choice the request made;
# the former means we shouldn't be running a query yet.
_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mypalace_current_tenant", default=None,
)

# Schema names go straight into SQL as identifiers, so we *must* validate
# before composing the SET LOCAL statement. This regex matches the same
# tenant_id rules already enforced in mypalace.auth.tenant.is_valid_tenant_id
# (lowercase letters, digits, underscore, hyphen; 1-32 chars). Kept local
# to avoid an import cycle.
_SCHEMA_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def set_current_tenant(tenant_id: str | None) -> contextvars.Token:
    """Install ``tenant_id`` as the current tenant for this context.

    Returns the Token so callers can ``reset(token)`` to restore the
    previous value (rarely needed — request lifetimes are short and
    contextvar values don't leak across asyncio tasks).
    """
    return _current_tenant.set(tenant_id)


def current_tenant() -> str | None:
    """Return the tenant id active for the current context, or None."""
    return _current_tenant.get()


def is_valid_schema_name(tenant_id: str) -> bool:
    """Cheap defence against SQL injection via a malformed tenant_id.

    Tenant ids that pass mypalace.auth.tenant.is_valid_tenant_id will
    also pass this — same character class, same length cap.
    """
    return bool(_SCHEMA_NAME_RE.match(tenant_id))


@contextmanager
def tenant_scope(tenant_id: str | None):
    """Context manager: set the current tenant for the duration of the block.

    Useful in worker handlers and tests where there's no AuthMiddleware
    to populate the contextvar automatically.
    """
    token = set_current_tenant(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)
