"""OS-specific locations for the config and log files."""

from __future__ import annotations

import shutil
from pathlib import Path

import platformdirs

_APP = "telegram-reader"

LEGACY_CONFIG = Path.home() / ".config" / "telegram-reader" / "config.toml"


def config_path() -> Path:
    return Path(platformdirs.user_config_dir(_APP, appauthor=False)) / "config.toml"


def log_path() -> Path:
    return Path(platformdirs.user_log_dir(_APP, appauthor=False)) / "telegram-reader.log"


def downloads_dir() -> Path:
    return Path(platformdirs.user_downloads_dir()) / _APP


def migrate_location() -> bool:
    """Move the legacy config to the OS-specific path if the new one is absent."""
    new = config_path()
    if new.exists() or not LEGACY_CONFIG.exists() or new == LEGACY_CONFIG:
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(LEGACY_CONFIG), str(new))
    return True
