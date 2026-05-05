"""Admin endpoints for personality trait CRUD (phase 10 slice 2).

Mounts under /v1/admin/personality/*. Operators inspect what the agent
believes about itself, manually seed traits, or correct a bad LLM
evolution decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.models import PersonalityTrait
from mypalace.personality_service import DEFAULT_AGENT_ID, personality_service

router = APIRouter()


class TraitOut(BaseModel):
    id: str
    tenant_id: str
    agent_id: str
    category: str
    trait_key: str
    content: str
    source: str
    reason: str | None
    active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: PersonalityTrait) -> TraitOut:
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            agent_id=row.agent_id,
            category=row.category,
            trait_key=row.trait_key,
            content=row.content,
            source=row.source,
            reason=row.reason,
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class CreateTraitRequest(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    trait_key: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)
    source: str = Field(default="manual", max_length=20)
    reason: str | None = None
    agent_id: str = Field(default=DEFAULT_AGENT_ID, max_length=64)


class UpdateTraitRequest(BaseModel):
    content: str = Field(min_length=1)
    reason: str | None = None
    source: str = Field(default="manual", max_length=20)


@router.get("/personality/traits", response_model=ApiResponse[list[TraitOut]])
async def list_traits(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
    agent_id: str = Query(default=DEFAULT_AGENT_ID, max_length=64),
) -> Any:
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    rows = await personality_service.list_active(
        agent_id=agent_id, tenant_id=resolved,
    )
    return ApiResponse(
        data=[TraitOut.from_row(r) for r in rows], meta=Meta(count=len(rows)),
    )


@router.post("/personality/traits", response_model=ApiResponse[TraitOut])
async def create_trait(
    req: CreateTraitRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> Any:
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    row = await personality_service.add(
        category=req.category,
        trait_key=req.trait_key,
        content=req.content,
        source=req.source,
        reason=req.reason,
        agent_id=req.agent_id,
        tenant_id=resolved,
    )
    return ApiResponse(data=TraitOut.from_row(row), meta=Meta(count=1))


@router.patch(
    "/personality/traits/{trait_id}", response_model=ApiResponse[TraitOut],
)
async def update_trait(
    trait_id: str,
    req: UpdateTraitRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    try:
        row = await personality_service.update(
            trait_id=trait_id, content=req.content,
            reason=req.reason, source=req.source,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ApiResponse(data=TraitOut.from_row(row), meta=Meta(count=1))


@router.delete("/personality/traits/{trait_id}", status_code=204)
async def delete_trait(
    trait_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    reason: str | None = Query(default=None),
) -> None:
    removed = await personality_service.remove(
        trait_id=trait_id, reason=reason, source="manual",
    )
    if not removed:
        raise HTTPException(status_code=404, detail=f"trait not found: {trait_id}")
