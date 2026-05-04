"""Admin tenants CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.tenant import validate_tenant_id
from mypalace.database import async_session
from mypalace.models import (
    ApiKey,
    Intention,
    Memory,
    NarrativeArc,
    Tenant,
    utcnow,
)
from mypalace.models import Session as SessionModel

router = APIRouter()


class CreateTenantRequest(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=100)


class TenantOut(BaseModel):
    id: str
    label: str
    created_at: str | None

    @classmethod
    def from_row(cls, row: Tenant) -> TenantOut:
        return cls(
            id=row.id,
            label=row.label,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


@router.post("/tenants", response_model=ApiResponse[TenantOut])
async def create_tenant(req: CreateTenantRequest) -> Any:
    validate_tenant_id(req.id)
    async with async_session() as db:
        existing = await db.execute(select(Tenant).where(Tenant.id == req.id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"tenant '{req.id}' already exists")
        row = Tenant(id=req.id, label=req.label, created_at=utcnow())
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return ApiResponse(data=TenantOut.from_row(row), meta=Meta(count=1))


@router.get("/tenants", response_model=ApiResponse[list[TenantOut]])
async def list_tenants() -> Any:
    async with async_session() as db:
        result = await db.execute(select(Tenant).order_by(Tenant.created_at))
        rows = list(result.scalars().all())
    return ApiResponse(
        data=[TenantOut.from_row(r) for r in rows],
        meta=Meta(count=len(rows)),
    )


@router.delete("/tenants/{tenant_id}", response_model=ApiResponse[dict])
async def delete_tenant(tenant_id: str) -> Any:
    validate_tenant_id(tenant_id)
    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"tenant '{tenant_id}' not found")

        # Refuse if any data still references this tenant. We check the
        # high-traffic tables; full enumeration would be expensive.
        for model in (Memory, SessionModel, NarrativeArc, Intention, ApiKey):
            check = await db.execute(
                select(model).where(model.tenant_id == tenant_id).limit(1),
            )
            if check.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"tenant '{tenant_id}' has data in {model.__tablename__}; "
                        "purge before deleting"
                    ),
                )
        await db.delete(row)
        await db.commit()
    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))
