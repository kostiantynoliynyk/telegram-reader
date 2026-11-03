"""Plain data passed between the Telegram wrapper, access checks and formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ChatKind = Literal["private", "group", "channel", "forum"]
MediaKind = Literal["document", "photo", "voice", "video", "audio", "sticker", "other"]


@dataclass(frozen=True)
class TopicInfo:
    id: int
    title: str


@dataclass(frozen=True)
class ChatInfo:
    id: int  # Telethon "marked" id: -100… for channels and supergroups
    title: str
    kind: ChatKind
    link_base: str | None  # https://t.me/<username> or https://t.me/c/<internal_id>
    unread: int = 0
    last_date: datetime | None = None
    topics: tuple[TopicInfo, ...] = ()


@dataclass(frozen=True)
class MediaInfo:
    kind: MediaKind
    name: str | None = None
    mime: str | None = None
    size: int | None = None  # bytes
    width: int | None = None
    height: int | None = None
    duration: int | None = None  # seconds
    other: str | None = None  # media type name when kind == "other", e.g. "poll"


@dataclass(frozen=True)
class LinkInfo:
    url: str
    anchor: str | None = None  # visible text when the target is hidden behind it


@dataclass(frozen=True)
class MessageData:
    id: int
    chat_id: int
    date: datetime  # aware, UTC
    sender: str
    text: str
    reply_to_id: int | None = None
    reply_snippet: str | None = None
    media: MediaInfo | None = None
    forwarded_from: str | None = None
    links: tuple[LinkInfo, ...] = ()


@dataclass(frozen=True)
class FolderInfo:
    id: int
    title: str
    peer_ids: tuple[int, ...]
    has_auto_rules: bool
