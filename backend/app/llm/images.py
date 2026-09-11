import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from app.domain.models import InboundMessage, MediaAttachment
from app.telegram.media import MEDIA_DIR

logger = logging.getLogger(__name__)

# Vision APIs accept these as data-URI image_url parts.
_VISION_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
_CONVERT_MIMES = {
    "image/heic",
    "image/heif",
    "image/heic-sequence",
    "image/heif-sequence",
    "image/avif",
    "image/bmp",
    "image/x-ms-bmp",
    "image/tiff",
    "image/tif",
    "image/x-tiff",
}
_SUFFIX_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_KIND_MIME = {
    "photo": "image/jpeg",
    "sticker": "image/webp",
}
_RASTER_MIMES = _VISION_MIMES | _CONVERT_MIMES | {"image/jpg"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_SNIFF_BYTES = 64

MARKER_NOT_STORED = "[Image could not be stored]"
MARKER_NOT_READ = "[Image could not be read]"
MARKER_EMPTY = "[Image was empty]"
MARKER_TOO_LARGE = "[Image too large]"
MARKER_UNSUPPORTED = "[Image format not supported]"

_heif_registered = False


@dataclass(frozen=True)
class ImageAttachResult:
    """One stored attachment after the vision-attach attempt."""

    block: dict[str, Any] | None
    skip_reason: str | None
    intended: bool


def looks_like_image(
    *,
    mime_type: object = None,
    path: Path | None = None,
    kind: object = None,
    file_name: object = None,
    header: bytes | None = None,
) -> bool:
    """True when kind, MIME, suffix, or magic bytes say this is a raster image."""
    if header:
        sniffed = sniff_image_mime(header)
        if sniffed:
            return True
    mime = _declared_raster_mime(mime_type)
    if mime:
        return True
    for candidate in (path, Path(file_name) if isinstance(file_name, str) and file_name else None):
        if candidate is not None and candidate.suffix.lower() in _SUFFIX_MIME:
            return True
    return kind in _KIND_MIME


def sniff_image_mime(data: bytes) -> str | None:
    """Detect a raster image MIME from magic bytes. SVG and other XML are ignored."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    brand = _iso_brand(data)
    if brand in {"avif", "avis"}:
        return "image/avif"
    if brand in {"heic", "heix", "heif", "hevc", "heis", "mif1", "msf1"}:
        return "image/heic" if brand.startswith("hei") else "image/heif"
    return None


def stored_attachments(inbound: InboundMessage) -> list[dict[str, str]] | None:
    """Serialize downloaded files so later turns can re-attach images."""
    items: list[dict[str, str]] = []
    for attachment in inbound.attachments:
        if attachment.local_path is None:
            continue
        rel_path = _relative_media_path(attachment.local_path)
        if rel_path is None:
            continue
        items.append(
            {
                "kind": attachment.kind,
                "rel_path": rel_path,
                "mime_type": _mime_type(attachment),
            }
        )
    return items or None


def inbound_image_markers(inbound: InboundMessage) -> list[str]:
    """Persist-time markers for image attachments that never reached disk."""
    markers: list[str] = []
    for attachment in inbound.attachments:
        if not looks_like_image(
            mime_type=attachment.mime_type,
            path=attachment.local_path,
            kind=attachment.kind,
            file_name=attachment.file_name,
        ):
            continue
        if attachment.local_path is None:
            markers.append(MARKER_NOT_STORED)
    return markers


def image_blocks(payload: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Build OpenAI-style image_url blocks from stored attachment metadata."""
    return [result.block for result in attach_images(payload) if result.block is not None]


def attach_images(payload: list[dict[str, Any]] | None) -> list[ImageAttachResult]:
    """Try to attach each stored file; record a skip reason when it looked like an image."""
    if not payload:
        return []
    return [_attach_one(item) for item in payload]


def _attach_one(item: dict[str, Any]) -> ImageAttachResult:
    rel_path = item.get("rel_path")
    path: Path | None = None
    header: bytes | None = None
    if isinstance(rel_path, str) and rel_path:
        path = _absolute_media_path(rel_path)
        if path is not None and path.is_file():
            try:
                header = path.read_bytes()[:_SNIFF_BYTES]
            except OSError:
                header = None
    intended = looks_like_image(
        mime_type=item.get("mime_type"),
        path=path,
        kind=item.get("kind"),
        file_name=rel_path if isinstance(rel_path, str) else None,
        header=header,
    )
    if not isinstance(rel_path, str) or not rel_path:
        return ImageAttachResult(None, MARKER_NOT_READ if intended else None, intended)
    if path is None:
        logger.warning("Skipping image outside media dir rel_path=%s", rel_path)
        return ImageAttachResult(None, MARKER_NOT_READ if intended else None, intended)
    if not path.is_file():
        logger.warning("Skipping missing image path=%s", path)
        return ImageAttachResult(None, MARKER_NOT_READ if intended else None, intended)
    try:
        size = path.stat().st_size
    except OSError:
        logger.exception("Failed to stat image path=%s", path)
        return ImageAttachResult(None, MARKER_NOT_READ if intended else None, intended)
    if intended and size > _MAX_IMAGE_BYTES:
        logger.warning("Skipping oversized image path=%s size=%s", path, size)
        return ImageAttachResult(None, MARKER_TOO_LARGE, True)
    try:
        data = path.read_bytes()
    except OSError:
        logger.exception("Failed to read image path=%s", path)
        return ImageAttachResult(None, MARKER_NOT_READ if intended else None, intended)
    intended = intended or bool(sniff_image_mime(data))
    if not intended:
        return ImageAttachResult(None, None, False)
    if not data:
        logger.warning("Skipping empty image path=%s", path)
        return ImageAttachResult(None, MARKER_EMPTY, True)
    if len(data) > _MAX_IMAGE_BYTES:
        logger.warning("Skipping oversized image path=%s size=%s", path, len(data))
        return ImageAttachResult(None, MARKER_TOO_LARGE, True)
    mime = sniff_image_mime(data) or _normalize_mime(item.get("mime_type"), path, item.get("kind"))
    if mime is None:
        return ImageAttachResult(None, MARKER_UNSUPPORTED, True)
    converted = _to_vision_bytes(data, mime)
    if converted is None:
        return ImageAttachResult(None, MARKER_UNSUPPORTED, True)
    vision_bytes, vision_mime = converted
    if len(vision_bytes) > _MAX_IMAGE_BYTES:
        logger.warning("Skipping oversized converted image path=%s size=%s", path, len(vision_bytes))
        return ImageAttachResult(None, MARKER_TOO_LARGE, True)
    encoded = base64.b64encode(vision_bytes).decode("ascii")
    return ImageAttachResult(
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{vision_mime};base64,{encoded}",
                "detail": "high",
            },
        },
        None,
        True,
    )


def _mime_type(attachment: MediaAttachment) -> str:
    header: bytes | None = None
    if attachment.local_path is not None:
        confined = _confined_media_path(attachment.local_path)
        if confined is not None and confined.is_file():
            try:
                header = confined.read_bytes()[:_SNIFF_BYTES]
            except OSError:
                header = None
    sniffed = sniff_image_mime(header) if header else None
    mime = sniffed or _normalize_mime(attachment.mime_type, attachment.local_path, attachment.kind)
    return mime or "application/octet-stream"


def _declared_raster_mime(mime: object) -> str | None:
    if not isinstance(mime, str):
        return None
    lowered = mime.split(";", 1)[0].strip().lower()
    if lowered == "image/jpg":
        return "image/jpeg"
    if lowered in _RASTER_MIMES:
        return lowered
    return None


def _normalize_mime(mime: object, path: Path | None, kind: object) -> str | None:
    declared = _declared_raster_mime(mime)
    if declared:
        return declared
    if path is not None:
        from_suffix = _SUFFIX_MIME.get(path.suffix.lower())
        if from_suffix:
            return from_suffix
    if isinstance(kind, str):
        return _KIND_MIME.get(kind)
    return None


def _to_vision_bytes(data: bytes, mime: str) -> tuple[bytes, str] | None:
    if mime in _VISION_MIMES:
        return data, mime
    if mime not in _CONVERT_MIMES:
        return None
    try:
        return _convert_to_jpeg(data)
    except Exception:
        logger.exception("Failed to convert image mime=%s", mime)
        return None


def _convert_to_jpeg(data: bytes) -> tuple[bytes, str]:
    _ensure_heif_support()
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        rgb = image.convert("RGB")
        out = BytesIO()
        rgb.save(out, format="JPEG", quality=90)
        return out.getvalue(), "image/jpeg"


def _ensure_heif_support() -> None:
    global _heif_registered
    if _heif_registered:
        return
    try:
        from pillow_heif import register_avif_opener, register_heif_opener

        register_heif_opener()
        register_avif_opener()
    except Exception:
        logger.warning("pillow-heif is unavailable; HEIC/AVIF conversion is disabled")
    _heif_registered = True


def _iso_brand(data: bytes) -> str | None:
    if len(data) < 12 or data[4:8] != b"ftyp":
        return None
    return data[8:12].decode("latin-1").lower()


def _relative_media_path(path: Path) -> str | None:
    confined = _confined_media_path(path)
    if confined is None:
        logger.warning("Refusing to persist path outside media dir path=%s", path)
        return None
    return confined.relative_to(_media_root()).as_posix()


def _absolute_media_path(rel_path: str) -> Path | None:
    candidate = Path(rel_path)
    if candidate.is_absolute():
        return _confined_media_path(candidate)
    return _confined_media_path(_media_root() / candidate)


def _confined_media_path(path: Path) -> Path | None:
    root = _media_root()
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _media_root() -> Path:
    return MEDIA_DIR.resolve()
