"""Registration of the MCP server in Claude Code via the `claude` CLI."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

NAME = "telegram-reader"
TIMEOUT_SECONDS = 30


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found is None and os.name == "nt":
        found = shutil.which("claude.cmd")
    return found


def server_command() -> list[str]:
    exe = shutil.which("telegram-reader")
    if exe is None:
        return [sys.executable, "-m", "telegram_reader", "serve"]
    return [exe, "serve"]


def is_registered(claude: str) -> bool:
    try:
        result = subprocess.run([claude, "mcp", "get", NAME], capture_output=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False  # unknown: treat as not registered; setup then offers to register
    return result.returncode == 0


def _add_argv(claude: str) -> list[str]:
    return [claude, "mcp", "add", "--scope", "user", NAME, "--", *server_command()]


def register(claude: str) -> None:
    try:
        subprocess.run(_add_argv(claude), check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude mcp add did not respond within {TIMEOUT_SECONDS} s") from e
    except OSError as e:
        raise RuntimeError(f"could not start claude mcp add: {e.strerror or type(e).__name__}") from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        raise RuntimeError((stderr or "").strip() or f"claude mcp add exited with code {e.returncode}") from e


def manual_command() -> str:
    return shlex.join(_add_argv("claude"))
