"""Cleaning untrusted Telegram text: hidden characters, nonce, injection detector."""
from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Iterable

from .injection_patterns import PATTERNS

HIDDEN_MARK = "[hidden characters removed]"

# tag characters, bidi controls, zero-width; U+200D is handled separately
_HIDDEN = re.compile(
    "[\U000e0000-\U000e007f‪-‮⁦-⁩​‌⁠﻿]"
)
_ZWJ = "‍"


def _strip_zwj(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch == _ZWJ:
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            left_ok = prev and (
                unicodedata.category(prev) in ("So", "Sk") or prev == "\ufe0f"
            )
            if not (left_ok and nxt and unicodedata.category(nxt) == "So"):
                continue
        out.append(ch)
    return "".join(out)


def _strip(text: str) -> str:
    return _strip_zwj(_HIDDEN.sub("", text))


def clean(text: str) -> str:
    """Strips hidden characters; appends a marker if anything was removed."""
    result = _strip(text)
    if result != text:
        return f"{result} {HIDDEN_MARK}"
    return result


def clip(text: str, limit: int) -> str:
    """clean + whitespace collapsing + clipping to `limit` characters with «…».

    The hidden-characters marker is appended after clipping so it cannot be pushed out.
    """
    stripped = _strip(text)
    flat = " ".join(stripped.split())
    if len(flat) > limit:
        flat = flat[: limit - 1] + "…"
    return f"{flat} {HIDDEN_MARK}" if stripped != text else flat


def new_nonce(texts: Iterable[str]) -> str:
    """8 hex characters that appear in none of `texts`."""
    texts = list(texts)
    while True:
        nonce = secrets.token_hex(4)
        if not any(nonce in t for t in texts):
            return nonce


def looks_like_injection(text: str) -> bool:
    normalized = _strip(unicodedata.normalize("NFKC", _strip(text)))
    return any(p.search(normalized) for p in PATTERNS)
