from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


MediaKind = Literal["photo", "video", "document", "audio", "voice", "other"]


class MediaAttachment(BaseModel):
    """File attached to a Telegram message"""

    kind: MediaKind
    telegram_file_id: str
    file_unique_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    local_path: Path | None = None
    extracted_text: str | None = None
    caption: str | None = None


class InboundMessage(BaseModel):
    """Provider-agnostic message normalized from a Telegram Update."""

    update_id: int
    chat_id: int
    telegram_message_id: int
    user_id: int
    thread_id: int | None = None
    user_display_name: str | None = None
    text: str | None = None
    attachments: Annotated[list[MediaAttachment], Field(default_factory=list)]
    raw_update: dict[str, Any] | None = None
