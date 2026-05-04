"""Session and message management service."""

from sqlalchemy import select

from palace.database import async_session
from palace.models import DEFAULT_TENANT_ID, Message, Session, utcnow


class SessionService:
    """Business logic for conversation sessions."""

    async def create(
        self,
        user_id: str,
        title: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Session:
        async with async_session() as db:
            session = Session(
                tenant_id=tenant_id,
                user_id=user_id,
                title=title,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return session

    async def get(
        self,
        session_id: str,
        include_messages: bool = True,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict | None:
        async with async_session() as db:
            result = await db.execute(
                select(Session).where(
                    Session.id == session_id,
                    Session.tenant_id == tenant_id,
                ),
            )
            session = result.scalar_one_or_none()
            if not session:
                return None

            data: dict = {
                "id": session.id,
                "user_id": session.user_id,
                "title": session.title,
                "summary": session.summary,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            }
            if include_messages:
                msg_result = await db.execute(
                    select(Message)
                    .where(
                        Message.session_id == session_id,
                        Message.tenant_id == tenant_id,
                    )
                    .order_by(Message.created_at),
                )
                data["messages"] = [
                    {
                        "id": m.id,
                        "user_id": m.user_id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in msg_result.scalars()
                ]
            return data

    async def add_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Message:
        async with async_session() as db:
            message = Message(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                role=role,
                content=content,
                created_at=utcnow(),
            )
            db.add(message)

            result = await db.execute(
                select(Session).where(
                    Session.id == session_id,
                    Session.tenant_id == tenant_id,
                ),
            )
            session = result.scalar_one()
            session.updated_at = utcnow()

            await db.commit()
            await db.refresh(message)
            return message

    async def update(
        self,
        session_id: str,
        title: str | None = None,
        summary: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Session | None:
        async with async_session() as db:
            result = await db.execute(
                select(Session).where(
                    Session.id == session_id,
                    Session.tenant_id == tenant_id,
                ),
            )
            session = result.scalar_one_or_none()
            if not session:
                return None
            if title is not None:
                session.title = title
            if summary is not None:
                session.summary = summary
            session.updated_at = utcnow()
            await db.commit()
            return session

    async def delete(
        self,
        session_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> bool:
        async with async_session() as db:
            result = await db.execute(
                select(Session).where(
                    Session.id == session_id,
                    Session.tenant_id == tenant_id,
                ),
            )
            session = result.scalar_one_or_none()
            if not session:
                return False

            await db.execute(
                Message.__table__.delete().where(
                    Message.session_id == session_id,
                    Message.tenant_id == tenant_id,
                ),
            )
            await db.delete(session)
            await db.commit()
            return True


# Singleton
session_service = SessionService()
