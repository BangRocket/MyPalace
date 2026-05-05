"""Admin tenants CRUD."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.tenant import validate_tenant_id
from mypalace.config import settings
from mypalace.database import async_session, engine
from mypalace.models import (
    ApiKey,
    Intention,
    Memory,
    NarrativeArc,
    Tenant,
    utcnow,
)
from mypalace.models import Session as SessionModel
from mypalace.tenancy import drop_tenant_schema, replicate_per_tenant_schema

logger = logging.getLogger(__name__)

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

    # Phase 12.2: when running in schema-mode, provision the per-tenant
    # schema and replicate per-tenant DDL into it. Done outside the
    # tenant-row commit so a DDL failure surfaces as a 500 with the
    # tenant row already on disk — operators can re-call create or run
    # `mypalace-admin tenants reprovision` (added in a follow-up).
    if settings.tenant_schema_mode == "schema":
        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sc: replicate_per_tenant_schema(req.id, sc),
                )
        except Exception:
            logger.exception(
                "tenant created but schema replication failed; tenant_id=%s",
                req.id,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"tenant '{req.id}' row created but schema provisioning "
                    "failed; see server logs"
                ),
            ) from None

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
async def delete_tenant(
    tenant_id: str,
    confirm: str | None = Query(
        default=None,
        description=(
            "Must equal tenant_id to proceed. Required when ?force=true OR "
            "when running in schema-mode (because DROP SCHEMA CASCADE "
            "irreversibly deletes all per-tenant data)."
        ),
    ),
    force: bool = Query(
        default=False,
        description=(
            "Skip the row-presence safety check and DROP SCHEMA CASCADE. "
            "Combined with confirm=<tenant_id> this destroys all data "
            "for the tenant. Default false preserves the original "
            "data-still-present 409 response."
        ),
    ),
) -> Any:
    validate_tenant_id(tenant_id)

    schema_mode = settings.tenant_schema_mode == "schema"

    # Confirmation guard — phase 12 makes tenant-drop irreversible (in
    # schema-mode). Require an explicit ?confirm=<tenant_id> match.
    if (force or schema_mode) and confirm != tenant_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"destructive operation: pass ?confirm={tenant_id} to proceed. "
                "Tenant data will be permanently removed."
            ),
        )

    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"tenant '{tenant_id}' not found")

        if not force:
            # Pre-phase-12 safety: refuse if any data still references this
            # tenant. We check the high-traffic tables; full enumeration
            # would be expensive.
            for model in (Memory, SessionModel, NarrativeArc, Intention, ApiKey):
                check = await db.execute(
                    select(model).where(model.tenant_id == tenant_id).limit(1),
                )
                if check.scalar_one_or_none() is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"tenant '{tenant_id}' has data in "
                            f"{model.__tablename__}; pass ?force=true&"
                            f"confirm={tenant_id} to drop it anyway"
                        ),
                    )
        await db.delete(row)
        await db.commit()

    # Phase 12.2: drop the per-tenant schema. CASCADE removes everything
    # inside it; the tenant row is gone above so this is unrecoverable.
    if schema_mode:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sc: drop_tenant_schema(tenant_id, sc))
        except Exception:
            logger.exception(
                "tenant row deleted but schema drop failed; tenant_id=%s",
                tenant_id,
            )
            # Don't 500 here — the tenant row is gone, so the tenant is
            # effectively deleted from MyPalace's view. Schema cleanup
            # can be done manually via psql.

    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))
