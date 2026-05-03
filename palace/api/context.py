"""Context assembly route handlers."""

import time

from fastapi import APIRouter

from palace.api.common import ApiResponse, AssembleContextRequest, ContextOut, Meta
from palace.context_service import context_service

router = APIRouter()


@router.post("", response_model=ApiResponse[ContextOut])
async def assemble_context(req: AssembleContextRequest):
    start = time.time()
    result = await context_service.assemble(
        user_id=req.user_id,
        query=req.query,
        session_id=req.session_id,
        max_memories=req.max_memories,
        max_messages=req.max_messages,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=ContextOut(**result),
        meta=Meta(
            count=len(result["memories"]) + len(result["recent_messages"]),
            took_ms=took,
        ),
    )
