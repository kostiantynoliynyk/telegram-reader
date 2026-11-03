"""The single place that decides which chats Claude may read."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .config import Config
from .errors import AccessDenied, AccountMismatch, AmbiguousChat, LoginRequired
from .format import NAME_MAX
from .models import ChatInfo
from .sanitize import clip
from .store import ConfigStore

log = logging.getLogger("telegram_reader")

FOLDER_TTL_SECONDS = 5
_NUMERIC = re.compile(r"-?\d+")
_OLDEST = datetime.min.replace(tzinfo=UTC)


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def _as_id(ref: str | int) -> int | None:
    if isinstance(ref, int):
        return ref
    stripped = ref.strip()
    return int(stripped) if _NUMERIC.fullmatch(stripped) else None


def _match(ref: str | int, chats: Iterable[ChatInfo]) -> list[ChatInfo]:
    chats = list(chats)
    chat_id = _as_id(ref)
    if chat_id is not None:
        by_id = [c for c in chats if c.id == chat_id]
        if by_id or isinstance(ref, int):
            return by_id
    # A numeric-looking string that is no known id may still be a title, e.g. a chat named "2026".
    wanted = _norm(str(ref))
    return [c for c in chats if _norm(c.title) == wanted]


class Access:
    """Whitelist = chats in the folders picked in the config, re-checked at most every FOLDER_TTL_SECONDS.

    Any failure while refreshing empties the Telegram-side guard and the cache (fail closed).
    """

    def __init__(self, tg: Any, store: ConfigStore, *, clock: Callable[[], float] = time.monotonic):
        self._tg = tg
        self._store = store
        self._clock = clock
        self._allowed: dict[int, ChatInfo] = {}
        self._refreshed_at: float | None = None
        self._cfg: Config | None = None
        self._lock = asyncio.Lock()
        self.warnings: list[str] = []

    def _lock_down(self) -> None:
        self._tg.set_allowed(frozenset())
        self._allowed = {}
        self._refreshed_at = None
        self._cfg = None

    async def _refresh(self, cfg: Config, *, fresh_metadata: bool) -> None:
        if cfg.account_id != self._tg.account_id:
            raise AccountMismatch()
        self._tg.set_features(cfg.features)
        folders = {f.id: f for f in await self._tg.list_folders()}
        warnings: list[str] = []
        ids: set[int] = set()
        for ref in cfg.folders:
            folder = folders.get(ref.id)
            if folder is None:
                warnings.append(f"Selected folder «{clip(ref.title, NAME_MAX)}» no longer exists — run telegram-reader folders")
                continue
            if folder.has_auto_rules:
                warnings.append(f"Folder «{clip(folder.title, NAME_MAX)}»: automatic rules are ignored")
            ids.update(folder.peer_ids)

        # The guard must know the ids before any metadata request for them goes out.
        self._tg.set_allowed(frozenset(ids))
        known = {} if fresh_metadata else {i: c for i, c in self._allowed.items() if i in ids}
        new_ids = [i for i in ids if i not in known]
        if new_ids:
            for info in await self._tg.chat_infos(new_ids):
                if info.kind == "forum":
                    try:
                        info = replace(info, topics=tuple(await self._tg.list_topics(info.id)))
                    except LoginRequired:
                        raise
                    except Exception as e:
                        # One unreachable forum must not take the whole whitelist down.
                        warnings.append(f"Topics of chat «{clip(info.title, NAME_MAX)}» are unavailable: {e}")
                known[info.id] = info

        self._allowed = known
        if warnings != self.warnings:
            for warning in warnings:
                log.warning("whitelist: %s", warning)
        self.warnings = warnings
        self._cfg = cfg
        self._refreshed_at = self._clock()

    async def _ensure_fresh(self, *, fresh_metadata: bool = False) -> None:
        async with self._lock:
            cfg = self._store.current()
            if (
                not fresh_metadata
                and cfg is self._cfg
                and self._refreshed_at is not None
                and self._clock() - self._refreshed_at < FOLDER_TTL_SECONDS
            ):
                return
            try:
                await self._refresh(cfg, fresh_metadata=fresh_metadata)
            except BaseException:
                self._lock_down()
                raise

    async def allowed_chats(self, *, fresh_metadata: bool = False) -> list[ChatInfo]:
        await self._ensure_fresh(fresh_metadata=fresh_metadata)
        return sorted(self._allowed.values(), key=lambda c: c.last_date or _OLDEST, reverse=True)

    async def resolve(self, chat: str | int) -> ChatInfo:
        await self._ensure_fresh()
        matches = _match(chat, self._allowed.values())
        if not matches:
            raise AccessDenied(chat)
        if len(matches) > 1:
            raise AmbiguousChat(chat, matches)
        return matches[0]
