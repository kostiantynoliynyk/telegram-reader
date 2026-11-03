"""Folder picker: choose which Telegram folders Claude may read; migrates v1 configs."""

from __future__ import annotations

import dataclasses

from mcp.server.mcpserver.exceptions import ToolError

from .. import keychain, paths
from ..config import (
    Config,
    ConfigError,
    ConfigMissing,
    ConfigOutdated,
    ConfigTampered,
    FolderRef,
    parse_config,
    parse_legacy,
    read_api_id,
    write_config,
)
from ..errors import LoginRequired, SessionRevoked
from ..keychain import SecretStoreUnavailable
from ..models import FolderInfo
from ..tg import TgClient
from .messages import CONFIG_BROKEN, CONFIG_TAMPERED, NO_SECRET_STORE, format_problem, login_problem
from .ui import UI, Cancelled, Choice

AUTO_RULES_NOTE = " ⚠ auto rules are ignored"
NO_FOLDERS_HELP = (
    "This account has no folders. Create them in Telegram: Settings → Folders → Create a folder, "
    "add the chats you want, then choose «Refresh list»."
)
REFRESH, QUIT = "refresh", "quit"
LEGACY_CHATS_WARNING = "Chats outside folders are no longer supported — add them to a folder in Telegram"


def _chat_ids(folders: list[FolderInfo], selected: set[int]) -> set[int]:
    return {pid for f in folders if f.id in selected for pid in f.peer_ids}


async def choose_folders(ui: UI, tg, cfg: Config) -> Config:
    selected = {f.id for f in cfg.folders}
    while True:
        folders = await tg.list_folders()
        if not folders:
            ui.say(NO_FOLDERS_HELP)
            action = await ui.select(
                "What next?", [Choice("Refresh list", REFRESH), Choice("Quit", QUIT)]
            )
            if action == QUIT:
                raise Cancelled
            continue
        live = {f.id for f in folders}
        choices = [
            Choice(
                f"{f.title} — {len(f.peer_ids)} chats" + (AUTO_RULES_NOTE if f.has_auto_rules else ""),
                f.id,
                checked=f.id in selected,
            )
            for f in folders
        ]
        choices += [
            Choice(f.title, f.id, disabled="gone")
            for f in cfg.folders
            if f.id not in live
        ]
        picked = await ui.checkbox("Select the folders Claude will see", choices)
        if not picked:
            ui.warn("Select at least one folder")
            continue
        titles = {f.id: f.title for f in folders}
        return dataclasses.replace(cfg, folders=tuple(FolderRef(i, titles[i]) for i in picked if i in titles))


def _migrate(ui: UI, text: str, folders: list[FolderInfo]) -> Config:
    legacy = parse_legacy(text)
    by_title = {f.title: f for f in folders}
    resolved, missing = [], []
    for name in legacy.folder_names:
        f = by_title.get(name)
        if f is None:
            missing.append(name)
        else:
            resolved.append(FolderRef(f.id, f.title))
    if missing:
        ui.warn("Folders not found: " + ", ".join(f"«{n}»" for n in missing))
    if legacy.had_chats:
        ui.warn(LEGACY_CHATS_WARNING)
    return Config(api_id=legacy.api_id, folders=tuple(resolved))


async def run_folders(ui: UI) -> int:
    paths.migrate_location()
    path = paths.config_path()
    try:
        key = keychain.get_or_create_config_key()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigMissing(str(path)) from None
        except (OSError, UnicodeDecodeError) as e:
            raise ConfigError(str(e)) from e
        legacy_text: str | None = None
        try:
            cfg = parse_config(text, key)
        except ConfigOutdated:
            legacy_text, cfg = text, None
        except ConfigTampered:
            ui.fail(format_problem(CONFIG_TAMPERED))
            cfg = Config(api_id=read_api_id(text))
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    except ConfigMissing:
        ui.fail("Config not found — run telegram-reader setup")
        return 1
    except ConfigError:
        ui.fail(format_problem(CONFIG_BROKEN))
        return 1

    api_id = cfg.api_id if cfg else parse_legacy(legacy_text).api_id
    tg = TgClient(api_id)
    try:
        await tg.connect()
        if legacy_text is not None:
            cfg = _migrate(ui, legacy_text, await tg.list_folders())
        before = await tg.list_folders()
        if cfg.account_id is not None and cfg.account_id != tg.account_id:
            cfg = dataclasses.replace(cfg, folders=())  # folder ids belong to another account
        old_chats = _chat_ids(before, {f.id for f in cfg.folders})
        cfg = await choose_folders(ui, tg, cfg)
        after = await tg.list_folders()
    except ToolError as e:
        ui.fail(login_problem(isinstance(e, SessionRevoked)) if isinstance(e, LoginRequired) else str(e))
        return 1
    finally:
        await tg.disconnect()

    cfg = dataclasses.replace(cfg, account_id=tg.account_id)
    write_config(path, cfg, key)
    new_chats = _chat_ids(after, {f.id for f in cfg.folders})
    summary = f"Done: Claude will see {len(new_chats)} chats from {len(cfg.folders)} folders"
    if old_chats:
        added, removed = len(new_chats - old_chats), len(old_chats - new_chats)
        if added or removed:
            summary += f" (+{added} / −{removed})"
    ui.ok(summary)
    return 0
