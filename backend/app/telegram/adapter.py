from typing import Any

from app.domain.identity import compose_display_name
from app.domain.models import InboundMessage, MediaAttachment, MediaKind


def adapt_update(update: dict[str, Any]) -> InboundMessage | None:
    """Normalize a Telegram Update into InboundMessage, or None if not processable.

    Only new ``message`` updates from human senders with a Telegram user id
    are accepted. ``edited_message``, ``channel_post``, bots, anonymous
    admins, and other payloads without ``from.id`` are skipped.
    """
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    from_user = message.get("from")
    if not isinstance(from_user, dict) or from_user.get("is_bot"):
        return None
    user_id = from_user.get("id")
    if user_id is None:
        return None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        return None

    text = message.get("text") or message.get("caption")
    caption = message.get("caption")
    attachments = _extract_attachments(message, caption)
    first_name = from_user.get("first_name")
    last_name = from_user.get("last_name")
    username = from_user.get("username")
    language_code = from_user.get("language_code")
    media_group_id = message.get("media_group_id")

    return InboundMessage(
        update_id=int(update["update_id"]),
        chat_id=int(chat_id),
        thread_id=message.get("message_thread_id"),
        user_id=int(user_id),
        user_display_name=compose_display_name(
            str(first_name) if first_name else None,
            str(last_name) if last_name else None,
        ),
        first_name=str(first_name) if first_name else None,
        last_name=str(last_name) if last_name else None,
        username=str(username) if username else None,
        language_code=str(language_code) if language_code else None,
        text=text,
        media_group_id=str(media_group_id) if media_group_id else None,
        attachments=attachments,
        telegram_message_id=int(message_id),
    )


def _extract_attachments(
    message: dict[str, Any],
    caption: str | None,
) -> list[MediaAttachment]:
    """Collect photo/sticker/animation plus video/document/audio/voice attachments."""
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

    sticker = message.get("sticker")
    if isinstance(sticker, dict) and not sticker.get("is_animated") and not sticker.get("is_video"):
        attachments.append(
            _attachment_from_file(
                kind="sticker",
                file_obj=sticker,
                caption=caption,
                default_mime="image/webp",
            )
        )

    animation = message.get("animation")
    if isinstance(animation, dict):
        attachments.append(
            _attachment_from_file(
                kind="animation",
                file_obj=animation,
                caption=caption,
            )
        )

    # Animation messages also set ``document`` for backward compatibility.
    media_fields: list[tuple[MediaKind, str]] = [
        ("video", "video"),
        ("audio", "audio"),
        ("voice", "voice"),
    ]
    if not isinstance(animation, dict):
        media_fields.insert(1, ("document", "document"))
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
    default_mime: str | None = None,
) -> MediaAttachment:
    """Build a MediaAttachment from a Telegram file object (no download)."""
    return MediaAttachment(
        kind=kind,
        telegram_file_id=file_obj["file_id"],
        file_unique_id=file_obj.get("file_unique_id"),
        mime_type=file_obj.get("mime_type") or default_mime,
        file_name=file_obj.get("file_name"),
        local_path=None,
        extracted_text=None,
        caption=caption,
    )
