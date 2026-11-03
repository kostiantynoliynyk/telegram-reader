"""Shared CLI plumbing: TTY guard, error-to-exit-code runner, config store loader."""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable

import asyncio

from .. import paths
from ..store import ConfigStore
from .messages import NOT_INTERACTIVE, format_problem
from .ui import UI, Cancelled, RichUI

log = logging.getLogger("telegram_reader")


class NotInteractive(Exception):
    """An interactive command was started without a terminal."""


def require_tty() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise NotInteractive


def run(command: Callable[[UI], Awaitable[int]], *, interactive: bool, ui: UI | None = None) -> int:
    async def main() -> int:
        if interactive:
            require_tty()
        return await command(ui or RichUI())

    try:
        return asyncio.run(main())
    except (Cancelled, KeyboardInterrupt):
        print("Cancelled. Unfinished steps were not saved.")
        return 130
    except NotInteractive:
        print(format_problem(NOT_INTERACTIVE))
        return 2
    except Exception:
        _log_failure()
        print(f"Unexpected error. Details: {paths.log_path()}")
        return 1


def _log_failure() -> None:
    path = paths.log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        return
    log.addHandler(handler)
    try:
        log.exception("unexpected CLI error")
    finally:
        log.removeHandler(handler)
        handler.close()


def load_store() -> ConfigStore:
    paths.migrate_location()
    return ConfigStore(paths.config_path())
