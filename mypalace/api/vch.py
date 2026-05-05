"""VCH (verbatim chat history search) endpoint (phase 10 slice 5).

Hits the existing ``messages`` table via Postgres FTS, returns matched
messages plus a 5-minute context window from the same session. Useful
for "what did we discuss" recall that semantic search misses.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.vch_service import vch_service

router = APIRouter()


class VCHSearchRequest(BaseModel):
    user_id: str
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)
    context_window: int = Field(default=2, ge=0, le=10)
    min_content_length: int = Field(default=20, ge=1, le=500)


class VCHMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class VCHSnippet(BaseModel):
    messages: list[VCHMessage]
    matched_content: str
    rank: float
    timestamp: str


@router.post("/vch", response_model=ApiResponse[list[VCHSnippet]])
async def search_vch(
    req: VCHSearchRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    tenant_id = auth.resolve_tenant()
    snippets = await vch_service.search(
        query=req.query,
        user_id=req.user_id,
        limit=req.limit,
        context_window=req.context_window,
        min_content_length=req.min_content_length,
        tenant_id=tenant_id,
    )
    return ApiResponse(
        data=[VCHSnippet(**s) for s in snippets],
        meta=Meta(count=len(snippets)),
    )
