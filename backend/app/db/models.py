from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for Stage 3 tables."""


class User(Base):
    """A Telegram speaker. Later: portfolio fields keyed by this row."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["Message"]] = relationship(back_populates="sender")


class Conversation(Base):
    """
    One workspace topic (or 1:1 chat). Not owned by a single user.

    - The chat_id is the Telegram chat/group ID.
    - The thread_id is the Telegram topic ID in a chat/group.
    """

    __tablename__ = "conversations"

    # Unique constraint on chat_id and thread_id to prevent duplicate conversations.
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "thread_id",
            name="uq_conversations_chat_thread",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class MessageRole(StrEnum):
    """Who produced a stored turn. System prompt is not a row; it lives in settings."""

    USER = "user"
    ASSISTANT = "assistant"


class Message(Base):
    """One persisted turn. Working memory is last N of these for a conversation."""

    __tablename__ = "messages"

    # Index based on two columns (conversation_id, created_at) to speed up queries.
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            native_enum=False,
            length=16,
            values_callable=lambda roles: [role.value for role in roles],
            validate_strings=True,
        ),
    )
    content: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sender: Mapped[User | None] = relationship(back_populates="messages")
