"""`status`: read-only report on the setup. Needs no terminal and writes nothing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from ..access import Access
from ..errors import LoginRequired, SessionRevoked
from .. import paths
from ..features import FEATURES
from ..format import format_chat, local_tz
from ..store import ConfigStore
from ..tg import TgClient
from .messages import login_problem
from .ui import UI


def _feature_line(enabled: frozenset[str]) -> str:
    parts = []
    for key, feature in FEATURES.items():
        if not feature.available:
            state = "disabled (unavailable)"
        else:
            state = "enabled" if key in enabled else "disabled"
        parts.append(f"{feature.title} — {state}")
    return "Features: " + "; ".join(parts)


async def run_status(
    ui: UI,
    *,
    store: ConfigStore | None = None,
    tg: Any = None,
    registered: Callable[[], bool | None] | None = None,
) -> int:
    # No migrate_location(): status must not move or write anything.
    store = store or ConfigStore(paths.config_path())
    try:
        cfg = store.current()
    except ToolError as e:
        ui.fail(str(e))
        return 1
    tg = tg or TgClient(cfg.api_id)
    try:
        # tg maps network failures to NetworkError; other errors reach run()'s logged path.
        await tg.connect()
        access = Access(tg, store)
        chats = await access.allowed_chats(fresh_metadata=True)
    except LoginRequired as e:
        ui.fail(login_problem(isinstance(e, SessionRevoked)))
        return 1
    except ToolError as e:
        ui.fail(str(e))
        return 1
    finally:
        await tg.disconnect()

    name = getattr(tg, "account_name", None) or "—"
    ui.say(f"Account: {name} ({tg.account_id})")
    ui.say("Folders: " + (", ".join(f.title for f in cfg.folders) or "none selected"))
    ui.say(_feature_line(cfg.features))
    ui.say(f"Claude sees {len(chats)} chats")
    tz = local_tz()
    for chat in chats:
        ui.say(format_chat(chat, tz))
    for warning in access.warnings:
        ui.warn(warning)
    if registered is not None:
        state = registered()
        ui.say("Claude Code: " + {True: "connected", False: "not connected", None: "claude not found"}[state])
    if not chats:
        ui.say("Select folders: telegram-reader folders")
        return 1
    return 0
