import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import settings
from app.telegram.adapter import adapt_update
from app.telegram.sender import send_ack

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    """Receive a Telegram Update, normalize it, log it, and send an ack reply."""
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret token",
        )

    update: dict[str, Any] = await request.json()
    inbound = adapt_update(update)

    if inbound is None:
        logger.debug("Ignoring non-message update_id=%s", update.get("update_id"))
        return {"ok": True}

    attachment_summary = [
        {
            "kind": a.kind,
            "file_id": a.telegram_file_id,
            "mime_type": a.mime_type,
            "file_name": a.file_name,
        }
        for a in inbound.attachments
    ]
    text_preview = (inbound.text or "")[:120]

    logger.info(
        "InboundMessage update_id=%s chat_id=%s thread_id=%s user_id=%s message_id=%s text=%r attachments=%s",
        inbound.update_id,
        inbound.chat_id,
        inbound.thread_id,
        inbound.user_id,
        inbound.telegram_message_id,
        text_preview,
        attachment_summary,
    )

    try:
        await send_ack(chat_id=inbound.chat_id, thread_id=inbound.thread_id)
    except Exception:
        logger.exception(
            "Failed to send ack chat_id=%s thread_id=%s",
            inbound.chat_id,
            inbound.thread_id,
        )

    return {"ok": True}
