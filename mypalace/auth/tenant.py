"""Tenant ID validation."""

from __future__ import annotations

import re

from fastapi import HTTPException

# Lowercase alphanumeric + underscore, 1–32 chars. Safe in Qdrant collection
# names, URLs, and JSON keys.
_TENANT_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def validate_tenant_id(tenant_id: str) -> str:
    """Return the tenant_id unchanged if valid, else raise HTTPException(400)."""
    if not isinstance(tenant_id, str) or not _TENANT_ID_RE.fullmatch(tenant_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid_tenant_id: must match [a-z0-9_]{1,32} "
                f"(got {tenant_id!r})"
            ),
        )
    return tenant_id


def is_valid_tenant_id(tenant_id: str) -> bool:
    return isinstance(tenant_id, str) and bool(_TENANT_ID_RE.fullmatch(tenant_id))
