"""Session route handlers."""

from fastapi import APIRouter, HTTPException

from palace.api.common import (
    AddMessageRequest,
    ApiResponse,
    CreateSessionRequest,
    MessageOut,
    Meta,
    SessionOut,
    UpdateSessionRequest,
)
from palace.session_service import session_service

router = APIRouter()


@router.post("", response_model=ApiResponse[SessionOut])
async def create_session(req: CreateSessionRequest):
    session = await session_service.create(user_id=req.user_id, title=req.title)
    return ApiResponse(
        data=SessionOut(
            id=session.id,
            user_id=session.user_id,
            title=session.title,
            summary=session.summary,
            created_at=session.created_at.isoformat() if session.created_at else None,
            updated_at=session.updated_at.isoformat() if session.updated_at else None,
        ),
        meta=Meta(count=1),
    )


@router.get("/{session_id}", response_model=ApiResponse[dict])
async def get_session(session_id: str):
    data = await session_service.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    msg_count = len(data.get("messages", []))
    return ApiResponse(data=data, meta=Meta(count=msg_count))


@router.post("/{session_id}/messages", response_model=ApiResponse[MessageOut])
async def add_message(session_id: str, req: AddMessageRequest):
    message = await session_service.add_message(
        session_id=session_id,
        user_id=req.user_id,
        role=req.role,
        content=req.content,
    )
    return ApiResponse(
        data=MessageOut(
            id=message.id,
            user_id=message.user_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at.isoformat() if message.created_at else None,
        ),
        meta=Meta(count=1),
    )


@router.patch("/{session_id}", response_model=ApiResponse[SessionOut])
async def update_session(session_id: str, req: UpdateSessionRequest):
    session = await session_service.update(
        session_id, title=req.title, summary=req.summary,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ApiResponse(
        data=SessionOut(
            id=session.id,
            user_id=session.user_id,
            title=session.title,
            summary=session.summary,
            created_at=session.created_at.isoformat() if session.created_at else None,
            updated_at=session.updated_at.isoformat() if session.updated_at else None,
        ),
        meta=Meta(count=1),
    )


@router.delete("/{session_id}", response_model=ApiResponse[dict])
async def delete_session(session_id: str):
    ok = await session_service.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))
