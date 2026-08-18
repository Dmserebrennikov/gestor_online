import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TG_BASE_URL = "https://api.telegram.org"
BOT_ID = f"bot{settings.telegram_bot_token}"
DEFAULT_RESPONSE_TIMEOUT = 10.0
DEFAULT_BOT_EMOJI = "👀"
ACK_TEXT = "Your message has been received and will be processed shortly. Take a few seconds to relax."


async def _post_telegram(method: str, payload: dict[str, object]) -> None:
    url = f"{TG_BASE_URL}/{BOT_ID}/{method}"
    async with httpx.AsyncClient(timeout=DEFAULT_RESPONSE_TIMEOUT) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data}")


async def send_message(
    chat_id: int,
    text: str,
    thread_id: int | None = None,
) -> None:
    """Send a text message via Telegram Bot API (same topic if thread_id is set)."""
    payload = {"chat_id": chat_id, "text": text}
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    await _post_telegram("sendMessage", payload)
    logger.info(f"Sent reply chat_id={chat_id} thread_id={thread_id} text={text[:80]}...")


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


async def send_ack(chat_id: int, thread_id: int | None = None) -> None:
    """Send the standard 'message received' acknowledgement."""
    await send_message(chat_id=chat_id, text=ACK_TEXT, thread_id=thread_id)
