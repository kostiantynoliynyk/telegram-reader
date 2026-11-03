"""User-facing texts of the CLI: intro, explanations and the catalog of known problems."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    what: str
    why: str
    todo: str


def format_problem(p: Problem) -> str:
    return f"✗ {p.what}\nWhy: {p.why}\nWhat to do: {p.todo}"


def login_problem(revoked: bool) -> str:
    """LoginRequired in the CLI: a stored session Telegram refuses, or no session at all."""
    return format_problem(SESSION_REVOKED if revoked else LOGIN_FIRST)


INTRO = (
    "telegram-reader lets Claude Code read your Telegram chats — only those in the folders you select.\n"
    "Read-only access: the tool never sends, replies or marks messages as read."
)

WHY_FOLDERS = (
    "Why Telegram folders: convenient — you manage chats right in Telegram; "
    "safe — Claude sees exactly what is in the folder."
)

NO_SECRET_STORE = Problem(
    what="No access to the secret store",
    why="telegram-reader keeps the session and keys in your system's secret store, and it is unavailable",
    todo=(
        "macOS: unlock Keychain (Keychain Access). "
        "Linux: install and start gnome-keyring or KWallet (Secret Service)"
    ),
)
API_ID_INVALID = Problem(
    what="Telegram rejected api_id / api_hash",
    why="the pair does not match or contains a typo",
    todo="check both values at my.telegram.org → API development tools",
)
QR_EXPIRED_MANY = Problem(
    what="The QR code expired several times",
    why="it was not scanned in time",
    todo="scan faster or log in with a code: telegram-reader login --code",
)
BAD_2FA = Problem(
    what="Wrong two-step verification password",
    why="Telegram rejected the 2FA password",
    todo="try again; you can reset the password in the official Telegram app",
)
FLOOD_WAIT = Problem(
    what="Telegram asks to wait {seconds} s",
    why="too many attempts or requests in a short time",
    todo="wait the given time or quit and try later",
)
NO_NETWORK = Problem(
    what="No network or Telegram is unreachable",
    why="could not connect to Telegram servers",
    todo="check your internet, VPN and proxy settings",
)
SESSION_REVOKED = Problem(
    what="Session ended",
    why="it was closed from another device or in Telegram settings",
    todo="log in again: telegram-reader login",
)
CONFIG_BROKEN = Problem(
    what="Config is corrupted",
    why="the file could not be read or has a wrong format",
    todo="keep a copy (config.toml.bak) and recreate the config: telegram-reader setup",
)
CONFIG_TAMPERED = Problem(
    what="Config was changed outside telegram-reader",
    why="the file signature does not match, so it cannot be trusted",
    todo="review the selection and save it again: telegram-reader folders",
)
CLAUDE_NOT_FOUND = Problem(
    what="The claude command was not found",
    why="Claude Code is not installed or not on PATH",
    todo="run the registration command manually (printed below)",
)
NOT_INTERACTIVE = Problem(
    what="This command only works in a terminal",
    why="it asks questions, and standard input or output is not a terminal",
    todo="run it in a regular terminal window",
)
LOGIN_FIRST = Problem(
    what="No saved session",
    why="you have not logged in to Telegram via telegram-reader yet",
    todo="log in first: telegram-reader login",
)
EMAIL_REQUIRED = Problem(
    what="Telegram requires an email for code login",
    why="for this account the code is only sent to a login email, which is not set up",
    todo="add a login email in the official Telegram app (Settings → Privacy and Security → Login Email)",
)
