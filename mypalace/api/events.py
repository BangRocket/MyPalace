"""WebSocket events route. Auth via api_key query param (browsers can't send
custom headers on WebSocket handshakes reliably)."""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from mypalace.auth.context import AuthContext
from mypalace.auth.key_service import key_service
from mypalace.config import settings
from mypalace.events.broker import broker
from mypalace.events.types import KNOWN_EVENT_TYPES

router = APIRouter()


def _parse_topics(raw: str | None) -> set[str] | None:
    """Comma-separated list of event types; None means subscribe to all."""
    if not raw:
        return None
    requested = {t.strip() for t in raw.split(",") if t.strip()}
    return requested or None


async def _resolve_auth(api_key: str | None) -> AuthContext | None:
    if settings.auth_disabled:
        return AuthContext.all_scopes()
    if not api_key:
        return None
    return await key_service.lookup(api_key)


@router.websocket("/events")
async def events_ws(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
    topics: str | None = Query(default=None),
) -> None:
    """Subscribe to per-tenant events. Frame format:
        {"type": "memory.created", "tenant_id": "...", "payload": {...},
         "occurred_at": "..."}

    Sends `{"hello": {...}}` on connect with the resolved tenant + active
    topics so the client can confirm what they're getting.
    """
    auth = await _resolve_auth(api_key)
    if auth is None:
        # Reject the handshake before accepting.
        await websocket.close(code=4401, reason="unauthenticated")
        return

    if not auth.has_scope("read"):
        await websocket.close(code=4403, reason="forbidden: requires 'read' scope")
        return

    tenant_id = auth.resolve_tenant()
    requested = _parse_topics(topics)
    # Validate any explicit topics the client asked for; warn rather than
    # close so a typo doesn't kill the connection.
    if requested is not None:
        unknown = requested - KNOWN_EVENT_TYPES
        if unknown:
            requested = requested & KNOWN_EVENT_TYPES

    await websocket.accept()
    await websocket.send_json({
        "hello": {
            "tenant_id": tenant_id,
            "key_id": auth.key_id,
            "topics": sorted(requested) if requested is not None else "*",
        },
    })

    # Optional: a tiny consumer task that ignores client-sent frames so the
    # WebSocket stays open instead of being closed by client pings.
    async def drain_client():
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    drain_task = asyncio.create_task(drain_client())

    try:
        async with broker.subscribe(tenant_id) as queue:
            while True:
                envelope_str = await queue.get()
                try:
                    envelope = json.loads(envelope_str)
                except json.JSONDecodeError:
                    continue
                if requested is not None and envelope.get("type") not in requested:
                    continue
                await websocket.send_text(envelope_str)
    except WebSocketDisconnect:
        pass
    finally:
        drain_task.cancel()
        with contextlib.suppress(Exception):
            await drain_task
