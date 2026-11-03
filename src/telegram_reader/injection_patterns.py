"""Patterns of typical prompt-injection phrases in untrusted text (case-insensitive)."""
from __future__ import annotations

import re

_VERB = r"(?:call|run|use|execute|виклич|запусти|выполни)"
# exact tool name only (case-sensitive); Bash is excluded: too common in ordinary chats
_TOOL = r"(?-i:\bWebFetch\b)"

PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"\b(?:ignore|disregard|ігноруй(?:те)?|игнорируй(?:те)?)\s+"
        r"(?:(?:all|the|your|previous|prior|всі|все|попередні|предыдущие)\s+)*"
        r"(?:instructions|інструкції|инструкции)",
        r"\byou are now\b",
        r"\bsystem prompt\b",
        r"<\|im_(?:start|end)\|>",
        r"</?tool_(?:result|use|call)>",
        r"^(?:Human|Assistant|System):",
        r"\bmcp__\w+",
        rf"\b{_VERB}\b.{{0,20}}{_TOOL}",
        r"[A-Za-z0-9+/]{200,}={0,2}",
    )
)
