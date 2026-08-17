from typing import Any

from app.domain.models import InboundMessage, MediaAttachment, MediaKind


def adapt_update(update: dict[str, Any]) -> InboundMessage | None:
    """Normalize a Telegram Update into InboundMessage, or None if not processable."""
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None

    from_user = message.get("from") or {}
    if from_user.get("is_bot"):
        return None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        return None

    text = message.get("text") or message.get("caption")
    caption = message.get("caption")
    attachments = _extract_attachments(message, caption)

    return InboundMessage(
        update_id=int(update["update_id"]),
        chat_id=int(chat_id),
        thread_id=message.get("message_thread_id"),
        user_id=from_user.get("id"),
        text=text,
        attachments=attachments,
        telegram_message_id=int(message_id),
        raw_update=update,
    )


def _extract_attachments(
    message: dict[str, Any],
    caption: str | None,
) -> list[MediaAttachment]:
    """Collect photo/video/document/audio/voice attachments from a message."""
    attachments: list[MediaAttachment] = []

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = max(photos, key=lambda p: p.get("file_size") or 0)
        attachments.append(
            _attachment_from_file(
                kind="photo",
                file_obj=largest,
                caption=caption,
            )
        )

    media_fields: list[tuple[MediaKind, str]] = [
        ("video", "video"),
        ("document", "document"),
        ("audio", "audio"),
        ("voice", "voice"),
    ]
    for kind, key in media_fields:
        file_obj = message.get(key)
        if isinstance(file_obj, dict):
            attachments.append(
                _attachment_from_file(
                    kind=kind,
                    file_obj=file_obj,
                    caption=caption,
                )
            )

    return attachments


def _attachment_from_file(
    *,
    kind: MediaKind,
    file_obj: dict[str, Any],
    caption: str | None,
) -> MediaAttachment:
    """Build a MediaAttachment from a Telegram file object (no download)."""
    return MediaAttachment(
        kind=kind,
        telegram_file_id=file_obj["file_id"],
        file_unique_id=file_obj.get("file_unique_id"),
        mime_type=file_obj.get("mime_type"),
        file_name=file_obj.get("file_name"),
        local_path=None,
        extracted_text=None,
        caption=caption,
    )
