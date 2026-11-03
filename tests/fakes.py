"""In-memory stand-in for TgClient with the same public async methods."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from telegram_reader.config import Config
from telegram_reader.errors import DownloadFailed, InvalidArgument
from telegram_reader.models import ChatInfo, FolderInfo, MediaInfo, MessageData, TopicInfo


# Telegram's search filters, as TgClient.search maps them, by the media kind they match.
_FILTER_KINDS = {
    "documents": ("document",),
    "photos": ("photo",),
    "videos": ("video",),
    "photo_video": ("photo", "video"),
    "voice": ("voice",),
}


class FakeStore:
    """Stands in for ConfigStore: current() returns whatever object `cfg` holds."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def current(self) -> Config:
        return self.cfg


class FakeTg:
    def __init__(
        self,
        dialogs: list[ChatInfo] | None = None,
        folders: list[FolderInfo] | None = None,
        topics: dict[int, list[TopicInfo]] | None = None,
        messages: dict[int, list[MessageData]] | None = None,
    ):
        self.dialogs = dialogs or []
        self.folders = folders or []
        self.topics = topics or {}
        self.messages = messages or {}  # chat_id -> messages, any order
        self.fail: dict[int, Exception] = {}
        self.connect_error: Exception | None = None
        self.calls: list[tuple] = []
        self.account_id: int | None = 1
        self.account_name: str | None = "John"
        self.allowed: frozenset[int] = frozenset()
        self.features: frozenset[str] = frozenset()
        self.folders_error: Exception | None = None
        self.files: dict[tuple[int, int], tuple[MediaInfo, bytes]] = {}

    def set_allowed(self, ids: frozenset[int]) -> None:
        self.allowed = ids

    def set_features(self, enabled: frozenset[str]) -> None:
        self.features = enabled

    def _check(self, chat_id: int) -> None:
        if chat_id in self.fail:
            raise self.fail[chat_id]

    def _newest_first(self, chat_id: int) -> list[MessageData]:
        return sorted(self.messages.get(chat_id, []), key=lambda m: m.id, reverse=True)

    async def connect(self) -> None:
        self.calls.append(("connect",))
        if self.connect_error:
            raise self.connect_error

    async def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    async def chat_infos(self, ids: Iterable[int]) -> list[ChatInfo]:
        ids = list(ids)
        self.calls.append(("chat_infos", tuple(ids)))
        return [c for c in self.dialogs if c.id in ids]

    async def list_folders(self) -> list[FolderInfo]:
        self.calls.append(("list_folders",))
        if self.folders_error:
            raise self.folders_error
        return list(self.folders)

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        self.calls.append(("list_topics", chat_id))
        return list(self.topics.get(chat_id, []))

    def _filter(self, chat_id, limit, since, until, before_id=None, pred=lambda m: True):
        out = []
        for m in self._newest_first(chat_id):
            if until is not None and m.date >= until:
                continue
            if before_id is not None and m.id >= before_id:
                continue
            if since is not None and m.date < since:
                break
            if pred(m):
                out.append(m)
            if len(out) >= limit:
                break
        return out

    async def fetch_messages(
        self,
        chat_id: int,
        *,
        limit: int,
        topic: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        before_id: int | None = None,
    ) -> list[MessageData]:
        self.calls.append(("fetch_messages", chat_id, {"limit": limit, "topic": topic, "before_id": before_id}))
        self._check(chat_id)
        return self._filter(chat_id, limit, since, until, before_id)

    async def search(
        self,
        chat_id: int,
        query: str = "",
        *,
        limit: int,
        topic: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        from_user: object | None = None,
        filter: str | None = None,
    ) -> list[MessageData]:
        self.calls.append(
            (
                "search",
                chat_id,
                {"query": query, "limit": limit, "topic": topic, "from_user": from_user, "filter": filter},
            )
        )
        self._check(chat_id)
        kinds = _FILTER_KINDS.get(filter, ())

        def pred(m: MessageData) -> bool:
            if query.lower() not in m.text.lower():
                return False
            if filter is None:
                return True
            if filter == "url":
                return bool(m.links)
            return m.media is not None and m.media.kind in kinds

        return self._filter(chat_id, limit, since, until, pred=pred)

    async def resolve_user(self, chat_id: int, ref: str) -> object:
        self.calls.append(("resolve_user", chat_id, ref))
        return f"resolved:{ref}"

    async def fetch_around(self, chat_id: int, message_id: int, before: int, after: int) -> list[MessageData]:
        self.calls.append(("fetch_around", chat_id, message_id, before, after))
        self._check(chat_id)
        msgs = sorted(self.messages.get(chat_id, []), key=lambda m: m.id)
        idx = next(i for i, m in enumerate(msgs) if m.id == message_id)
        return msgs[max(0, idx - before) : idx + after + 1]

    async def media_of(self, chat_id: int, message_id: int) -> MediaInfo:
        self.calls.append(("media_of", chat_id, message_id))
        self._check(chat_id)
        if (chat_id, message_id) not in self.files:
            raise InvalidArgument(f"Message #{message_id} has no file")
        return self.files[chat_id, message_id][0]

    async def download(self, chat_id: int, message_id: int, dest: Path, max_bytes: int) -> int:
        """Mirrors TgClient.download: limit enforced while streaming, disk errors as DownloadFailed."""
        self.calls.append(("download", chat_id, message_id))
        self._check(chat_id)
        data = self.files[chat_id, message_id][1]
        if len(data) > max_bytes:
            raise InvalidArgument(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
        try:
            dest.write_bytes(data)
        except OSError as e:
            raise DownloadFailed(e) from None
        return len(data)


def real_readonly_client(monkeypatch, allowed, *, user_id: int = 100, channel_id: int = 7):
    """A real ReadOnlyTelegramClient whose PeerGuard whitelists `allowed`.

    Telethon's own network call is patched to fail, so a request that gets past the guard shows up
    in the returned list. The private chat `user_id` and the supergroup `channel_id` are in the entity
    cache (as after GetPeerDialogs).
    """
    from telethon import TelegramClient as Base
    from telethon._updates import Entity, EntityType
    from telethon.sessions import StringSession

    from telegram_reader.tg import PeerGuard, ReadOnlyTelegramClient

    sent: list = []

    async def network(self, sender, request, ordered=False, flood_sleep_threshold=None):
        sent.append(request)
        raise AssertionError(f"request reached the network: {type(request).__name__}")

    monkeypatch.setattr(Base, "_call", network)
    client = ReadOnlyTelegramClient(StringSession(), 1, "0" * 32, receive_updates=False)
    client.peer_guard = PeerGuard(allowed=frozenset(allowed), self_id=42)
    client._mb_entity_cache.put(Entity(EntityType.USER, user_id, 5))
    client._mb_entity_cache.put(Entity(EntityType.MEGAGROUP, channel_id, 6))
    return client, sent
