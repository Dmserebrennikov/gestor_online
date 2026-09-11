import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import settings
from app.db.models import Message, MessageRole
from app.db.crud import append_message, load_recent_messages, upsert_conversation, upsert_user
from app.db.session import session_factory
from app.domain.models import InboundMessage
from app.llm.client import get_chat_model
from app.llm.images import attach_images, inbound_image_markers, stored_attachments
from app.llm.prompts import SYSTEM_PROMPT
from app.telegram.sender import send_chat_action, send_message

logger = logging.getLogger(__name__)

FALLBACK_TEXT = "Sorry, I couldn't process that just now. Please try again."


async def respond_to_inbound(inbound: InboundMessage) -> None:
    """Handle one Telegram message: 
    -> Show typing
    -> Persist it
    -> Ask the LLM
    -> Persist the reply
    -> Send it

    Shows typing first, then upserts the speaker and topic, stores the user turn,
    loads the last N messages of that topic, calls the model, stores the assistant
    turn when successful, then sends the reply in the same forum topic. FALLBACK_TEXT
    is sent on failure but not stored. Persistence errors are logged; a fallback is
    still sent when possible. A long reply is stored in full and sent as several
    Telegram messages.
    """
    try:
        await send_chat_action(chat_id=inbound.chat_id, thread_id=inbound.thread_id)
    except Exception:
        logger.exception(f"Failed to send typing action chat_id={inbound.chat_id} thread_id={inbound.thread_id}")
    
    reply = FALLBACK_TEXT
    try:
        async with session_factory() as session:
            user = await upsert_user(session, inbound.user_id, inbound.user_display_name)
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

            history = await load_recent_messages(
                session,
                conversation.id,
                settings.llm_history_max_messages,
            )

            try:
                reply = await _invoke_llm(history)
            except Exception:
                logger.exception(f"LLM call failed chat_id={inbound.chat_id} thread_id={inbound.thread_id}")
                reply = FALLBACK_TEXT

            if reply != FALLBACK_TEXT:
                await append_message(
                    session,
                    conversation_id=conversation.id,
                    sender_user_id=None,
                    role=MessageRole.ASSISTANT,
                    content=reply,
                )
                await session.commit()
    except Exception:
        logger.exception(f"Failed to persist or load history chat_id={inbound.chat_id} thread_id={inbound.thread_id}")

    try:
        await send_message(chat_id=inbound.chat_id, text=reply, thread_id=inbound.thread_id)
    except Exception:
        logger.exception(f"Failed to send LLM reply chat_id={inbound.chat_id} thread_id={inbound.thread_id}")


def _inbound_content(inbound: InboundMessage) -> str:
    """Build the stored user-turn text from caption/body plus attachment notes."""
    name = inbound.user_display_name or "User"
    parts: list[str] = []
    if inbound.text:
        parts.append(inbound.text)
    for attachment in inbound.attachments:
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


async def _invoke_llm(history: list[Message]) -> str:
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


def _latest_user_message_id(history: list[Message]) -> int | None:
    for row in reversed(history):
        if row.role == MessageRole.USER:
            return row.id
    return None


def _to_langchain(row: Message, *, attach_pixels: bool) -> BaseMessage:
    """Map one stored turn to a LangChain message (assistant vs speaker-labeled human)."""
    if row.role == MessageRole.ASSISTANT:
        return AIMessage(content=row.content)
    name = row.sender.display_name if row.sender and row.sender.display_name else "User"
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
