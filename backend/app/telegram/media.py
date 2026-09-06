import logging
from pathlib import Path

from app.domain.models import InboundMessage, MediaAttachment, MediaKind
from app.telegram.http import download_file, get_method

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 30.0
MEDIA_DIR = Path(__file__).resolve().parents[2] / "media"

_DEFAULT_EXTENSION: dict[MediaKind, str] = {
    "photo": ".jpg",
    "video": ".mp4",
    "document": ".bin",
    "audio": ".mp3",
    "voice": ".ogg",
    "other": ".bin",
}


async def store_inbound_attachments(inbound: InboundMessage) -> None:
    """Download every inbound attachment into media/<kind>/."""
    for attachment in inbound.attachments:
        try:
            attachment.local_path = await download_telegram_file(attachment)
            logger.info(
                "Stored attachment kind=%s path=%s chat_id=%s",
                attachment.kind,
                attachment.local_path,
                inbound.chat_id,
            )
        except Exception:
            logger.exception(
                "Failed to store attachment kind=%s file_id=%s chat_id=%s",
                attachment.kind,
                attachment.telegram_file_id,
                inbound.chat_id,
            )


async def download_telegram_file(attachment: MediaAttachment) -> Path:
    """Resolve a Telegram attachment by file_id and download it to internal storage under media/<kind>/."""
    meta = await get_method(
        "getFile",
        {"file_id": attachment.telegram_file_id},
        DOWNLOAD_TIMEOUT,
    )
    result = meta["result"]
    file_path = result["file_path"]
    unique_id = result.get("file_unique_id") or attachment.file_unique_id or attachment.telegram_file_id
    dest = _destination(attachment.kind, unique_id, file_path, attachment.file_name)
    dest.write_bytes(await download_file(file_path, DOWNLOAD_TIMEOUT))

    logger.info("Downloaded Telegram file file_id=%s path=%s", attachment.telegram_file_id, dest)
    return dest


def _destination(kind: MediaKind, unique_id: str, file_path: str, file_name: str | None) -> Path:
    """Build 'media/<kind>/<unique_name>.<extension>' path, creating the kind folder if needed."""
    dest_dir = MEDIA_DIR / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"{_safe_name(unique_id)}{_extension(file_path, file_name, kind)}"


def _safe_name(input_name: str) -> str:
    """Keep only letters, digits, '-' and '_', so it is a safe filename."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in input_name)


def _extension(file_path: str, file_name: str | None, kind: MediaKind) -> str:
    """Pick a short alphanumeric extension from Telegram's path or filename, else a kind default."""
    for candidate in (Path(file_path).suffix, Path(file_name or "").suffix):
        ext = candidate.lower()
        if ext.startswith(".") and ext[1:].isalnum() and len(ext) <= 8:
            return ext
    return _DEFAULT_EXTENSION[kind]
