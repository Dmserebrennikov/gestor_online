import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.config import settings
from app.domain.models import InboundMessage
from app.llm.pipeline import respond_to_inbound
from app.telegram.adapter import adapt_update
from app.telegram.album import wait_for_full_send
from app.telegram.media import store_inbound_attachments
from app.telegram.sender import send_bot_reaction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


def validate_token(token: str | None, secret: str) -> None:
    if token != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret token",
        )


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    """
    - Validate token
    - Adapt message
    - Set reaction
    - Send http response
    - Queue background task: wait for sibling updates, download files, LLM reply

    Telegram expects a webhook to return quickly. Downloads, grouping, the LLM,
    DB writes, and outbound messages must not run inside this request, or
    Telegram may retry or mark the webhook as failing.

    Downloads wait until after sibling updates are merged. A later photo in the
    same send can take seconds to download; if we downloaded first, the quiet
    timer would fire and treat each photo as its own turn.

    Thus we handle the fast path here, and queue the slow work in the background 
    (throught the use of the BackgroundTasks) after the response is sent.
    """
    validate_token(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret)

    update: dict[str, Any] = await request.json()
    inbound = adapt_update(update)
    if inbound is None:
        logger.debug("Ignoring unprocessable update_id=%s", update.get("update_id"))
        return {"ok": True}

    try:
        await send_bot_reaction(
            chat_id=inbound.chat_id,
            message_id=inbound.telegram_message_id,
        )
    except Exception:
        logger.exception(
            "Failed to set reaction chat_id=%s message_id=%s",
            inbound.chat_id,
            inbound.telegram_message_id,
        )

    text_preview = (inbound.text or "")[:120]
    logger.info(
        "InboundMessage update_id=%s chat_id=%s thread_id=%s user_id=%s name=%s message_id=%s text=%r attachments=%s",
        inbound.update_id,
        inbound.chat_id,
        inbound.thread_id,
        inbound.user_id,
        inbound.user_display_name,
        inbound.telegram_message_id,
        text_preview,
        [{"kind": a.kind, "file_id": a.telegram_file_id} for a in inbound.attachments],
    )

    background_tasks.add_task(_respond_when_complete, inbound)
    return {"ok": True}


async def _respond_when_complete(inbound: InboundMessage) -> None:
    """Assemble one user send, download its files, then reply once.

    Two separate waits, in order:

    1. ``wait_for_full_send`` — 0.8s quiet time after the last *webhook*.
       Only metadata (kind, file_id) is merged. No download. A later photo
       of the same send must arrive as an HTTP update within that window.
    2. ``store_inbound_attachments`` — fetch bytes for every file_id already
       on the merged inbound. One file can take several seconds; that does
       not reopen the grouping window.

    Earlier sibling tasks return here when step 1 yields None. Only the last
    waiter downloads and calls the reply pipeline.
    """
    full_inbound = await wait_for_full_send(inbound)
    if full_inbound is None:
        return
    await store_inbound_attachments(full_inbound)
    logger.info(
        "Complete send chat_id=%s thread_id=%s message_id=%s attachments=%s",
        full_inbound.chat_id,
        full_inbound.thread_id,
        full_inbound.telegram_message_id,
        [
            {
                "kind": a.kind,
                "file_id": a.telegram_file_id,
                "mime_type": a.mime_type,
                "file_name": a.file_name,
                "local_path": str(a.local_path) if a.local_path else None,
            }
            for a in full_inbound.attachments
        ],
    )
    await respond_to_inbound(full_inbound)
