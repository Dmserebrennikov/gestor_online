import logging

from telegramify_markdown import convert, split_entities

from app.telegram.http import TelegramAPIError, post_method

logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_TIMEOUT = 10.0
DEFAULT_BOT_EMOJI = "👀"

TELEGRAM_TEXT_LIMIT = 4096


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split text into chunks that fit Telegram's sendMessage limit, preferring newlines then spaces."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        if length - start <= limit:
            chunks.append(text[start:])
            break
        window = text[start : start + limit]
        break_at = window.rfind("\n")
        if break_at <= 0:
            break_at = window.rfind(" ")
        if break_at <= 0:
            break_at = limit
        chunks.append(text[start : start + break_at])
        start += break_at
        while start < length and text[start] in " \n":
            start += 1
    return [chunk for chunk in chunks if chunk]


def _message_chunks(text: str) -> list[tuple[str, list[dict[str, object]]]]:
    """Turn Markdown into Telegram text + MessageEntity dicts, split to the 4096 limit."""
    plain, entities = convert(text)
    return [
        (chunk_text, [entity.to_dict() for entity in chunk_entities])
        for chunk_text, chunk_entities in split_entities(plain, entities, max_utf16_len=TELEGRAM_TEXT_LIMIT)
    ]


async def _post_telegram(method: str, payload: dict[str, object]) -> None:
    await post_method(method, payload, DEFAULT_RESPONSE_TIMEOUT)


async def send_message(
    chat_id: int,
    text: str,
    thread_id: int | None = None,
) -> None:
    """Send a text message via Telegram Bot API (same topic if thread_id is set).

    Markdown is converted to Telegram ``entities`` (no ``parse_mode``). Long
    replies are split into several messages so nothing is truncated. If Telegram
    rejects the entities, the same chunk is resent as plain text.
    """
    if not text:
        logger.warning("Skipping empty Telegram message chat_id=%s thread_id=%s", chat_id, thread_id)
        return

    try:
        chunks = _message_chunks(text)
    except Exception:
        logger.exception("Markdown conversion failed; sending as plain text")
        chunks = [(chunk, []) for chunk in split_telegram_text(text)]

    if not chunks:
        logger.warning("Skipping empty Telegram message chat_id=%s thread_id=%s", chat_id, thread_id)
        return

    for chunk_text, entities in chunks:
        payload: dict[str, object] = {"chat_id": chat_id, "text": chunk_text}
        if entities:
            payload["entities"] = entities
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        try:
            await _post_telegram("sendMessage", payload)
        except TelegramAPIError:
            logger.warning(
                "Telegram rejected entities; retrying as plain text chat_id=%s thread_id=%s",
                chat_id,
                thread_id,
            )
            plain: dict[str, object] = {"chat_id": chat_id, "text": chunk_text}
            if thread_id is not None:
                plain["message_thread_id"] = thread_id
            await _post_telegram("sendMessage", plain)
        logger.info("Sent reply chat_id=%s thread_id=%s text=%s...", chat_id, thread_id, chunk_text[:80])


async def send_bot_reaction(
    chat_id: int,
    message_id: int,
    emoji: str = DEFAULT_BOT_EMOJI,
) -> None:
    """Send reaction on the user's message so he can see the bot has received it."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
    }
    await _post_telegram("setMessageReaction", payload)
    logger.info(f"Sent reaction {emoji} chat_id={chat_id} message_id={message_id}")


async def send_chat_action(
    chat_id: int,
    thread_id: int | None = None,
    action: str = "typing",
) -> None:
    """Show a chat action (default typing...) in the topic."""
    payload = {"chat_id": chat_id, "action": action}
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    await _post_telegram("sendChatAction", payload)
    logger.info("Sent chat action %s chat_id=%s thread_id=%s", action, chat_id, thread_id)
