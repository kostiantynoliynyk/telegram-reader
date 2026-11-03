"""Feature toggles: enable or disable optional capabilities in the signed config."""

from __future__ import annotations

import dataclasses

from mcp.server.mcpserver.exceptions import ToolError

from .. import keychain, paths
from ..config import Config, write_config
from ..features import FEATURES
from ..keychain import SecretStoreUnavailable
from .common import load_store
from .messages import NO_SECRET_STORE, format_problem
from .ui import UI, Choice

CONFIRM_WORD = "yes"
RESTART_NOTE = "Enabled features appear after restarting the Claude Code session or /mcp"


async def choose_features(ui: UI, cfg: Config) -> Config:
    choices = [
        Choice(
            f"{f.title} — {f.description}",
            f.key,
            checked=f.key in cfg.features,
            disabled=None if f.available else "soon",
        )
        for f in FEATURES.values()
    ]
    picked = set(await ui.checkbox("Choose features", choices))
    enabled = set()
    for key in picked:
        feature = FEATURES.get(key)
        if feature is None or not feature.available:
            continue
        if feature.risk == "high" and key not in cfg.features:
            ui.warn(f"{feature.title}: {feature.description} This is a high risk.")
            if (await ui.ask(f"To enable, type «{CONFIRM_WORD}»")).strip().lower() != CONFIRM_WORD:
                ui.say(f"Not enabled: {feature.title}")
                continue
        enabled.add(key)
    return dataclasses.replace(cfg, features=frozenset(enabled))


async def run_features(ui: UI) -> int:
    store = load_store()
    try:
        cfg = store.current()
        key = keychain.get_or_create_config_key()
    except ToolError as e:
        ui.fail(str(e))
        return 1
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    updated = await choose_features(ui, cfg)
    if updated == cfg:
        ui.say("No changes")
        return 0
    write_config(paths.config_path(), updated, key)
    ui.ok("Saved")
    ui.say(RESTART_NOTE)
    return 0
