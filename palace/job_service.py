"""Background reflection/synthesis job tracking using pure asyncio (no Celery)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from palace.database import async_session
from palace.models import ReflectionJob, utcnow


class JobService:
    """CRUD for ReflectionJob + asyncio.create_task wrapper."""

    async def create(self, kind: str, user_id: str) -> ReflectionJob:
        async with async_session() as db:
            job = ReflectionJob(kind=kind, user_id=user_id, status="pending")
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job

    async def get(self, job_id: str) -> ReflectionJob | None:
        async with async_session() as db:
            result = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            return result.scalar_one_or_none()

    async def complete(self, job_id: str, result: list | dict) -> None:
        async with async_session() as db:
            r = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            job = r.scalar_one_or_none()
            if not job:
                return
            job.status = "completed"
            job.result_json = result
            job.completed_at = utcnow()
            await db.commit()

    async def fail(self, job_id: str, error: str) -> None:
        async with async_session() as db:
            r = await db.execute(select(ReflectionJob).where(ReflectionJob.id == job_id))
            job = r.scalar_one_or_none()
            if not job:
                return
            job.status = "failed"
            job.error = error
            job.completed_at = utcnow()
            await db.commit()

    async def run_async(
        self,
        kind: str,
        user_id: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> ReflectionJob:
        """Create a pending job, spawn coro_factory() as an asyncio.Task that
        writes result/error back to the job row when done. Returns the
        pending job immediately."""
        job = await self.create(kind=kind, user_id=user_id)

        async def runner():
            try:
                result = await coro_factory()
                # Coerce ORM models to dicts where needed before JSON storage
                serializable = _serialize_result(result)
                await self.complete(job.id, serializable)
            except Exception as e:
                await self.fail(job.id, repr(e))

        asyncio.create_task(runner())
        return job


def _serialize_result(result: Any) -> list | dict:
    """Coerce service return values into JSON-storable shapes for result_json."""
    if isinstance(result, list):
        return [_one(item) for item in result]
    if isinstance(result, dict):
        return result
    return {"value": _one(result)}


def _one(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dict__"):
        # Skip SQLAlchemy internal attrs
        return {k: v for k, v in vars(item).items() if not k.startswith("_")}
    return item


# Singleton
job_service = JobService()
