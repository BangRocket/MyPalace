"""Admin re-embed endpoint (phase 6 slice 4).

Enqueues a `reembed` worker job that walks every memory in a tenant and
re-embeds it under the named (provider, model). Returns the job_id so
operators can poll /v1/jobs/{id} for completion.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from palace.api.common import ApiResponse, JobPendingOut, Meta
from palace.auth.context import AuthContext, get_auth_context
from palace.auth.tenant import is_valid_tenant_id
from palace.workers.queue import enqueue as enqueue_job

router = APIRouter()


class ReembedRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=32)
    provider: str = Field(default="huggingface")
    model: str = Field(min_length=1)
    token: str | None = None
    batch_size: int = Field(default=100, ge=1, le=1000)


@router.post("/reembed", response_model=ApiResponse[JobPendingOut])
async def reembed(
    req: ReembedRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    """Enqueue a per-tenant re-embed job. Cross-tenant admin keys may
    target any tenant_id; tenant-bound keys are restricted to their own."""
    if not is_valid_tenant_id(req.tenant_id):
        raise HTTPException(
            status_code=400, detail=f"invalid_tenant_id: {req.tenant_id!r}",
        )
    if req.provider not in ("huggingface", "openai"):
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider: {req.provider!r} (must be huggingface or openai)",
        )

    target = auth.resolve_tenant(request_tenant=req.tenant_id)

    payload = {
        "provider": req.provider,
        "model": req.model,
        "batch_size": req.batch_size,
    }
    if req.token:
        payload["token"] = req.token

    job = await enqueue_job(
        kind="reembed",
        user_id=auth.label or "admin",
        payload=payload,
        tenant_id=target,
    )
    return ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1),
    )
