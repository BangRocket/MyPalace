"""Session and message management service."""

from sqlalchemy import select

from mypalace.database import async_session
from mypalace.models import DEFAULT_TENANT_ID, Message, Session, utcnow


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

        # Phase 10 slice 2: probabilistic personality evolution.
        # Triggers only on assistant messages (we need both sides of the
        # exchange) and only when PALACE_PERSONALITY_EVOLUTION_CHANCE > 0.
        # Lookup is async + best-effort; failures never affect the write.
        if role == "assistant":
            await self._maybe_trigger_personality_evolution(
                session_id=session_id,
                user_id=user_id,
                assistant_reply=content,
                tenant_id=tenant_id,
            )
        return message

    async def _maybe_trigger_personality_evolution(
        self,
        session_id: str,
        user_id: str,
        assistant_reply: str,
        tenant_id: str,
    ) -> None:
        from mypalace.config import settings

        if settings.personality_evolution_chance <= 0:
            return

        # Fetch the most recent user message in this session — that's the
        # half of the exchange we just replied to.
        async with async_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .where(Message.tenant_id == tenant_id)
                .where(Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(1),
            )
            user_msg = result.scalar_one_or_none()
        if user_msg is None:
            return

        from mypalace.personality_service import maybe_enqueue_evolution
        maybe_enqueue_evolution(
            user_message=user_msg.content,
            assistant_reply=assistant_reply,
            user_id=user_id,
            tenant_id=tenant_id,
        )

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
