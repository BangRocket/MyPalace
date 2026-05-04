"""Admin/maintenance routes — currently just access-log pruning."""

from __future__ import annotations

import time

from fastapi import APIRouter

from palace.api.common import ApiResponse, Meta
from palace.dynamics.service import dynamics_service

router = APIRouter()


@router.post("/prune-access-logs", response_model=ApiResponse[dict])
async def prune_access_logs(retention_days: int = 90):
    start = time.time()
    deleted = await dynamics_service.prune_access_logs(retention_days=retention_days)
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data={"deleted": deleted},
        meta=Meta(count=deleted, took_ms=took),
    )
