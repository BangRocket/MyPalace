"""Admin/maintenance routes — currently just access-log pruning."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.dynamics.service import dynamics_service
from mypalace.intentions.service import intention_service

router = APIRouter()


@router.post("/prune-access-logs", response_model=ApiResponse[dict])
async def prune_access_logs(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    retention_days: int = 90,
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    deleted = await dynamics_service.prune_access_logs(
        retention_days=retention_days, tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data={"deleted": deleted},
        meta=Meta(count=deleted, took_ms=took),
    )


@router.post("/cleanup-intentions", response_model=ApiResponse[dict])
async def cleanup_intentions(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    deleted = await intention_service.cleanup_expired(tenant_id=tenant_id)
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data={"deleted": deleted},
        meta=Meta(count=deleted, took_ms=took),
    )
