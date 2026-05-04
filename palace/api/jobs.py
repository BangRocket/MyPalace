"""Job status route."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from palace.api.common import ApiResponse, JobOut, Meta
from palace.auth.context import AuthContext, get_auth_context
from palace.job_service import job_service

router = APIRouter()


@router.get("/{job_id}", response_model=ApiResponse[JobOut])
async def get_job(
    job_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    job = await job_service.get(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiResponse(data=JobOut.from_job(job), meta=Meta(count=1))
