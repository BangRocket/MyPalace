"""Admin stats — per-tenant snapshots + cross-tenant rollups."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from mypalace.api.common import ApiResponse, Meta
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.auth.tenant import is_valid_tenant_id
from mypalace.config import settings
from mypalace.database import async_session
from mypalace.models import (
    Intention,
    Memory,
    MemoryAccessLog,
    MemoryDynamics,
    MemorySupersession,
    NarrativeArc,
    ReflectionJob,
    Tenant,
    utcnow,
)
from mypalace.models import Session as SessionModel
from mypalace.tenancy import tenant_scope

router = APIRouter()


# --- response shape ---------------------------------------------------

class RowCounts(BaseModel):
    memories: int = 0
    sessions: int = 0
    episodes: int = 0  # populated from ReflectionJob completed (proxy)
    narrative_arcs: int = 0
    intentions: int = 0
    memory_supersessions: int = 0


class Activity7d(BaseModel):
    memories_created: int = 0
    memories_accessed: int = 0
    episodes_reflected: int = 0
    intentions_fired: int = 0


class TopUser(BaseModel):
    user_id: str
    access_count: int


class FsrsHealth(BaseModel):
    tracked_memories: int = 0
    key_memories: int = 0
    mean_stability: float = 0.0
    mean_retrieval_strength: float = 0.0


class TenantStats(BaseModel):
    tenant_id: str
    row_counts: RowCounts
    activity_7d: Activity7d
    top_users_by_access_7d: list[TopUser]
    fsrs_health: FsrsHealth


class AllTenantsStats(BaseModel):
    tenants: list[TenantStats]


# --- helpers ----------------------------------------------------------

ALL_SENTINEL = "ALL"
TOP_USERS_CAP = 10


async def _row_counts(tenant_id: str | None) -> RowCounts:
    """Count rows in each user-data table. ``tenant_id=None`` aggregates
    across tenants — used by the ALL-tenants summary (each tenant gets
    its own RowCounts, so this stays per-tenant in practice)."""
    async with async_session() as db:
        async def _count(model, *extra) -> int:
            stmt = select(func.count()).select_from(model)
            clauses = []
            if tenant_id is not None:
                clauses.append(model.tenant_id == tenant_id)
            clauses.extend(extra)
            if clauses:
                stmt = stmt.where(*clauses)
            result = await db.execute(stmt)
            return int(result.scalar_one() or 0)

        return RowCounts(
            memories=await _count(Memory),
            sessions=await _count(SessionModel),
            episodes=await _count(ReflectionJob, ReflectionJob.kind == "reflection"),
            narrative_arcs=await _count(NarrativeArc),
            intentions=await _count(Intention),
            memory_supersessions=await _count(MemorySupersession),
        )


async def _activity_7d(tenant_id: str | None) -> Activity7d:
    cutoff = utcnow() - timedelta(days=7)
    async with async_session() as db:
        async def _count(model, ts_col, *extra) -> int:
            stmt = select(func.count()).select_from(model).where(ts_col >= cutoff)
            if tenant_id is not None:
                stmt = stmt.where(model.tenant_id == tenant_id)
            for clause in extra:
                stmt = stmt.where(clause)
            result = await db.execute(stmt)
            return int(result.scalar_one() or 0)

        return Activity7d(
            memories_created=await _count(Memory, Memory.created_at),
            memories_accessed=await _count(MemoryAccessLog, MemoryAccessLog.accessed_at),
            episodes_reflected=await _count(
                ReflectionJob, ReflectionJob.completed_at,
                ReflectionJob.kind == "reflection",
                ReflectionJob.status == "completed",
            ),
            intentions_fired=await _count(
                Intention, Intention.fired_at,
                Intention.fired == True,  # noqa: E712
            ),
        )


async def _top_users_by_access_7d(tenant_id: str | None) -> list[TopUser]:
    cutoff = utcnow() - timedelta(days=7)
    async with async_session() as db:
        stmt = (
            select(
                MemoryAccessLog.user_id,
                func.count().label("access_count"),
            )
            .where(MemoryAccessLog.accessed_at >= cutoff)
            .group_by(MemoryAccessLog.user_id)
            .order_by(func.count().desc())
            .limit(TOP_USERS_CAP)
        )
        if tenant_id is not None:
            stmt = stmt.where(MemoryAccessLog.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return [
            TopUser(user_id=row[0], access_count=int(row[1]))
            for row in result.all()
        ]


async def _fsrs_health(tenant_id: str | None) -> FsrsHealth:
    async with async_session() as db:
        if tenant_id is not None:
            stmt_tracked = select(func.count()).select_from(MemoryDynamics).where(
                MemoryDynamics.tenant_id == tenant_id,
            )
            stmt_key = select(func.count()).select_from(MemoryDynamics).where(
                MemoryDynamics.tenant_id == tenant_id,
                MemoryDynamics.is_key == True,  # noqa: E712
            )
            stmt_means = select(
                func.coalesce(func.avg(MemoryDynamics.stability), 0.0),
                func.coalesce(func.avg(MemoryDynamics.retrieval_strength), 0.0),
            ).where(MemoryDynamics.tenant_id == tenant_id)
        else:
            stmt_tracked = select(func.count()).select_from(MemoryDynamics)
            stmt_key = select(func.count()).select_from(MemoryDynamics).where(
                MemoryDynamics.is_key == True,  # noqa: E712
            )
            stmt_means = select(
                func.coalesce(func.avg(MemoryDynamics.stability), 0.0),
                func.coalesce(func.avg(MemoryDynamics.retrieval_strength), 0.0),
            )

        tracked = int((await db.execute(stmt_tracked)).scalar_one() or 0)
        key = int((await db.execute(stmt_key)).scalar_one() or 0)
        means_row = (await db.execute(stmt_means)).first()
        mean_stability = float(means_row[0] or 0.0) if means_row else 0.0
        mean_retrieval = float(means_row[1] or 0.0) if means_row else 0.0

        return FsrsHealth(
            tracked_memories=tracked,
            key_memories=key,
            mean_stability=round(mean_stability, 4),
            mean_retrieval_strength=round(mean_retrieval, 4),
        )


async def _stats_for(tenant_id: str) -> TenantStats:
    return TenantStats(
        tenant_id=tenant_id,
        row_counts=await _row_counts(tenant_id),
        activity_7d=await _activity_7d(tenant_id),
        top_users_by_access_7d=await _top_users_by_access_7d(tenant_id),
        fsrs_health=await _fsrs_health(tenant_id),
    )


async def _all_tenant_ids() -> list[str]:
    async with async_session() as db:
        result = await db.execute(select(Tenant.id).order_by(Tenant.id))
        return [row[0] for row in result.all()]


# --- routes -----------------------------------------------------------

@router.get("/stats", response_model=ApiResponse[TenantStats | AllTenantsStats])
async def get_stats(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> Any:
    """Per-tenant snapshot, or cross-tenant rollup if ``tenant_id=ALL``.

    `ALL` requires a cross-tenant admin key (key.tenant_id is None).
    Other tenant_id values must match the key's binding (or be admin).
    """
    if tenant_id == ALL_SENTINEL:
        if auth.tenant_id is not None:
            raise HTTPException(
                status_code=403,
                detail="cross-tenant rollup requires a cross-tenant admin key",
            )
        ids = await _all_tenant_ids()
        # v0.12.0: seat each tenant's search_path so _stats_for's inner
        # sessions read <t>.<table>, not stale public.*.
        per = []
        for t in ids:
            with tenant_scope(t):
                per.append(await _stats_for(t))
        return ApiResponse(
            data=AllTenantsStats(tenants=per),
            meta=Meta(count=len(per)),
        )

    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(
            status_code=400, detail=f"invalid_tenant_id: {tenant_id!r}",
        )

    # Bound key trying to read another tenant → 403 (resolve_tenant raises).
    resolved = auth.resolve_tenant(request_tenant=tenant_id)
    _ = settings  # keep import for future per-tenant config lookups
    stats = await _stats_for(resolved)
    return ApiResponse(data=stats, meta=Meta(count=1))
