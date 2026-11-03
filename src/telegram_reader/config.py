"""Signed config v2 for ~/.config/telegram-reader/config.toml."""

from __future__ import annotations

import hmac
import json
import os
import tempfile
import tomllib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import tomli_w

from telegram_reader.features import FEATURES


class ConfigError(Exception):
    pass


class ConfigMissing(ConfigError):
    pass


class ConfigOutdated(ConfigError):
    pass


class ConfigTampered(ConfigError):
    pass


@dataclass(frozen=True)
class FolderRef:
    id: int
    title: str


@dataclass(frozen=True)
class Config:
    api_id: int
    account_id: int | None = None
    folders: tuple[FolderRef, ...] = ()
    features: frozenset[str] = frozenset()
    max_messages: int = 200
    search_per_chat: int = 20
    download_max_mb: int = 50


@dataclass(frozen=True)
class LegacyConfig:
    api_id: int
    folder_names: tuple[str, ...]
    had_chats: bool


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int_in_range(section: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = section.get(key, default)
    if not _is_int(value) or not lo <= value <= hi:
        raise ConfigError(f"limits.{key}: expected an integer from {lo} to {hi}")
    return value


def _table(raw: dict, key: str) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}]: expected a table")
    return value


def _loads(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Config syntax error: {e}") from None


def _api_id(raw: dict) -> int:
    api_id = _table(raw, "telegram").get("api_id")
    if not _is_int(api_id) or api_id <= 0:
        raise ConfigError("telegram.api_id: expected a positive integer from my.telegram.org")
    return api_id


def _check_features(known: frozenset[str], enabled: frozenset[str]) -> None:
    for key in sorted(known):
        if key not in FEATURES:
            raise ConfigError(f"features.{key}: unknown feature")
    for key in sorted(enabled):
        if not FEATURES[key].available:
            raise ConfigError(f"features.{key}: feature not available yet")


def signature(cfg: Config, key: bytes) -> str:
    canonical = json.dumps(
        {
            "account_id": cfg.account_id,
            "folders": [[f.id, f.title] for f in cfg.folders],
            "features": sorted(cfg.features),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(key, canonical.encode("utf-8"), sha256).hexdigest()


def parse_config(text: str, key: bytes) -> Config:
    raw = _loads(text)
    if raw.get("version") != 2:
        raise ConfigOutdated("Config is outdated: expected version = 2")

    api_id = _api_id(raw)
    telegram = _table(raw, "telegram")
    account_id = telegram.get("account_id")
    if account_id is not None and not _is_int(account_id):
        raise ConfigError("telegram.account_id: expected an integer")

    folders_raw = _table(raw, "access").get("folders", [])
    if not isinstance(folders_raw, list):
        raise ConfigError("access.folders: expected a list")
    folders: list[FolderRef] = []
    for item in folders_raw:
        if (
            not isinstance(item, dict)
            or not _is_int(item.get("id"))
            or not isinstance(item.get("title"), str)
        ):
            raise ConfigError("access.folders: expected a list of {id, title}")
        folders.append(FolderRef(item["id"], item["title"]))

    features_raw = _table(raw, "features")
    if not all(isinstance(v, bool) for v in features_raw.values()):
        raise ConfigError("features: expected true/false values")
    enabled = frozenset(k for k, v in features_raw.items() if v)
    _check_features(frozenset(features_raw), enabled)

    limits = _table(raw, "limits")
    cfg = Config(
        api_id=api_id,
        account_id=account_id,
        folders=tuple(folders),
        features=enabled,
        max_messages=_int_in_range(limits, "max_messages", 200, 1, 1000),
        search_per_chat=_int_in_range(limits, "search_per_chat", 20, 1, 100),
        download_max_mb=_int_in_range(limits, "download_max_mb", 50, 1, 2000),
    )

    sig = _table(raw, "signature").get("hmac")
    if not isinstance(sig, str) or not hmac.compare_digest(
        sig.encode("utf-8"), signature(cfg, key).encode("utf-8")
    ):
        raise ConfigTampered("Config signature is invalid or missing")
    return cfg


def parse_legacy(text: str) -> LegacyConfig:
    raw = _loads(text)
    access = _table(raw, "access")
    folders = access.get("folders", [])
    if not isinstance(folders, list) or not all(isinstance(v, str) for v in folders):
        raise ConfigError("access.folders: expected a list of strings")
    return LegacyConfig(
        api_id=_api_id(raw),
        folder_names=tuple(folders),
        had_chats=bool(access.get("chats") or access.get("exclude")),
    )


def read_api_id(text: str) -> int:
    """api_id from a config whose signature cannot be trusted (e.g. tampered), to let the user re-pick folders."""
    return _api_id(_loads(text))


def dump_config(cfg: Config, key: bytes) -> str:
    _check_features(cfg.features, cfg.features)
    telegram: dict[str, Any] = {"api_id": cfg.api_id}
    if cfg.account_id is not None:
        telegram["account_id"] = cfg.account_id
    doc = {
        "version": 2,
        "telegram": telegram,
        "access": {"folders": [{"id": f.id, "title": f.title} for f in cfg.folders]},
        "features": {k: k in cfg.features for k in FEATURES},
        "limits": {
            "max_messages": cfg.max_messages,
            "search_per_chat": cfg.search_per_chat,
            "download_max_mb": cfg.download_max_mb,
        },
        "signature": {"hmac": signature(cfg, key)},
    }
    return tomli_w.dumps(doc)


def write_config(path: Path, cfg: Config, key: bytes) -> None:
    text = dump_config(cfg, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
