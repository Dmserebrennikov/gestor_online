from pathlib import Path
from typing import Any, Literal

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
    thread_id: int | None = None
    user_id: int | None = None
    text: str | None = None
    attachments: list[MediaAttachment] = Field(default_factory=list)
    telegram_message_id: int
    raw_update: dict[str, Any] | None = None
