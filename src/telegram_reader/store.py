"""Hot-reloading, signature-verifying access to the config file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from . import keychain
from .config import (
    Config,
    ConfigError,
    ConfigMissing,
    ConfigOutdated,
    ConfigTampered,
    parse_config,
)
from .errors import SecretStoreError
from .keychain import SecretStoreUnavailable

_MISSING = "Config not found — run telegram-reader setup"
_OUTDATED = "Config needs an update — run telegram-reader folders"
_TAMPERED = "Config was changed outside telegram-reader — run telegram-reader folders"


class ConfigStore:
    def __init__(
        self,
        path: Path,
        key_loader: Callable[[], bytes | None] = keychain.get_config_key,
    ):
        self._path = path
        self._key_loader = key_loader
        self._mtime_ns: int | None = None
        self._cached: Config | None = None

    def current(self) -> Config:
        try:
            return self._load()
        except ConfigError as e:
            self._cached = None
            self._mtime_ns = None
            raise ToolError(_message(e)) from e
        except SecretStoreUnavailable as e:
            self._cached = None
            self._mtime_ns = None
            raise SecretStoreError() from e

    def _load(self) -> Config:
        try:
            mtime = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            raise ConfigMissing(str(self._path)) from None
        except OSError as e:
            raise ConfigError(f"could not read {self._path}: {e}") from e
        if self._cached is not None and mtime == self._mtime_ns:
            return self._cached
        key = self._key_loader()
        if key is None:
            raise ConfigTampered("signing key not found")
        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ConfigError(f"could not read {self._path}: {e}") from e
        cfg = parse_config(text, key)
        self._cached, self._mtime_ns = cfg, mtime
        return cfg


def _message(e: ConfigError) -> str:
    if isinstance(e, ConfigMissing):
        return _MISSING
    if isinstance(e, ConfigOutdated):
        return _OUTDATED
    if isinstance(e, ConfigTampered):
        return _TAMPERED
    return f"Config error: {e}"
