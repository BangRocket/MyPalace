"""FSRS dynamics routes — promote, demote, get-dynamics, score.

Mounted under /v1/memories so paths overlay cleanly with the slice-1 memories
router (FastAPI resolves by exact path match).
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from palace.api.common import (
    ApiResponse,
    DemoteMemoryRequest,
    MemoryDynamicsOut,
    Meta,
    PromoteMemoryRequest,
    ScoreBreakdownOut,
    ScoreMemoryRequest,
)
from palace.auth.context import AuthContext, get_auth_context
from palace.dynamics.service import dynamics_service

router = APIRouter()


@router.post(
    "/{memory_id}/promote",
    response_model=ApiResponse[MemoryDynamicsOut],
)
async def promote_memory(
    memory_id: str,
    req: PromoteMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    if req.grade not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="grade must be 1-4")
    tenant_id = auth.resolve_tenant()
    start = time.time()
    dyn = await dynamics_service.promote(
        memory_id=memory_id,
        user_id=req.user_id,
        grade=req.grade,
        signal_type=req.signal_type,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=MemoryDynamicsOut.from_dynamics(dyn),
        meta=Meta(count=1, took_ms=took),
    )


@router.post(
    "/{memory_id}/demote",
    response_model=ApiResponse[MemoryDynamicsOut],
)
async def demote_memory(
    memory_id: str,
    req: DemoteMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    dyn = await dynamics_service.demote(
        memory_id=memory_id,
        user_id=req.user_id,
        reason=req.reason,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=MemoryDynamicsOut.from_dynamics(dyn),
        meta=Meta(count=1, took_ms=took),
    )


@router.get(
    "/{memory_id}/dynamics",
    response_model=ApiResponse[MemoryDynamicsOut],
)
async def get_memory_dynamics(
    memory_id: str,
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    dyn = await dynamics_service.get_dynamics(memory_id, user_id, tenant_id=tenant_id)
    if dyn is None:
        raise HTTPException(status_code=404, detail="Dynamics not found")
    return ApiResponse(
        data=MemoryDynamicsOut.from_dynamics(dyn),
        meta=Meta(count=1),
    )


@router.post(
    "/{memory_id}/score",
    response_model=ApiResponse[ScoreBreakdownOut],
)
async def score_memory(
    memory_id: str,
    req: ScoreMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    breakdown = await dynamics_service.score(
        memory_id=memory_id,
        user_id=req.user_id,
        semantic_score=req.semantic_score,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=ScoreBreakdownOut(**breakdown),
        meta=Meta(count=1, took_ms=took),
    )
