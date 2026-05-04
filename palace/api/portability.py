"""Bulk export + import for tenant migration / disaster recovery.

Wire format: NDJSON. One record per line, ``_type`` discriminator. Vector
data is NOT included — re-embed on import. Keeps dumps portable across
embedding models.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from palace.api.common import ApiResponse, Meta
from palace.auth.context import AuthContext, get_auth_context
from palace.auth.tenant import is_valid_tenant_id
from palace.database import async_session
from palace.memory_service import memory_service
from palace.models import (
    Intention,
    Memory,
    MemoryDynamics,
    MemorySupersession,
    NarrativeArc,
    Tenant,
)
from palace.models import Session as SessionModel

router = APIRouter()

# --- export -----------------------------------------------------------

# Order matters for import: tenants → memories → sessions → ... so foreign-key
# references resolve cleanly. Keep this list in dependency order.
EXPORTABLE = (
    ("tenant",              Tenant),
    ("memory",              Memory),
    ("session",             SessionModel),
    ("narrative_arc",       NarrativeArc),
    ("intention",           Intention),
    ("memory_dynamics",     MemoryDynamics),
    ("memory_supersession", MemorySupersession),
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """SQLModel row → dict, preserving timestamps as ISO strings."""
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        out[col.name] = val
    return out


async def _stream_export(tenant_id: str) -> AsyncIterator[bytes]:
    """Yield NDJSON lines for every exportable row in tenant_id."""
    async with async_session() as db:
        for type_name, model in EXPORTABLE:
            if model is Tenant:
                stmt = select(Tenant).where(Tenant.id == tenant_id)
            else:
                stmt = select(model).where(model.tenant_id == tenant_id)
            result = await db.execute(stmt)
            for row in result.scalars().all():
                payload = {"_type": type_name, **_row_to_dict(row)}
                yield (json.dumps(payload, default=str) + "\n").encode("utf-8")


@router.get("/export")
async def export_tenant(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
) -> StreamingResponse:
    """Stream a NDJSON dump of one tenant. Tenant-bound keys may only
    export their own tenant; cross-tenant admins may export any."""
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(status_code=400, detail=f"invalid_tenant_id: {tenant_id!r}")
    resolved = auth.resolve_tenant(request_tenant=tenant_id)

    return StreamingResponse(
        _stream_export(resolved),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": (
                f'attachment; filename="palace-{resolved}-export.ndjson"'
            ),
        },
    )


# --- import -----------------------------------------------------------

class ImportSummary(BaseModel):
    target_tenant: str
    tenants_seen: int = 0
    memories_imported: int = 0
    sessions_imported: int = 0
    arcs_imported: int = 0
    intentions_imported: int = 0
    dynamics_imported: int = 0
    supersessions_imported: int = 0
    skipped: int = 0
    skipped_reasons: list[str] = []


def _coerce_timestamps(record: dict, model: type) -> dict:
    """Convert ISO strings back to datetimes for tz-aware columns."""
    from datetime import datetime
    out = dict(record)
    for col in model.__table__.columns:
        v = out.get(col.name)
        if isinstance(v, str) and "T" in v and ":" in v:
            with contextlib.suppress(ValueError):
                out[col.name] = datetime.fromisoformat(v)
    return out


_TYPE_TO_MODEL: dict[str, type] = dict(EXPORTABLE)


async def _ingest_records(
    target_tenant: str,
    lines: list[str],
    reembed_memories: bool,
) -> ImportSummary:
    """Parse NDJSON lines and upsert records into target_tenant.

    `reembed_memories=True` (default) re-embeds memory content as it
    inserts. False skips the embedding step (use only when paired with
    an immediate /v1/admin/reembed run, e.g. for very large imports).
    """
    summary = ImportSummary(target_tenant=target_tenant)
    memory_payloads: list[dict] = []

    async with async_session() as db:
        # Ensure target tenant exists.
        existing = await db.execute(select(Tenant).where(Tenant.id == target_tenant))
        if existing.scalar_one_or_none() is None:
            db.add(Tenant(id=target_tenant, label=f"imported {target_tenant}"))
            await db.commit()

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                summary.skipped += 1
                summary.skipped_reasons.append("malformed json")
                continue

            type_name = record.pop("_type", None)
            if type_name == "tenant":
                summary.tenants_seen += 1
                continue  # we already ensured target_tenant; ignore source label

            model = _TYPE_TO_MODEL.get(type_name)
            if model is None or model is Tenant:
                summary.skipped += 1
                summary.skipped_reasons.append(f"unknown _type: {type_name!r}")
                continue

            # Force tenant_id to the target — never let an import smuggle
            # data into a different tenant than the operator requested.
            record["tenant_id"] = target_tenant
            coerced = _coerce_timestamps(record, model)

            # Memories need an embedding pass after the SQL upsert.
            if model is Memory and reembed_memories:
                memory_payloads.append(coerced)

            try:
                # Use db.merge() for upsert semantics (insert or update by PK)
                obj = model(**coerced)
                await db.merge(obj)
                if model is Memory:
                    summary.memories_imported += 1
                elif model is SessionModel:
                    summary.sessions_imported += 1
                elif model is NarrativeArc:
                    summary.arcs_imported += 1
                elif model is Intention:
                    summary.intentions_imported += 1
                elif model is MemoryDynamics:
                    summary.dynamics_imported += 1
                elif model is MemorySupersession:
                    summary.supersessions_imported += 1
            except Exception as e:
                summary.skipped += 1
                summary.skipped_reasons.append(f"{type_name}: {e!r}"[:200])

        await db.commit()

    # Re-embed memories outside the SQL transaction so vector ops don't
    # block the DB. Failures here log but don't roll back the import — the
    # row is in PG, just missing from Qdrant; operators can run reembed
    # to recover.
    if reembed_memories and memory_payloads:
        for payload in memory_payloads:
            try:
                vectors = await memory_service.embedder.embed([payload["content"]])
                from palace.vector import vector_store
                await vector_store.upsert(
                    payload["id"],
                    vectors[0],
                    {
                        "user_id": payload["user_id"],
                        "agent_id": payload.get("agent_id"),
                        "memory_type": payload.get("memory_type", "semantic"),
                    },
                    tenant_id=target_tenant,
                )
            except Exception:
                # Re-embed is best-effort during import; row is preserved.
                pass

    return summary


@router.post("/import", response_model=ApiResponse[ImportSummary])
async def import_dump(
    request: Request,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    tenant_id: str = Query(..., min_length=1, max_length=32),
    reembed: bool = Query(default=True),
) -> Any:
    """Ingest a NDJSON dump into ``tenant_id``. Idempotent — re-importing
    the same dump upserts the same rows."""
    if not is_valid_tenant_id(tenant_id):
        raise HTTPException(status_code=400, detail=f"invalid_tenant_id: {tenant_id!r}")
    target = auth.resolve_tenant(request_tenant=tenant_id)

    body = await request.body()
    lines = body.decode("utf-8", errors="replace").splitlines()

    summary = await _ingest_records(
        target_tenant=target,
        lines=lines,
        reembed_memories=reembed,
    )
    total = (
        summary.memories_imported + summary.sessions_imported +
        summary.arcs_imported + summary.intentions_imported +
        summary.dynamics_imported + summary.supersessions_imported
    )
    return ApiResponse(data=summary, meta=Meta(count=total))
