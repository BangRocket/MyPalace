"""GET /v1/admin/audit — query the admin audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.database import async_session
from mypalace.models import AuditLog

router = APIRouter()


class AuditEntryOut(BaseModel):
    id: str
    key_id: str
    tenant_id: str | None
    method: str
    path: str
    status_class: str
    request_body_hash: str | None
    response_ms: int
    created_at: str | None


def _to_out(row: AuditLog) -> AuditEntryOut:
    return AuditEntryOut(
        id=row.id,
        key_id=row.key_id,
        tenant_id=row.tenant_id,
        method=row.method,
        path=row.path,
        status_class=row.status_class,
        request_body_hash=row.request_body_hash,
        response_ms=row.response_ms,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


MAX_LIMIT = 500


@router.get("/audit", response_model=ApiResponse[list[AuditEntryOut]])
async def query_audit(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    key_id: Annotated[str | None, Query()] = None,
    path_prefix: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> Any:
    """Recent-first audit trail. Tenant-bound keys see only their tenant's
    rows; cross-tenant admin keys see everything."""
    clauses = []
    if since is not None:
        clauses.append(AuditLog.created_at >= since)
    if until is not None:
        clauses.append(AuditLog.created_at <= until)
    if key_id is not None:
        clauses.append(AuditLog.key_id == key_id)
    if path_prefix is not None:
        clauses.append(AuditLog.path.startswith(path_prefix))
    # Tenant scoping — bound keys see their tenant only; cross-tenant
    # admin sees all (audit is meant for support/compliance).
    if auth.tenant_id is not None:
        clauses.append(AuditLog.tenant_id == auth.tenant_id)

    stmt = (
        select(AuditLog)
        .where(*clauses) if clauses else select(AuditLog)
    )
    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)

    async with async_session() as db:
        result = await db.execute(stmt)
        rows = list(result.scalars().all())

    return ApiResponse(
        data=[_to_out(r) for r in rows],
        meta=Meta(count=len(rows)),
    )
