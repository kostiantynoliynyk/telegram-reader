"""User-facing tool errors; MCPServer turns them into isError results with this text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError

from .format import NAME_MAX
from .sanitize import clip

if TYPE_CHECKING:
    from .models import ChatInfo


class AccessDenied(ToolError):
    def __init__(self, chat_ref: object):
        super().__init__(f"No access to chat {chat_ref}")


class AmbiguousChat(ToolError):
    def __init__(self, chat_ref: object, candidates: list[ChatInfo]):
        options = "; ".join(f"{c.id} — {clip(c.title, NAME_MAX)}" for c in candidates)
        super().__init__(f"Name «{clip(str(chat_ref), NAME_MAX)}» is ambiguous: {options}")
        self.candidates = candidates


class LoginRequired(ToolError):
    def __init__(self):
        super().__init__("Login required: telegram-reader login")


class SessionRevoked(LoginRequired):
    """A stored session exists but Telegram no longer accepts it (ended from another device)."""


SECRET_STORE_UNAVAILABLE = (
    "No access to the secret store (Keychain / Credential Manager / Secret Service). "
    "Unlock it and try again"
)


class SecretStoreError(ToolError):
    def __init__(self):
        super().__init__(SECRET_STORE_UNAVAILABLE)


class RateLimited(ToolError):
    def __init__(self, seconds: int):
        super().__init__(f"Telegram asks to wait {seconds} s")
        self.seconds = seconds


class InvalidArgument(ToolError):
    pass


class NetworkError(ToolError):
    def __init__(self):
        super().__init__("No connection to Telegram, try again")


class AccountMismatch(ToolError):
    def __init__(self):
        super().__init__("Folders were selected for another Telegram account — run telegram-reader folders")


class DownloadFailed(ToolError):
    """A disk error while saving a download. A ToolError, not an OSError, so with_flood_retry
    never reports it as a network problem."""

    def __init__(self, error: OSError):
        super().__init__(f"Could not write the file: {error.strerror or error}")


@contextmanager
def disk_errors() -> Iterator[None]:
    """Wrap only filesystem calls: a network OSError inside would be misreported as a disk one."""
    try:
        yield
    except OSError as e:
        raise DownloadFailed(e) from None
