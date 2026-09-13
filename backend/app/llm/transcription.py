import logging
import os
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.domain.models import InboundMessage

logger = logging.getLogger(__name__)

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"

# Telegram voice notes are Ogg/Opus; the API also takes mp3, m4a, wav, webm, …
_TRANSCRIBABLE_KINDS = ("voice", "audio")

# OpenAI keys the format off the upload filename and rejects ".oga", even though
# it is the same Ogg container as ".ogg" (Telegram voice notes arrive as ".oga").
_SUPPORTED_SUFFIXES = {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}
_MIME_SUFFIX = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
}


class TranscriptionError(RuntimeError):
    """Speech-to-text failed; the reply pipeline must continue without it."""


async def transcribe_inbound_attachments(inbound: InboundMessage) -> None:
    """Fill ``extracted_text`` on every downloaded voice/audio attachment.

    Call after ``store_inbound_attachments`` so files are already on disk and
    before the turn is persisted, so the transcript is stored with the turn.
    Each failure is logged and skipped: a missing transcript must never block
    the reply.
    """
    targets = [
        attachment
        for attachment in inbound.attachments
        if attachment.kind in _TRANSCRIBABLE_KINDS and attachment.local_path is not None
    ]
    if not targets:
        return
    language = _language_hint(inbound)
    for attachment in targets:
        try:
            attachment.extracted_text = await transcribe_file(
                attachment.local_path,
                language=language,
                mime_type=attachment.mime_type,
            )
            logger.info(
                "Transcribed attachment kind=%s path=%s chat_id=%s chars=%s",
                attachment.kind,
                attachment.local_path,
                inbound.chat_id,
                len(attachment.extracted_text or ""),
            )
        except Exception:
            logger.exception(
                "Failed to transcribe attachment kind=%s path=%s chat_id=%s",
                attachment.kind,
                attachment.local_path,
                inbound.chat_id,
            )


def _language_hint(inbound: InboundMessage) -> str | None:
    """Prefer the sender's Telegram language_code ('es-419' -> 'es'); else the STT default."""
    code = (inbound.language_code or "").split("-", 1)[0].strip().lower()
    if code:
        return code
    return settings.stt_language


async def transcribe_file(path: Path, *, language: str | None = None, mime_type: str | None = None) -> str:
    """Transcribe one audio file with the configured OpenAI model; return plain text."""
    payload = await _post_transcription(path, language, mime_type)
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise TranscriptionError(f"OpenAI transcription returned no text for {path.name}")
    return text.strip()


def _upload_name(path: Path, mime_type: str | None) -> str:
    """Filename sent to the API: keep supported suffixes, remap the rest (e.g. .oga -> .ogg)."""
    if path.suffix.lower() in _SUPPORTED_SUFFIXES:
        return path.name
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    return f"{path.stem}{_MIME_SUFFIX.get(mime, '.ogg')}"


async def _post_transcription(path: Path, language: str | None, mime_type: str | None) -> dict[str, Any]:
    """HTTP seam (mocked in tests). Returns the decoded JSON body."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "OPENAI_API_KEY is not set. Add it to the repo-root .env so voice/audio notes can be transcribed."
        )
    try:
        audio = path.read_bytes()
    except OSError as exc:
        raise TranscriptionError(f"Cannot read audio file path={path}") from exc
    data: dict[str, str] = {"model": settings.stt_model}
    if language:
        data["language"] = language
    files = {"file": (_upload_name(path, mime_type), audio, "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=settings.stt_timeout) as client:
            response = await client.post(
                OPENAI_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files=files,
            )
    except httpx.HTTPError:
        raise TranscriptionError(f"OpenAI transcription request failed for {path.name}") from None
    if response.is_error:
        raise TranscriptionError(f"OpenAI transcription HTTP {response.status_code}: {response.text[:200]}")
    try:
        body = response.json()
    except ValueError:
        raise TranscriptionError(f"OpenAI transcription returned non-JSON for {path.name}") from None
    if not isinstance(body, dict):
        raise TranscriptionError(f"OpenAI transcription returned unexpected JSON for {path.name}")
    return body
