"""Admin routes: API key CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from palace.api.common import ApiResponse, Meta
from palace.auth.key_service import key_service
from palace.auth.tenant import is_valid_tenant_id
from palace.models import ApiKey

router = APIRouter()


class CreateKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    tenant_id: str | None = Field(
        default=None,
        description=(
            "Tenant binding. None = cross-tenant admin key (admins only). "
            "If omitted, defaults to settings.default_tenant_id."
        ),
    )
    cross_tenant: bool = Field(
        default=False,
        description="Set true to mint a cross-tenant admin key (tenant_id=None).",
    )


class ApiKeyOut(BaseModel):
    key_id: str
    key_prefix: str
    label: str
    scopes: list[str]
    tenant_id: str | None
    created_at: str | None
    last_used_at: str | None
    revoked_at: str | None

    @classmethod
    def from_row(cls, row: ApiKey) -> ApiKeyOut:
        return cls(
            key_id=row.id,
            key_prefix=row.key_prefix,
            label=row.label,
            scopes=list(row.scopes or []),
            tenant_id=row.tenant_id,
            created_at=row.created_at.isoformat() if row.created_at else None,
            last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
            revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
        )


class CreatedKeyOut(BaseModel):
    key_id: str
    plaintext_key: str
    label: str
    scopes: list[str]
    tenant_id: str | None
    created_at: str | None


@router.post("/keys", response_model=ApiResponse[CreatedKeyOut])
async def create_key(req: CreateKeyRequest) -> Any:
    from palace.config import settings

    if req.cross_tenant:
        bound_tenant: str | None = None
    else:
        bound_tenant = req.tenant_id or settings.default_tenant_id
        if not is_valid_tenant_id(bound_tenant):
            raise HTTPException(
                status_code=400,
                detail=f"invalid_tenant_id: {bound_tenant!r}",
            )
    try:
        created = await key_service.create_key(
            label=req.label, scopes=req.scopes, tenant_id=bound_tenant,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    out = CreatedKeyOut(
        key_id=created.api_key.id,
        plaintext_key=created.plaintext,
        label=created.api_key.label,
        scopes=list(created.api_key.scopes or []),
        tenant_id=created.api_key.tenant_id,
        created_at=(
            created.api_key.created_at.isoformat() if created.api_key.created_at else None
        ),
    )
    return ApiResponse(data=out, meta=Meta(count=1))


@router.get("/keys", response_model=ApiResponse[list[ApiKeyOut]])
async def list_keys(include_revoked: bool = False) -> Any:
    rows = await key_service.list_keys(include_revoked=include_revoked)
    data = [ApiKeyOut.from_row(r) for r in rows]
    return ApiResponse(data=data, meta=Meta(count=len(data)))


@router.delete("/keys/{key_id}", response_model=ApiResponse[dict])
async def revoke_key(key_id: str) -> Any:
    ok = await key_service.revoke(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found")
    return ApiResponse(data={"revoked": True}, meta=Meta(count=1))
