import logging
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import settings
from app.db.crud import append_message, load_recent_messages, upsert_conversation, upsert_user
from app.db.models import Message, MessageRole
from app.db.session import session_factory
from app.domain.identity import display_label
from app.domain.models import InboundMessage
from app.llm.client import get_chat_model
from app.llm.images import attach_images, inbound_image_markers, stored_attachments
from app.llm.prompts import SYSTEM_PROMPT
from app.telegram.sender import send_chat_action, send_message

logger = logging.getLogger(__name__)

FALLBACK_TEXT = "Lo siento, no he podido procesar tu mensaje. Inténtalo de nuevo en un momento."


@dataclass(frozen=True)
class HistorySender:
    """Detached speaker fields so history survives after the DB session closes."""

    display_name: str | None
    username: str | None
    telegram_user_id: int | None


@dataclass(frozen=True)
class HistoryTurn:
    """Detached message row used after the persist session is closed."""

    id: int
    role: MessageRole
    content: str
    attachments: list[dict] | None
    sender: HistorySender | None

    @classmethod
    def from_row(cls, row: Message) -> "HistoryTurn":
        sender = None
        if row.sender is not None:
            sender = HistorySender(
                display_name=row.sender.display_name,
                username=row.sender.username,
                telegram_user_id=row.sender.telegram_user_id,
            )
        return cls(
            id=row.id,
            role=row.role,
            content=row.content,
            attachments=row.attachments,
            sender=sender,
        )


async def respond_to_inbound(inbound: InboundMessage) -> None:
    """Handle one Telegram message:
    -> Show typing
    -> Persist the user turn and close the session
    -> Ask the LLM (no DB session held)
    -> Persist the reply
    -> Send it

    FALLBACK_TEXT is sent on failure but not stored. Persistence errors are
    logged; a fallback is still sent when possible. A long reply is stored
    in full and sent as several Telegram messages.
    """
    try:
        await send_chat_action(chat_id=inbound.chat_id, thread_id=inbound.thread_id)
    except Exception:
        logger.exception(
            f"Failed to send typing action chat_id={inbound.chat_id} thread_id={inbound.thread_id}"
        )

    reply = FALLBACK_TEXT
    conversation_id: int | None = None
    history: list[HistoryTurn] = []

    try:
        conversation_id, history = await _persist_user_turn(inbound)
    except Exception:
        logger.exception(
            f"Failed to persist or load history chat_id={inbound.chat_id} thread_id={inbound.thread_id}"
        )

    if history:
        try:
            reply = await _invoke_llm(history)
        except Exception:
            logger.exception(f"LLM call failed chat_id={inbound.chat_id} thread_id={inbound.thread_id}")
            reply = FALLBACK_TEXT

        if reply != FALLBACK_TEXT and conversation_id is not None:
            try:
                await _persist_assistant_turn(conversation_id, reply)
            except Exception:
                logger.exception(
                    f"Failed to persist assistant turn chat_id={inbound.chat_id} thread_id={inbound.thread_id}"
                )

    try:
        await send_message(chat_id=inbound.chat_id, text=reply, thread_id=inbound.thread_id)
    except Exception:
        logger.exception(f"Failed to send LLM reply chat_id={inbound.chat_id} thread_id={inbound.thread_id}")


async def _persist_user_turn(inbound: InboundMessage) -> tuple[int, list[HistoryTurn]]:
    async with session_factory() as session:
        user = await upsert_user(
            session,
            inbound.user_id,
            inbound.user_display_name,
            username=inbound.username,
            last_name=inbound.last_name,
            language_code=inbound.language_code,
        )
        conversation = await upsert_conversation(session, inbound.chat_id, inbound.thread_id)
        await append_message(
            session,
            conversation_id=conversation.id,
            sender_user_id=user.id,
            role=MessageRole.USER,
            content=_inbound_content(inbound),
            telegram_message_id=inbound.telegram_message_id,
            attachments=stored_attachments(inbound),
        )
        await session.commit()

        rows = await load_recent_messages(
            session,
            conversation.id,
            settings.llm_history_max_messages,
        )
        return conversation.id, [HistoryTurn.from_row(row) for row in rows]


async def _persist_assistant_turn(conversation_id: int, reply: str) -> None:
    async with session_factory() as session:
        await append_message(
            session,
            conversation_id=conversation_id,
            sender_user_id=None,
            role=MessageRole.ASSISTANT,
            content=reply,
        )
        await session.commit()


def _inbound_content(inbound: InboundMessage) -> str:
    """Build the stored user-turn text from caption/body plus attachment notes."""
    name = display_label(
        name=inbound.user_display_name,
        username=inbound.username,
        telegram_user_id=inbound.user_id,
    )
    parts: list[str] = []
    if inbound.text:
        parts.append(inbound.text)
    for attachment in inbound.attachments:
        if attachment.extracted_text:
            parts.append(f'{name} sent a {attachment.kind} (transcription): "{attachment.extracted_text}"')
            continue
        label = attachment.file_name
        if not label and attachment.local_path is not None:
            label = attachment.local_path.name
        if not label:
            label = attachment.kind
        parts.append(f"{name} sent a {attachment.kind}: {label}")
    parts.extend(inbound_image_markers(inbound))
    if not parts:
        return f"{name} sent a message"
    return "\n".join(parts)


async def _invoke_llm(history: list[HistoryTurn]) -> str:
    """Call the chat model with the system prompt plus topic history; return reply text.

    Only the latest user turn attaches image pixels. Older photo turns keep
    their text notes so the vision context stays bounded. Empty model output
    becomes FALLBACK_TEXT. The full reply is kept; Telegram splitting happens
    in send_message.
    """
    messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    current_id = _latest_user_message_id(history)
    messages.extend(_to_langchain(row, attach_pixels=row.id == current_id) for row in history)
    vision = _messages_have_images(messages)
    chat = get_chat_model(vision=vision)
    result = await chat.ainvoke(messages)
    text = _message_text(result.content)
    if not text:
        return FALLBACK_TEXT
    return text


def _latest_user_message_id(history: list[HistoryTurn]) -> int | None:
    for row in reversed(history):
        if row.role == MessageRole.USER:
            return row.id
    return None


def _to_langchain(row: HistoryTurn, *, attach_pixels: bool) -> BaseMessage:
    """Map one stored turn to a LangChain message (assistant vs speaker-labeled human)."""
    if row.role == MessageRole.ASSISTANT:
        return AIMessage(content=row.content)
    name = (
        display_label(
            name=row.sender.display_name,
            username=row.sender.username,
            telegram_user_id=row.sender.telegram_user_id,
        )
        if row.sender
        else "User"
    )
    text = f"{name}: {row.content}"
    if not attach_pixels:
        return HumanMessage(content=text)
    results = attach_images(row.attachments)
    blocks = [result.block for result in results if result.block is not None]
    markers = [result.skip_reason for result in results if result.skip_reason]
    if markers:
        text = "\n".join([text, *markers])
    if not blocks:
        return HumanMessage(content=text)
    logger.info(f"Attaching {len(blocks)} image(s) to user turn message_id={row.id}")
    return HumanMessage(content=[{"type": "text", "text": text}, *blocks])


def _messages_have_images(messages: list[BaseMessage]) -> bool:
    for message in messages:
        content = message.content
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_url":
                return True
    return False


def _message_text(content: object) -> str:
    """Flatten LangChain/provider content (string or content blocks) into plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text") or ""))
            elif hasattr(block, "text"):
                chunks.append(str(block.text))
        return "".join(chunks).strip()
    return str(content).strip() if content else ""
