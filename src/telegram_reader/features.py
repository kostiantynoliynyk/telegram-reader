"""Registry of optional features that can be enabled in the signed config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    description: str
    risk: Literal["low", "high"]
    available: bool
    tools: tuple[str, ...] = ()
    requests: tuple[str, ...] = ()


FEATURES: dict[str, Feature] = {
    "write": Feature(
        key="write",
        title="Sending messages",
        description="Lets Claude send messages on your behalf.",
        risk="high",
        available=False,
    ),
}


def allowed_requests(enabled: frozenset[str]) -> frozenset[str]:
    """Union of Telegram request names allowed by enabled, available features."""
    out: set[str] = set()
    for key in enabled:
        feature = FEATURES.get(key)
        if feature is not None and feature.available:
            out.update(feature.requests)
    return frozenset(out)
