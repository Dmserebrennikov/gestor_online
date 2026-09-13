from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Message, MessageRole, User


async def upsert_user(
    session: AsyncSession,
    telegram_user_id: int,
    display_name: str | None,
    *,
    username: str | None = None,
    last_name: str | None = None,
    language_code: str | None = None,
) -> User:
    """Insert the speaker and(or) return the existing row in one statement.

    Ensuring the row exists and getting it back in one go.
    Optionally refreshes identity fields when Telegram sends a new value.
    """
    stmt = insert(User).values(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        username=username,
        last_name=last_name,
        language_code=language_code,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[User.telegram_user_id],
        set_={
            "display_name": func.coalesce(stmt.excluded.display_name, User.display_name),
            "username": func.coalesce(stmt.excluded.username, User.username),
            "last_name": func.coalesce(stmt.excluded.last_name, User.last_name),
            "language_code": func.coalesce(stmt.excluded.language_code, User.language_code),
            "updated_at": func.now(),
        },
    ).returning(User)
    result = await session.execute(stmt)
    return result.scalar_one()


async def upsert_conversation(
    session: AsyncSession,
    chat_id: int,
    thread_id: int | None,
) -> Conversation:
    """Insert or fetch the topic row keyed by (chat_id, thread_id)."""
    stmt = insert(Conversation).values(chat_id=chat_id, thread_id=thread_id)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_conversations_chat_thread",
        set_={"chat_id": stmt.excluded.chat_id},
    ).returning(Conversation)
    result = await session.execute(stmt)
    return result.scalar_one()


async def append_message(
    session: AsyncSession,
    conversation_id: int,
    sender_user_id: int | None,
    role: MessageRole,
    content: str,
    telegram_message_id: int | None = None,
    attachments: list[dict[str, str]] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        role=role,
        content=content,
        telegram_message_id=telegram_message_id,
        attachments=attachments,
    )
    session.add(message)
    await session.flush()
    return message


async def load_recent_messages(
    session: AsyncSession,
    conversation_id: int,
    limit: int,
) -> list[Message]:
    """Last N turns of the whole topic."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.sender))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list((await session.scalars(stmt)).all())
    rows.reverse()
    return rows
