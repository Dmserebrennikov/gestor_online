"""Merge Telegram album parts that arrive as separate webhook updates."""

import asyncio
import logging

from app.domain.models import InboundMessage

logger = logging.getLogger(__name__)

# Quiet time after the last webhook of a split send. Not download time.
ALBUM_DEBOUNCE_SECONDS = 0.8

_pending: dict[tuple[int, int | None, str], InboundMessage] = {}
_generation: dict[tuple[int, int | None, str], int] = {}
_lock = asyncio.Lock()


def _album_key(inbound: InboundMessage) -> tuple[int, int | None, str] | None:
    if not inbound.media_group_id:
        return None
    return (inbound.chat_id, inbound.thread_id, inbound.media_group_id)


def _merge(base: InboundMessage, incoming: InboundMessage) -> None:
    base.attachments.extend(incoming.attachments)
    if incoming.text and not base.text:
        base.text = incoming.text
    if incoming.update_id > base.update_id:
        base.update_id = incoming.update_id


async def wait_for_full_send(inbound: InboundMessage) -> InboundMessage | None:
    """
    Wait for the full user send: aggregate all parts/metadata of a split send.
    
    Merge sibling webhooks of one send. Does not download files.

    Telegram can deliver one send as several updates that share
    ``media_group_id``. This waits ``ALBUM_DEBOUNCE_SECONDS`` (0.8s) after the
    latest of those *HTTP updates*, then returns one inbound with every
    attachment's file_id. Download time is irrelevant here and must happen
    afterwards: a 4s getFile would otherwise expire this timer before the
    sibling update is even registered.

    - No ``media_group_id``: return ``inbound`` immediately (no 0.8s wait).
    - Shared ``media_group_id``: merge metadata, sleep 0.8s, return the
      combined inbound once no new update arrives.
    - Only the last waiting call returns that inbound. Earlier calls return
      None so download and the reply pipeline run once.
    """
    key = _album_key(inbound)
    if key is None:
        return inbound

    async with _lock:
        existing = _pending.get(key)
        if existing is None:
            _pending[key] = inbound
        else:
            _merge(existing, inbound)
        _generation[key] = _generation.get(key, 0) + 1
        generation = _generation[key]
        logger.info(
            "Album part chat_id=%s group=%s parts=%s generation=%s",
            inbound.chat_id,
            inbound.media_group_id,
            len(_pending[key].attachments),
            generation,
        )

    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)

    async with _lock:
        if _generation.get(key) != generation:
            return None
        merged = _pending.pop(key, None)
        _generation.pop(key, None)
        return merged
