"""Graph routes (phase 3 slice 3)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.graph.service import graph_service

router = APIRouter()


@router.get("/neighbors", response_model=ApiResponse[dict])
async def get_neighbors(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    node_id: str = Query(..., min_length=1),
    depth: int = Query(1, ge=1, le=3),
    edge_type: str | None = Query(None),
) -> Any:
    if not graph_service.enabled:
        raise HTTPException(
            status_code=503,
            detail="graph not configured (set PALACE_FALKORDB_URL)",
        )
    tenant_id = auth.resolve_tenant()
    result = await graph_service.neighbors(
        node_id=node_id, depth=depth, tenant_id=tenant_id, edge_type=edge_type,
    )
    nodes = result.get("nodes", [])
    return ApiResponse(data=result, meta=Meta(count=len(nodes)))
