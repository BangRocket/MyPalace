"""Job status route."""

from fastapi import APIRouter, HTTPException

from palace.api.common import ApiResponse, JobOut, Meta
from palace.job_service import job_service

router = APIRouter()


@router.get("/{job_id}", response_model=ApiResponse[JobOut])
async def get_job(job_id: str):
    job = await job_service.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ApiResponse(data=JobOut.from_job(job), meta=Meta(count=1))
