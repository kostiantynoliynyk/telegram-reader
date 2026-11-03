"""`setup`: the eight-step first-run wizard. Writes the config once, after folders and features."""

from __future__ import annotations

import dataclasses

from mcp.server.mcpserver.exceptions import ToolError

from .. import keychain, paths
from ..config import Config, ConfigError, read_api_id, write_config
from ..errors import LoginRequired
from ..features import FEATURES
from ..keychain import SecretStoreUnavailable
from ..tg import TgClient
from .claude_code import find_claude, is_registered, manual_command, register
from .features_cmd import choose_features
from .folders import choose_folders
from .login import LoginFailed, ask_api_credentials, login
from .messages import CLAUDE_NOT_FOUND, INTRO, NO_SECRET_STORE, WHY_FOLDERS, format_problem
from .ui import UI, Choice

TOTAL = 8
RESTART = "Restart the Claude Code session or run /mcp"
EXISTING_HINT = (
    "Nothing changed. Individual steps: telegram-reader folders (folders), "
    "telegram-reader login (account), telegram-reader features (features)."
)


def _existing_api_id() -> int | None:
    try:
        return read_api_id(paths.config_path().read_text(encoding="utf-8"))
    except (OSError, ConfigError):
        return None


async def _working_session(api_id: int) -> tuple[int, str] | None:
    """(account id, name) when a saved session still works, else None."""
    tg = TgClient(api_id)
    try:
        await tg.connect()
        return tg.account_id, tg.account_name or "—"  # type: ignore[return-value]
    except (LoginRequired, ToolError):
        return None
    finally:
        await tg.disconnect()


async def run_setup(ui: UI) -> int:
    paths.migrate_location()
    if paths.config_path().exists():
        if not await ui.confirm("Settings already exist. Start over?", default=False):
            ui.say(EXISTING_HINT)
            return 0

    ui.step(1, TOTAL, "Introduction")
    ui.say(INTRO)
    ui.say(WHY_FOLDERS)

    ui.step(2, TOTAL, "Secret store")
    try:
        keychain.check_backend()
        key = keychain.get_or_create_config_key()
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    ui.ok("Secret store is available")

    ui.step(3, TOTAL, "Telegram app credentials")
    api_id, typed_hash = _existing_api_id(), None
    if api_id is not None and keychain.get_api_hash():
        ui.ok("api_id and api_hash are already saved")
    else:
        api_id, typed_hash = await ask_api_credentials(ui)

    ui.step(4, TOTAL, "Login")
    session = await _working_session(api_id) if keychain.get_session() and (typed_hash or keychain.get_api_hash()) else None
    account_id, name = session if session else (None, "")
    if session:
        choice = await ui.select(
            f"You are logged in as {name}", [Choice("Keep", "keep"), Choice("Change account", "change")]
        )
        if choice == "keep":
            ui.ok(f"Keeping account {name}")
    if not session or choice != "keep":
        try:
            result = await login(ui, api_id, previous_account=account_id, api_hash=typed_hash)
        except LoginFailed:
            return 1
        api_id = result.api_id or api_id
        account_id, name = result.account_id, result.name

    ui.step(5, TOTAL, "Folders")
    cfg = Config(api_id=api_id, account_id=account_id)
    tg = TgClient(api_id)
    try:
        await tg.connect()
        cfg = await choose_folders(ui, tg, cfg)
        selected = {f.id for f in cfg.folders}
        chat_count = len({p for f in await tg.list_folders() if f.id in selected for p in f.peer_ids})
    except (LoginRequired, ToolError) as e:
        ui.fail(str(e))
        return 1
    finally:
        await tg.disconnect()

    ui.step(6, TOTAL, "Features")
    cfg = await choose_features(ui, cfg)
    write_config(paths.config_path(), cfg, key)
    ui.ok("Settings saved")

    ui.step(7, TOTAL, "Claude Code")
    rc = 0
    claude = find_claude()
    if claude is None:
        ui.warn(format_problem(CLAUDE_NOT_FOUND))
        ui.say(manual_command())
    elif is_registered(claude):
        ui.ok("Already connected to Claude Code")
    elif await ui.confirm("Connect to Claude Code?"):
        try:
            register(claude)
            ui.ok("Connected to Claude Code")
        except RuntimeError as e:
            ui.fail(f"Could not connect: {e}")
            ui.say(f"Run it manually: {manual_command()}")
            rc = 1
    else:
        ui.say(f"Connect later: {manual_command()}")

    ui.step(8, TOTAL, "Summary")
    ui.say(f"Account: {name}")
    ui.say("Folders: " + ", ".join(f.title for f in cfg.folders))
    ui.say(f"Claude will see {chat_count} chats")
    on = [FEATURES[k].title for k in sorted(cfg.features) if k in FEATURES]
    ui.say("Features: " + (", ".join(on) if on else "read-only"))
    ui.say(RESTART)
    return rc
