"""Safe on-disk names for downloaded files and the rule for what is inlined to the agent."""

from __future__ import annotations

import mimetypes
import unicodedata
from pathlib import Path
from typing import Literal

from telegram_reader.models import MediaInfo
from telegram_reader.sanitize import _strip

IMAGE_INLINE_MAX = 5 * 1024 * 1024
TEXT_INLINE_MAX = 200 * 1024

_NAME_MAX = 128
_NAME_MAX_BYTES = 200  # ext4 allows 255 bytes; leave room for the "<message_id>-" prefix
_EXT_MAX = 16
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log"}


def _split_ext(name: str) -> tuple[str, str]:
    dot = name.rfind(".")
    if dot <= 0 or len(name) - dot > _EXT_MAX:  # a very long "extension" is just part of the name
        return name, ""
    return name[:dot], name[dot:]


def _fallback(media: MediaInfo) -> str:
    if media.kind == "photo":
        return "photo.jpg"
    ext = mimetypes.guess_extension(media.mime) if media.mime else None
    return media.kind + (ext or "")


def safe_name(media: MediaInfo) -> str:
    if media.name is None:
        return _fallback(media)
    name = _strip(media.name)
    name = name.split("/")[-1]
    name = "".join(c for c in name if unicodedata.category(c) != "Cc")
    if name.startswith(".") and name.count(".") == 1 and mimetypes.guess_type("x" + name)[0]:
        name = "file" + name  # ".pdf" is an extension without a name, not a hidden file
    else:
        name = name.lstrip(". ")
    base, ext = _split_ext(name)
    if not base.strip():
        base = "file"
    base = base[: _NAME_MAX - len(ext)]
    while len((base + ext).encode("utf-8")) > _NAME_MAX_BYTES:
        base = base[:-1]
    return base + ext


def target_path(root: Path, chat_id: int, message_id: int, media: MediaInfo) -> Path:
    return root / str(chat_id) / f"{message_id}-{safe_name(media)}"


def sniff_image(head: bytes) -> str | None:
    """The image type the bytes really are (by magic number), or None if not one we inline."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def inline_kind(media: MediaInfo, size: int) -> Literal["image", "text"] | None:
    if media.mime in _IMAGE_MIMES:
        return "image" if size <= IMAGE_INLINE_MAX else None
    ext = Path(media.name).suffix.lower() if media.name else ""
    is_text = (
        (media.mime or "").startswith("text/")
        or media.mime == "application/json"
        or ext in _TEXT_EXTS
    )
    return "text" if is_text and size <= TEXT_INLINE_MAX else None
