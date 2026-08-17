import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TG_BASE_URL = "https://api.telegram.org"
BOT_ID = f"bot{settings.telegram_bot_token}"
DEFAULT_RESPONSE_TIMEOUT = 10.0

ACK_TEXT = "Your message has been received and will be processed shortly. Take a few seconds to relax."


async def send_message(
    chat_id: int,
    text: str,
    thread_id: int | None = None,
) -> None:
    """Send a text message via Telegram Bot API (same topic if thread_id is set)."""
    url = f"{TG_BASE_URL}/{BOT_ID}/sendMessage"

    payload: dict[str, object] = {"chat_id": chat_id, "text": text}
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    async with httpx.AsyncClient(timeout=DEFAULT_RESPONSE_TIMEOUT) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

    logger.info(f"Sent reply chat_id={chat_id} thread_id={thread_id} text={text[:80]}...")


async def send_ack(chat_id: int, thread_id: int | None = None) -> None:
    """Send the standard 'message received' acknowledgement."""
    await send_message(chat_id=chat_id, text=ACK_TEXT, thread_id=thread_id)
