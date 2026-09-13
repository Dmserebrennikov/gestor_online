import asyncio
from pathlib import Path

import pytest

from app.config import settings
from app.domain.models import InboundMessage, MediaAttachment
from app.llm import transcription as stt
from app.llm.transcription import (
    TranscriptionError,
    _language_hint,
    _upload_name,
    transcribe_file,
    transcribe_inbound_attachments,
)


def _inbound(**kwargs: object) -> InboundMessage:
    return InboundMessage(
        update_id=1,
        chat_id=1,
        telegram_message_id=1,
        user_id=1,
        **kwargs,  # type: ignore[arg-type]
    )


def _attachment(kind: str, path: Path | None, mime_type: str | None = None) -> MediaAttachment:
    return MediaAttachment(kind=kind, telegram_file_id="f1", local_path=path, mime_type=mime_type)


def test_language_hint_prefers_telegram_language_code() -> None:
    assert _language_hint(_inbound(language_code="es-419")) == "es"
    assert _language_hint(_inbound(language_code="en")) == "en"


def test_language_hint_falls_back_to_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stt_language", "gl")
    assert _language_hint(_inbound(language_code=None)) == "gl"
    monkeypatch.setattr(settings, "stt_language", None)
    assert _language_hint(_inbound(language_code=None)) is None


def test_upload_name_keeps_supported_suffixes() -> None:
    assert _upload_name(Path("nota.ogg"), "audio/ogg") == "nota.ogg"
    assert _upload_name(Path("song.MP3"), "audio/mpeg") == "song.MP3"


def test_upload_name_remaps_oga_to_ogg() -> None:
    # Telegram voice notes arrive as .oga, which the API rejects.
    assert _upload_name(Path("AgADPqQAAr_TMUk.oga"), "audio/ogg") == "AgADPqQAAr_TMUk.ogg"


def test_upload_name_falls_back_to_mime_then_ogg() -> None:
    assert _upload_name(Path("audio.bin"), "audio/mpeg") == "audio.mp3"
    assert _upload_name(Path("audio.bin"), None) == "audio.ogg"


def test_transcribe_file_returns_stripped_text(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "nota.oga"
    audio.write_bytes(b"ogg-bytes")
    seen: dict[str, object] = {}

    async def fake_post(path: Path, language: str | None, mime_type: str | None) -> dict:
        seen["path"] = path
        seen["language"] = language
        seen["mime_type"] = mime_type
        return {"text": "  hola, ¿qué tal?  "}

    monkeypatch.setattr(stt, "_post_transcription", fake_post)
    text = asyncio.run(transcribe_file(audio, language="es", mime_type="audio/ogg"))
    assert text == "hola, ¿qué tal?"
    assert seen == {"path": audio, "language": "es", "mime_type": "audio/ogg"}


def test_transcribe_file_rejects_empty_text(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "nota.ogg"
    audio.write_bytes(b"ogg-bytes")

    async def fake_post(path: Path, language: str | None, mime_type: str | None) -> dict:
        return {"text": "   "}

    monkeypatch.setattr(stt, "_post_transcription", fake_post)
    with pytest.raises(TranscriptionError):
        asyncio.run(transcribe_file(audio, language=None))


def test_post_transcription_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "nota.ogg"
    audio.write_bytes(b"ogg-bytes")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TranscriptionError, match="OPENAI_API_KEY"):
        asyncio.run(stt._post_transcription(audio, "es", "audio/ogg"))


def test_inbound_fills_voice_and_audio_only(tmp_path: Path, monkeypatch) -> None:
    voice_path = tmp_path / "v.oga"
    voice_path.write_bytes(b"v")
    audio_path = tmp_path / "a.mp3"
    audio_path.write_bytes(b"a")
    photo = _attachment("photo", tmp_path / "p.jpg")
    voice = _attachment("voice", voice_path, "audio/ogg")
    audio = _attachment("audio", audio_path, "audio/mpeg")
    not_downloaded = _attachment("voice", None)
    inbound = _inbound(language_code="es", attachments=[photo, voice, audio, not_downloaded])
    calls: list[tuple[Path, str | None, str | None]] = []

    async def fake_transcribe(path: Path, *, language: str | None, mime_type: str | None) -> str:
        calls.append((path, language, mime_type))
        return f"texto de {path.name}"

    monkeypatch.setattr(stt, "transcribe_file", fake_transcribe)
    asyncio.run(transcribe_inbound_attachments(inbound))

    assert calls == [(voice_path, "es", "audio/ogg"), (audio_path, "es", "audio/mpeg")]
    assert voice.extracted_text == "texto de v.oga"
    assert audio.extracted_text == "texto de a.mp3"
    assert photo.extracted_text is None
    assert not_downloaded.extracted_text is None


def test_inbound_continues_when_one_transcription_fails(tmp_path: Path, monkeypatch) -> None:
    first = _attachment("voice", tmp_path / "one.ogg")
    second = _attachment("voice", tmp_path / "two.ogg")
    inbound = _inbound(attachments=[first, second])

    async def fake_transcribe(path: Path, *, language: str | None, mime_type: str | None) -> str:
        if path.name == "one.ogg":
            raise TranscriptionError("provider down")
        return "vale"

    monkeypatch.setattr(stt, "transcribe_file", fake_transcribe)
    asyncio.run(transcribe_inbound_attachments(inbound))

    assert first.extracted_text is None
    assert second.extracted_text == "vale"


def test_inbound_without_audio_is_a_noop(monkeypatch) -> None:
    inbound = _inbound(attachments=[_attachment("photo", Path("p.jpg"))])

    async def fake_transcribe(path: Path, *, language: str | None, mime_type: str | None) -> str:
        raise AssertionError("should not be called")

    monkeypatch.setattr(stt, "transcribe_file", fake_transcribe)
    asyncio.run(transcribe_inbound_attachments(inbound))
