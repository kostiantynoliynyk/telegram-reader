"""Secrets (api_hash, Telethon StringSession, config signing key) in the OS keyring."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from functools import wraps
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "telegram-reader"
_API_HASH = "api_hash"
_SESSION = "session"
_CONFIG_KEY = "config_key"
_PROBE = "probe"


class SecretStoreUnavailable(Exception):
    pass


def _wrapped(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except KeyringError as e:  # includes NoKeyringError
            raise SecretStoreUnavailable(str(e)) from e

    return inner


def _delete(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass


@_wrapped
def check_backend() -> None:
    keyring.set_password(SERVICE, _PROBE, "1")
    value = keyring.get_password(SERVICE, _PROBE)
    _delete(_PROBE)
    if value != "1":
        raise SecretStoreUnavailable("keyring probe value did not read back")


@_wrapped
def get_api_hash() -> str | None:
    return keyring.get_password(SERVICE, _API_HASH)


@_wrapped
def set_api_hash(value: str) -> None:
    keyring.set_password(SERVICE, _API_HASH, value)


@_wrapped
def clear_api_hash() -> None:
    _delete(_API_HASH)


@_wrapped
def get_session() -> str | None:
    return keyring.get_password(SERVICE, _SESSION)


@_wrapped
def set_session(value: str) -> None:
    keyring.set_password(SERVICE, _SESSION, value)


@_wrapped
def get_config_key() -> bytes | None:
    value = keyring.get_password(SERVICE, _CONFIG_KEY)
    if not value:
        return None
    try:
        key = bytes.fromhex(value)
    except ValueError:
        return None
    return key if len(key) == 32 else None


@_wrapped
def get_or_create_config_key() -> bytes:
    existing = get_config_key()
    if existing is not None:
        return existing
    key = secrets.token_bytes(32)
    keyring.set_password(SERVICE, _CONFIG_KEY, key.hex())
    return key


@_wrapped
def clear() -> None:
    for name in (_API_HASH, _SESSION, _CONFIG_KEY):
        _delete(name)
