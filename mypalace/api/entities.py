"""Admin endpoints for the entity-alias registry (phase 10 slice 1).

These live under /v1/admin/entities/* — operators register identifier→
canonical-name mappings used by graph node labelling and any other
display surface that wants to show a human name instead of a platform id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.database import async_session
from mypalace.entity_service import entity_service
from mypalace.models import EntityAlias

router = APIRouter()


class RegisterAliasRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)
    canonical_name: str = Field(min_length=1, max_length=200)
    source: str = Field(default="manual", max_length=20)


class AliasOut(BaseModel):
    identifier: str
    canonical_name: str
    source: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: EntityAlias) -> AliasOut:
        return cls(
            identifier=row.identifier,
            canonical_name=row.canonical_name,
            source=row.source,
            tenant_id=row.tenant_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ResolveOut(BaseModel):
    identifier: str
    resolved: str
    matched: bool


@router.post("/entities/aliases", response_model=ApiResponse[AliasOut])
async def register_alias(
    req: RegisterAliasRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> Any:
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    row = await entity_service.register(
        req.identifier, req.canonical_name,
        tenant_id=resolved, source=req.source,
    )
    return ApiResponse(data=AliasOut.from_row(row), meta=Meta(count=1))


@router.get("/entities/aliases", response_model=ApiResponse[list[AliasOut]])
async def list_aliases(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(default=100, ge=1, le=1000),
) -> Any:
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    async with async_session() as db:
        result = await db.execute(
            select(EntityAlias)
            .where(EntityAlias.tenant_id == resolved)
            .order_by(EntityAlias.canonical_name)
            .limit(limit),
        )
        rows = result.scalars().all()
    return ApiResponse(
        data=[AliasOut.from_row(r) for r in rows],
        meta=Meta(count=len(rows)),
    )


@router.get("/entities/resolve", response_model=ApiResponse[ResolveOut])
async def resolve_identifier(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    identifier: str = Query(..., min_length=1, max_length=200),
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> Any:
    resolved_tenant = auth.resolve_tenant(request_tenant=tenant_id)
    name = await entity_service.resolve(identifier, tenant_id=resolved_tenant)
    return ApiResponse(
        data=ResolveOut(
            identifier=identifier,
            resolved=name,
            matched=(name != identifier),
        ),
        meta=Meta(count=1),
    )


@router.delete("/entities/aliases/{identifier}", status_code=204)
async def delete_alias(
    identifier: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> None:
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    async with async_session() as db:
        result = await db.execute(
            select(EntityAlias)
            .where(EntityAlias.tenant_id == resolved)
            .where(EntityAlias.identifier == identifier),
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"alias not found: {identifier!r}")
        await db.delete(row)
        await db.commit()
    entity_service.invalidate_cache(resolved)
