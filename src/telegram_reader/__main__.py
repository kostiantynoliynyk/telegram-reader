"""CLI entry point: telegram-reader [serve|setup|folders|login|features|status|logout]."""

from __future__ import annotations

import argparse
import functools
import sys
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

from .access import Access
from .cli.claude_code import find_claude, is_registered
from .cli.common import load_store, run
from .cli.features_cmd import run_features
from .cli.folders import run_folders
from .cli.login import run_login, run_logout
from .cli.setup import run_setup
from .cli.status import run_status
from .cli.ui import UI
from .format import local_tz
from .server import build_server, setup_logging
from .tg import TgClient


def serve() -> int:
    store = load_store()
    try:
        cfg = store.current()
    except ToolError as e:
        print(e, file=sys.stderr)
        return 2
    setup_logging()
    tg = TgClient(cfg.api_id)
    build_server(tg, Access(tg, store), store, local_tz()).run("stdio")
    return 0


async def setup(ui: UI) -> int:
    return await run_setup(ui)


async def folders(ui: UI) -> int:
    return await run_folders(ui)


async def login(ui: UI, *, method: Literal["qr", "code"] = "qr") -> int:
    return await run_login(ui, method=method)


async def features(ui: UI) -> int:
    return await run_features(ui)


async def status(ui: UI) -> int:
    return await run_status(ui, registered=lambda: is_registered(c) if (c := find_claude()) else None)


async def logout(ui: UI) -> int:
    return await run_logout(ui)


_COMMANDS = ("setup", "folders", "login", "features", "status", "logout")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-reader", description="Read-only Telegram MCP server")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="MCP server (default)")
    sub.add_parser("setup", help="first-time setup")
    sub.add_parser("folders", help="change the folder selection")
    p = sub.add_parser("login", help="log in to Telegram")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--qr", action="store_true", help="log in with a QR code (default)")
    mode.add_argument("--code", action="store_true", help="log in with a code")
    sub.add_parser("features", help="enable or disable features")
    sub.add_parser("status", help="setup status")
    sub.add_parser("logout", help="log out and remove the session")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cmd = args.command or "serve"
    if cmd == "serve":
        return serve()
    handler = globals()[cmd]
    if cmd == "login":
        handler = functools.wraps(handler)(functools.partial(handler, method="code" if args.code else "qr"))
    return run(handler, interactive=cmd != "status")


if __name__ == "__main__":
    sys.exit(main())
