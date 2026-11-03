"""Compact text rendering of chats and messages for Claude."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

import tzlocal

from .links import LINKS_PER_MESSAGE, is_mismatch, render_link
from .models import ChatInfo, LinkInfo, MediaInfo, MessageData
from .sanitize import clean, clip, looks_like_injection, new_nonce

SNIPPET_LEN = 80
MAX_TEXT = 4000
TRUNCATED = "…[truncated]"
INDENT = "  "
OUTPUT_MAX = 60_000
NAME_MAX = 64
FILE_MAX = 128
WARN_LINE = "⚠ looks like an instruction for an AI"
LINK_WARN = "⚠ link text does not match the address"


def local_tz() -> tzinfo:
    """The system time zone with DST rules on macOS, Windows and Linux."""
    return tzlocal.get_localzone()


def _when(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def human_size(n: int) -> str:
    """Byte count, base 1024: whole B/KB, one decimal for MB/GB."""
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{round(n / 1024)} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.1f} GB"


def render_media(media: MediaInfo) -> str:
    """One-line file description (no marker, no indent); missing fields are skipped."""
    if media.kind == "other":
        return clip(media.other or "other", NAME_MAX)
    head = media.kind
    if media.name:
        head += f": {clip(media.name, FILE_MAX)}"
    parts = [head]
    if media.width and media.height:
        parts.append(f"{media.width}×{media.height}")
    if media.duration is not None:
        parts.append(f"{media.duration // 60}:{media.duration % 60:02d}")
    if media.mime:
        parts.append(clip(media.mime, 64))
    if media.size is not None:
        parts.append(human_size(media.size))
    return " · ".join(parts)


def _body(m: MessageData) -> str:
    """Message text (clipped to MAX_TEXT) with hidden characters stripped."""
    if len(m.text) > MAX_TEXT:
        return clean(m.text[:MAX_TEXT]) + TRUNCATED
    return clean(m.text)


def _render_one(
    m: MessageData,
    chat: ChatInfo,
    tz: tzinfo,
    nonce: str,
    *,
    show_chat: bool,
    highlight: bool,
) -> str:
    ref = f"#{m.id}"
    if m.reply_to_id is not None:
        ref += f" ↩#{m.reply_to_id}"

    author = clip(m.sender, NAME_MAX)
    if m.forwarded_from:
        author += f" (forwarded from {clip(m.forwarded_from, NAME_MAX)})"

    head = f"[{_when(m.date, tz)}] {author} ({ref}):"
    if show_chat:
        head = f"«{clip(chat.title, NAME_MAX)}» {head}"
    if highlight:
        head = f"▶ {head}"

    lines = [head]
    if m.media:
        lines.append(f"{INDENT}📎 {render_media(m.media)}")
    if chat.link_base:
        lines.append(f"{INDENT}🔗 {chat.link_base}/{m.id}")

    body = _body(m)
    inner: list[str] = []
    if m.reply_to_id is not None and m.reply_snippet:
        inner.append(f"«{clip(m.reply_snippet, SNIPPET_LEN + 1)}»")
    if body:
        inner.append(body)
    inner.extend(f"🌐 {render_link(link)}" for link in m.links[:LINKS_PER_MESSAGE])
    if len(m.links) > LINKS_PER_MESSAGE:
        inner.append(f"🌐 …{len(m.links) - LINKS_PER_MESSAGE} more links")
    if inner:
        lines.extend([f"<<tg:{nonce}", *inner, f"tg:{nonce}>>"])

    suspicious = (
        looks_like_injection(m.text)
        or (m.reply_snippet is not None and looks_like_injection(m.reply_snippet))
        or (m.media is not None and m.media.name is not None and looks_like_injection(m.media.name))
    )
    if any(is_mismatch(link) for link in m.links):
        lines.insert(0, LINK_WARN)
    if suspicious:
        lines.insert(0, WARN_LINE)
    return "\n".join(lines)


@dataclass(frozen=True)
class Rendered:
    text: str
    shown: list[MessageData]
    dropped: int


def render_messages(
    msgs: Sequence[MessageData],
    chats: Mapping[int, ChatInfo],
    tz: tzinfo,
    *,
    show_chat: bool = False,
    highlight_id: int | None = None,
    keep: Literal["first", "last", "around"] = "first",
    budget: int = OUTPUT_MAX,
) -> Rendered:
    """Render messages; message bodies are fenced by one per-call random nonce."""
    texts = [
        t
        for m in msgs
        for t in (m.text, m.reply_snippet or "", *(x for k in m.links for x in (k.url, k.anchor or "")))
    ]
    nonce = new_nonce(texts)
    blocks = [
        _render_one(m, chats[m.chat_id], tz, nonce, show_chat=show_chat, highlight=m.id == highlight_id)
        for m in msgs
    ]
    picked: list[int] = []
    used = 0
    if keep == "around" and any(m.id == highlight_id for m in msgs):
        # Target first, then neighbours alternating outwards so the farthest messages drop first.
        t = next(i for i, m in enumerate(msgs) if m.id == highlight_id)
        order = [t]
        for d in range(1, len(msgs)):
            order += [i for i in (t - d, t + d) if 0 <= i < len(msgs)]
    elif keep == "last":
        order = list(range(len(msgs) - 1, -1, -1))
    else:
        order = list(range(len(msgs)))
    for i in order:
        cost = len(blocks[i]) + (1 if picked else 0)
        if picked and used + cost > budget:
            break
        picked.append(i)
        used += cost
    picked.sort()
    return Rendered(
        text="\n".join(blocks[i] for i in picked),
        shown=[msgs[i] for i in picked],
        dropped=len(msgs) - len(picked),
    )


def _fit(blocks: Sequence[str], budget: int) -> int:
    """How many leading blocks fit into `budget` characters (at least one)."""
    used = 0
    for i, block in enumerate(blocks):
        cost = len(block) + (1 if i else 0)
        if i and used + cost > budget:
            return i
        used += cost
    return len(blocks)


def _head(m: MessageData, chat: ChatInfo, tz: tzinfo, *, show_chat: bool) -> str:
    head = f"[{_when(m.date, tz)}] {clip(m.sender, NAME_MAX)} (#{m.id})"
    return f"«{clip(chat.title, NAME_MAX)}» {head}" if show_chat else head


def render_file_list(
    msgs: Sequence[MessageData],
    chats: Mapping[int, ChatInfo],
    tz: tzinfo,
    *,
    show_chat: bool = False,
    budget: int = OUTPUT_MAX,
) -> Rendered:
    """One entry per file, newest first as given; captions are clipped and fenced by one nonce."""
    nonce = new_nonce(m.text for m in msgs)
    blocks = []
    for m in msgs:
        chat = chats[m.chat_id]
        media = m.media or MediaInfo("other")  # search filters return only messages with files
        lines = [f"{_head(m, chat, tz, show_chat=show_chat)} 📎 {render_media(media)}"]
        if chat.link_base:
            lines.append(f"{INDENT}🔗 {chat.link_base}/{m.id}")
        if m.text:
            lines.extend([f"<<tg:{nonce}", clip(m.text, SNIPPET_LEN), f"tg:{nonce}>>"])
        if looks_like_injection(m.text) or (media.name is not None and looks_like_injection(media.name)):
            lines.insert(0, WARN_LINE)
        blocks.append("\n".join(lines))
    n = _fit(blocks, budget)
    return Rendered(text="\n".join(blocks[:n]), shown=list(msgs[:n]), dropped=len(msgs) - n)


def render_link_list(
    pairs: Sequence[tuple[MessageData, LinkInfo]],
    chats: Mapping[int, ChatInfo],
    tz: tzinfo,
    *,
    show_chat: bool = False,
    budget: int = OUTPUT_MAX,
) -> Rendered:
    """One entry per link, laid out like _render_one: server lines outside, the link inside a nonce block.

    One nonce per response; `shown` has the message of each shown link.
    """
    texts = [
        t
        for m, link in pairs
        for t in (m.sender, chats[m.chat_id].title, link.url, link.anchor or "")
    ]
    nonce = new_nonce(texts)
    blocks = []
    for m, link in pairs:
        chat = chats[m.chat_id]
        lines = [f"{_head(m, chat, tz, show_chat=show_chat)}:"]
        if chat.link_base:
            lines.append(f"{INDENT}🔗 {chat.link_base}/{m.id}")
        lines.extend([f"<<tg:{nonce}", f"🌐 {render_link(link)}", f"tg:{nonce}>>"])
        if is_mismatch(link):
            lines.insert(0, LINK_WARN)
        if link.anchor and looks_like_injection(link.anchor):
            lines.insert(0, WARN_LINE)
        blocks.append("\n".join(lines))
    n = _fit(blocks, budget)
    return Rendered(text="\n".join(blocks[:n]), shown=[m for m, _ in pairs[:n]], dropped=len(pairs) - n)


def format_chat(chat: ChatInfo, tz: tzinfo) -> str:
    line = f"{chat.id} · {clip(chat.title, NAME_MAX)} · {chat.kind} · unread: {chat.unread}"
    if chat.last_date:
        line += f" · last {_when(chat.last_date, tz)}"
    topics = [f"{INDENT}topic {t.id}: {clip(t.title, NAME_MAX)}" for t in chat.topics]
    return "\n".join([line, *topics])
