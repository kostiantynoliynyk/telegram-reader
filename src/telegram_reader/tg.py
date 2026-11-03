"""Read-only wrapper around Telethon that returns plain models.

Only reading methods live here. Nothing in this module may send, edit,
delete, forward, pin or mark messages as read (enforced by tests/test_readonly.py).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from telethon import TelegramClient as _TelethonClient
from telethon import errors, utils
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.messages import (
    GetDialogFiltersRequest,
    GetForumTopicsRequest,
    GetPeerDialogsRequest,
    SearchRequest,
)

from . import keychain
from .features import allowed_requests
from .errors import (
    InvalidArgument,
    LoginRequired,
    NetworkError,
    RateLimited,
    SecretStoreError,
    SessionRevoked,
    disk_errors,
)
from .format import NAME_MAX
from .models import ChatInfo, ChatKind, FolderInfo, LinkInfo, MediaInfo, MessageData, TopicInfo
from .sanitize import clip

T = TypeVar("T")

# Runtime guard: every request the session client sends must be a read.
_READ_PREFIXES = ("Get", "Search", "Resolve", "Check")
_DENIED_READS = {
    "GetMessagesViewsRequest",  # increment=True bumps view counters
    "CheckChatInviteRequest",  # touches chats outside the whitelist
    "CheckUsernameRequest",
    "GetDialogsRequest",  # lists every chat of the account
    "SearchGlobalRequest",  # searches every chat of the account
}


# Requests Telethon's downloader (iter_download) sends through _call. They carry no peer: the
# file location comes from media of a message already fetched from a whitelisted chat.
# ExportAuthorization only moves this account's session to another DC; Telethon sends
# ImportAuthorization via sender.send, outside _call.
DOWNLOAD_REQUESTS = frozenset(
    {"GetFileRequest", "GetCdnFileRequest", "ReuploadCdnFileRequest", "ExportAuthorizationRequest"}
)


def _requests(request: Any) -> list[Any]:
    return list(request) if isinstance(request, (list, tuple)) else [request]


def ensure_read_only(request: Any, extra: frozenset[str] = frozenset()) -> None:
    """extra: exact request names allowed by enabled features (see features.allowed_requests)."""
    for r in _requests(request):
        name = type(r).__name__
        if name in extra:
            continue
        if not name.startswith(_READ_PREFIXES) or name in _DENIED_READS:
            raise PermissionError(f"telegram-reader is read-only; refused {name}")


_PEER_FIELDS = ("peer", "peers", "channel", "chat_id")

# Peerless requests the session client may send: the ones Telethon 1.45 itself sends on the code
# paths we use (TelegramClient.connect/get_me/is_user_authorized/get_input_entity/get_entity/
# get_messages/iter_messages/iter_participants, auto-reconnect) plus our own GetDialogFilters.
# Every other request without a peer field is refused (fail closed).
_PEERLESS_ALLOWED = frozenset(
    {
        "users.GetUsersRequest",  # get_me (InputUserSelf); get_input_entity / get_entity fallback
        "channels.GetChannelsRequest",  # get_input_entity fallback for a channel missing from the cache
        "updates.GetStateRequest",  # is_user_authorized
        "help.GetConfigRequest",  # _get_dc on a DC migration
        "messages.GetMessagesRequest",  # get_messages(ids=…) outside channels; response filtered
        "messages.GetDialogFiltersRequest",  # list_folders (the folder picker and the whitelist)
        # Used only by downloads of media fetched from whitelisted chats (see DOWNLOAD_REQUESTS).
        "upload.GetFileRequest",
        "upload.GetCdnFileRequest",
        "upload.ReuploadCdnFileRequest",
        "auth.ExportAuthorizationRequest",
        "help.GetCdnConfigRequest",  # Telethon fetches the CDN config before a CDN-redirected download
    }
)
# Allowed peerless requests whose `id` lists users/channels: each one is checked like a peer.
_ID_PEERS = frozenset({"users.GetUsersRequest", "channels.GetChannelsRequest"})


def _qualified(request: Any) -> str:
    cls = type(request)
    return f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}"


@dataclass
class PeerGuard:
    """Second line of defense: nothing outside the whitelist goes out or comes back.

    Requests with a peer field (peer, peers, channel, chat_id) go only to whitelisted chats.
    Requests without one pass only if listed in _PEERLESS_ALLOWED (or named exactly by an enabled
    feature); everything else is refused, e.g. updates.GetDifference, messages.GetAllDrafts,
    contacts.ResolveUsername / contacts.Search, messages.GetPinnedDialogs / GetCommonChats.

    Peerless requests Telethon 1.45 sends on our code paths:
    - connect(): InitConnection(help.GetConfig) goes straight to the sender, not through __call__;
      then get_me() → users.GetUsers([InputUserSelf]) and _on_login, which would send
      updates.GetState + updates.GetDifference — ReadOnlyTelegramClient._on_login skips both,
      so the update box stays empty and the update loop never asks for a difference;
    - is_user_authorized(): updates.GetState (only while _authorized is unknown);
    - get_input_entity(int) on a cache miss: users.GetUsers / channels.GetChannels with
      access_hash 0; get_entity (iter_participants of a private chat): users.GetUsers;
    - get_messages(ids=…) outside a channel: messages.GetMessages (ids are account-wide, so the
      response is cut by filter_response); in a channel: channels.GetMessages (peer-checked);
    - auto-reconnect: get_me(); DC migration: help.GetConfig;
    - iter_messages / iter_participants otherwise send peer-bearing GetHistory, Search,
      GetReplies, channels.GetParticipants, messages.GetFullChat; we add GetPeerDialogs,
      GetForumTopics and Search ourselves.
    The `id` users/channels of users.GetUsers and channels.GetChannels must be whitelisted;
    InputUserSelf passes there (own profile, needed before the whitelist exists).
    from_id is not checked: it names an author inside an allowed peer.
    Peerless reads use an allowlist instead of a deny-list.
    """

    allowed: frozenset[int] = frozenset()
    self_id: int | None = None

    def _peer_id(self, value: Any, field: str) -> int:
        if field == "chat_id" and isinstance(value, int):
            return -value  # basic group: raw chat id
        if isinstance(value, (types.InputPeerSelf, types.InputUserSelf)):
            if self.self_id is None:
                raise PermissionError("telegram-reader: own account id is unknown; refused Saved Messages")
            return self.self_id
        if isinstance(value, types.InputDialogPeer):
            return self._peer_id(value.peer, field)
        if isinstance(value, types.InputChannel):
            return utils.get_peer_id(types.PeerChannel(value.channel_id))
        if isinstance(value, int) or getattr(value, "SUBCLASS_OF_ID", None) is not None:
            try:
                return utils.get_peer_id(value)
            except TypeError:
                pass
        # Unresolved strings, folder peers, empty peers: we cannot tell where they point.
        raise PermissionError(f"telegram-reader: cannot verify chat {type(value).__name__}; refused")

    def _check(self, value: Any, field: str) -> None:
        for item in value if isinstance(value, list) else [value]:
            if field == "id" and isinstance(item, types.InputUserSelf):
                continue  # get_me: the account's own profile
            pid = self._peer_id(item, field)
            if pid not in self.allowed:
                raise PermissionError(f"telegram-reader: chat {pid} is outside the whitelist")

    def check_request(self, request: Any, extra: frozenset[str] = frozenset()) -> None:
        """extra: exact request names allowed by enabled features (see features.allowed_requests)."""
        for r in _requests(request):
            peerless = True
            for field in _PEER_FIELDS:
                value = getattr(r, field, None)
                if value is None:
                    continue
                peerless = False
                self._check(value, field)
            if not peerless:
                continue
            name = _qualified(r)
            if name in _ID_PEERS:
                self._check(getattr(r, "id", None) or [], "id")
            elif name not in _PEERLESS_ALLOWED and type(r).__name__ not in extra:
                raise PermissionError(f"telegram-reader: peerless request {name} refused")

    def _keep(self, msg: Any) -> bool:
        peer = getattr(msg, "peer_id", None)
        if peer is None:
            return False
        try:
            return utils.get_peer_id(peer) in self.allowed
        except TypeError:
            return False

    def filter_response(self, result: Any) -> None:
        # Message ids are account-wide in private chats and basic groups, so a by-id fetch
        # can return messages from any chat; drop those outside the whitelist.
        for r in result if isinstance(result, list) else [result]:
            for attr in ("messages", "new_messages"):
                messages = getattr(r, attr, None)
                if isinstance(messages, list):
                    setattr(r, attr, [m for m in messages if self._keep(m)])


class ReadOnlyTelegramClient(_TelethonClient):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.peer_guard = PeerGuard()  # empty until Access fills it
        self.extra_requests: frozenset[str] = frozenset()

    async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        # Telethon's downloader (iter_download) sends requests through _call, bypassing __call__,
        # so the guards live here; __call__ reaches them via super().__call__.
        extra = self.extra_requests | DOWNLOAD_REQUESTS
        ensure_read_only(request, extra)
        self.peer_guard.check_request(request, extra)
        return await super()._call(sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold)

    async def __call__(self, request, ordered=False, flood_sleep_threshold=None):
        result = await super().__call__(request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold)
        self.peer_guard.filter_response(result)
        return result

    async def _on_login(self, user: Any) -> Any:
        # Telethon's version also sends updates.GetState + updates.GetDifference to start the
        # update box; a difference carries new messages of every chat. This client never
        # receives updates, so keep only the bookkeeping and leave the update box empty.
        self._mb_entity_cache.set_self_user(user.id, user.bot, user.access_hash)
        self._authorized = True
        return user


TelegramClient = ReadOnlyTelegramClient

FLOOD_RETRY_MAX = 30
DEVICE_MODEL = "telegram-reader"
RAW_SCAN_MAX = 5000  # raw messages scanned per call, so runs of service messages don't cut pages short
SEARCH_PAGE = 100
_NUMERIC = re.compile(r"-?\d+")
PEER_DIALOGS_CHUNK = 100
PARTICIPANT_SEARCH_LIMIT = 50
# Telegram refuses to list participants: treat the author as not found.
_PARTICIPANTS_FORBIDDEN = (errors.ChatAdminRequiredError, errors.ChannelPrivateError, errors.ForbiddenError)
TOPIC_PAGE = 100
TOPICS_MAX = 1000
_SESSION_ERRORS = (errors.UnauthorizedError, errors.AuthKeyError)

SearchFilter = Literal["documents", "photos", "videos", "photo_video", "voice", "url"]
_SEARCH_FILTERS: dict[str, type] = {
    "documents": types.InputMessagesFilterDocument,
    "photos": types.InputMessagesFilterPhotos,
    "videos": types.InputMessagesFilterVideo,
    "photo_video": types.InputMessagesFilterPhotoVideo,
    "voice": types.InputMessagesFilterVoice,
    "url": types.InputMessagesFilterUrl,
}


async def with_flood_retry(call: Callable[[], Awaitable[T]], *, sleep=asyncio.sleep) -> T:
    for attempt in range(2):
        try:
            return await call()
        except errors.FloodWaitError as e:
            if e.seconds > FLOOD_RETRY_MAX or attempt == 1:
                raise RateLimited(e.seconds) from None
            await sleep(e.seconds)
        except _SESSION_ERRORS:
            raise LoginRequired() from None
        except PermissionError:
            raise  # peer guard refusal (an OSError subclass), not a network problem
        except (ConnectionError, OSError):
            raise NetworkError() from None
    raise AssertionError("unreachable")


def display_name(entity: Any) -> str:
    if entity is None:
        return "Unknown"
    if isinstance(entity, types.User):
        if entity.deleted:
            return "Deleted account"
        full = " ".join(p for p in (entity.first_name, entity.last_name) if p)
        if full:
            return full
        if entity.username:
            return f"@{entity.username}"
        return f"User {entity.id}"
    return getattr(entity, "title", None) or "Unknown"


def _largest_photo_size(photo: Any) -> tuple[int | None, int | None, int | None]:
    """(width, height, bytes) of the biggest regular size; File.size can describe a smaller one."""
    best: tuple[int, int, int] | None = None
    for s in getattr(photo, "sizes", None) or []:
        if isinstance(s, types.PhotoSize):
            size = s.size
        elif isinstance(s, types.PhotoSizeProgressive):
            size = max(s.sizes) if s.sizes else 0
        else:
            continue  # stripped / cached / path previews
        if best is None or s.w * s.h > best[0] * best[1]:
            best = (s.w, s.h, size)
    return best if best else (None, None, None)


def _media_info(msg: types.Message) -> MediaInfo | None:
    media = msg.media
    if media is None or isinstance(media, (types.MessageMediaEmpty, types.MessageMediaWebPage)):
        return None
    if isinstance(media, types.MessageMediaPhoto):  # photo may be PhotoEmpty (expired): still a photo
        w, h, size = _largest_photo_size(media.photo)
        return MediaInfo("photo", mime="image/jpeg", width=w, height=h, size=size)  # Telegram stores photos as JPEG
    kind = next((k for k in ("voice", "video", "audio", "sticker") if getattr(msg, k, None)), None)
    if kind is None and msg.document:
        kind = "document"
    if kind is None:
        return MediaInfo("other", other=type(media).__name__.removeprefix("MessageMedia").lower())
    f = msg.file
    return MediaInfo(
        kind,
        name=f.name if f else None,
        mime=f.mime_type if f else None,
        size=f.size if f else None,
        width=f.width if f else None,
        height=f.height if f else None,
        duration=int(f.duration) if f and f.duration is not None else None,
    )


def _photo_without_sizes(msg: Any) -> bool:
    """An expired photo (PhotoEmpty) or one with only previews: nothing to download."""
    media = msg.media
    if not isinstance(media, types.MessageMediaPhoto):
        return False
    sizes = getattr(media.photo, "sizes", None) or []
    return not any(isinstance(s, (types.PhotoSize, types.PhotoSizeProgressive)) for s in sizes)


def _file_location(msg: types.Message) -> tuple[Any, int | None]:
    """(what to pass to iter_download, dc_id override) for the message's file.

    Telethon's own choice for a photo is sizes[-1], which can be a tiny stripped preview, so ask for
    the largest regular size explicitly.
    """
    media = msg.media
    if isinstance(media, types.MessageMediaPhoto):
        photo = media.photo
        sizes = [s for s in photo.sizes if isinstance(s, (types.PhotoSize, types.PhotoSizeProgressive))]
        best = max(sizes, key=lambda s: s.w * s.h)
        location = types.InputPhotoFileLocation(
            id=photo.id, access_hash=photo.access_hash, file_reference=photo.file_reference, thumb_size=best.type
        )
        return location, photo.dc_id
    return msg.document, None


def _reply_to_id(msg: types.Message) -> int | None:
    header = msg.reply_to
    if not isinstance(header, types.MessageReplyHeader):
        return None
    # In forum topics every message points at the topic root; only reply_to_top_id marks a real reply.
    if header.forum_topic and header.reply_to_top_id is None:
        return None
    # A reply to a message in another chat: its id means nothing here.
    if header.reply_to_peer_id is not None:
        return None
    return header.reply_to_msg_id


def _topic_of(msg: Any) -> int | None:
    header = getattr(msg, "reply_to", None)
    if isinstance(header, types.MessageReplyHeader) and header.forum_topic:
        return header.reply_to_top_id or header.reply_to_msg_id
    return None


def _forwarded_from(msg: types.Message) -> str | None:
    fwd = msg.fwd_from
    if fwd is None:
        return None
    if fwd.from_name:
        return fwd.from_name
    forward = msg.forward
    if forward is not None and (forward.sender or forward.chat):
        return display_name(forward.sender or forward.chat)
    return fwd.post_author or "unknown"


def _links(msg: types.Message) -> tuple[LinkInfo, ...]:
    """Unique links in order of appearance; hidden targets (TextUrl) keep their visible text."""
    found: dict[LinkInfo, None] = {}
    for entity, text in msg.get_entities_text():
        if isinstance(entity, types.MessageEntityUrl):
            found[LinkInfo(text)] = None
        elif isinstance(entity, types.MessageEntityTextUrl):
            found[LinkInfo(entity.url, text)] = None
    return tuple(found)


def to_message_data(msg: Any, chat_id: int) -> MessageData | None:
    if not isinstance(msg, types.Message):
        return None
    if msg.peer_id is None or utils.get_peer_id(msg.peer_id) != chat_id:
        # e.g. discussion-group comments returned for a channel post: not this chat
        return None
    media = _media_info(msg)
    text = msg.message or ""
    if not text and media is None:
        return None
    sender = msg.sender
    name = display_name(msg.chat) if sender is None and msg.post else display_name(sender)
    return MessageData(
        id=msg.id,
        chat_id=chat_id,
        date=msg.date,
        sender=name,
        text=text,
        reply_to_id=_reply_to_id(msg),
        media=media,
        forwarded_from=_forwarded_from(msg),
        links=_links(msg),
    )


def _chat_kind(entity: Any) -> ChatKind:
    if isinstance(entity, types.User):
        return "private"
    if isinstance(entity, types.Channel):
        if entity.forum:
            return "forum"
        return "group" if entity.megagroup else "channel"
    return "group"


def _link_base(entity: Any) -> str | None:
    if not isinstance(entity, types.Channel):
        return None
    if entity.username:
        return f"https://t.me/{entity.username}"
    return f"https://t.me/c/{entity.id}"


class TgClient:
    def __init__(self, api_id: int):
        self._api_id = api_id
        self._client: TelegramClient | None = None
        self._lock = asyncio.Lock()
        self._allowed: frozenset[int] = frozenset()
        self._extra: frozenset[str] = frozenset()
        self._input_peers: dict[int, Any] = {}
        self.account_id: int | None = None
        self.account_name: str | None = None

    def set_allowed(self, ids: frozenset[int]) -> None:
        self._allowed = frozenset(ids)
        if self._client is not None:
            self._client.peer_guard.allowed = self._allowed

    def set_features(self, enabled: frozenset[str]) -> None:
        self._extra = allowed_requests(enabled)
        if self._client is not None:
            self._client.extra_requests = self._extra

    async def connect(self) -> None:
        async with self._lock:
            if self._client is not None:
                if self._client.is_connected():
                    return
                await self._client.disconnect()
                self._client = None
            try:
                api_hash, session = keychain.get_api_hash(), keychain.get_session()
            except keychain.SecretStoreUnavailable:
                raise SecretStoreError() from None
            if not api_hash or not session:
                raise LoginRequired()
            client = TelegramClient(
                StringSession(session),
                self._api_id,
                api_hash,
                device_model=DEVICE_MODEL,
                receive_updates=False,
                # Never sleep silently inside Telethon; with_flood_retry decides.
                flood_sleep_threshold=0,
            )
            client.peer_guard = PeerGuard(allowed=self._allowed)
            client.extra_requests = self._extra

            async def start() -> Any:
                await client.connect()
                if not await client.is_user_authorized():
                    return None
                return await client.get_me()

            try:
                me = await with_flood_retry(start)
            except LoginRequired:
                await client.disconnect()
                raise SessionRevoked() from None  # a session is stored, but Telegram refuses it
            except Exception:
                await client.disconnect()
                raise
            if me is None:
                await client.disconnect()
                raise SessionRevoked()
            self.account_id = me.id
            self.account_name = display_name(me)
            client.peer_guard.self_id = me.id
            self._client = client

    async def disconnect(self) -> None:
        async with self._lock:
            client, self._client = self._client, None
            if client is not None:
                await client.disconnect()

    async def _retry(self, call: Callable[[], Awaitable[T]]) -> T:
        try:
            return await with_flood_retry(call)
        except LoginRequired:
            # Drop the dead client so the next connect() reads a fresh session from the secret store.
            client, self._client = self._client, None
            if client is not None:
                await client.disconnect()
            raise

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise LoginRequired()
        return self._client

    async def list_folders(self) -> list[FolderInfo]:
        result = await self._retry(lambda: self.client(GetDialogFiltersRequest()))
        folders = []
        for f in getattr(result, "filters", result):
            if not isinstance(f, (types.DialogFilter, types.DialogFilterChatlist)):
                continue
            title = f.title if isinstance(f.title, str) else f.title.text
            peer_ids = []
            for peer in [*f.pinned_peers, *f.include_peers]:
                if isinstance(peer, types.InputPeerSelf):
                    if self.account_id is None:
                        continue
                    pid = self.account_id
                else:
                    try:
                        pid = utils.get_peer_id(peer)
                    except TypeError:  # non-addressable peers
                        continue
                peer_ids.append(pid)
                self._input_peers[pid] = peer
            auto = any(getattr(f, flag, None) for flag in ("contacts", "non_contacts", "groups", "broadcasts", "bots"))
            folders.append(FolderInfo(id=f.id, title=title, peer_ids=tuple(peer_ids), has_auto_rules=bool(auto)))
        return folders

    async def chat_infos(self, ids: Iterable[int]) -> list[ChatInfo]:
        """Metadata for whitelisted chats only, via GetPeerDialogs (never the full dialog list).

        Ids must come from list_folders(), which caches their input peers; others are skipped.
        """
        wanted = [(i, self._input_peers[i]) for i in dict.fromkeys(ids) if i in self._input_peers]

        async def chunk(part: list[tuple[int, Any]]) -> list[ChatInfo]:
            result = await self.client(GetPeerDialogsRequest(peers=[types.InputDialogPeer(p) for _, p in part]))
            entities = {utils.get_peer_id(e): e for e in [*result.users, *result.chats]}
            dates = {}
            for m in result.messages:
                if getattr(m, "peer_id", None) is not None:
                    dates[(utils.get_peer_id(m.peer_id), m.id)] = m.date
            out = []
            for d in result.dialogs:
                if not isinstance(d, types.Dialog):
                    continue
                pid = utils.get_peer_id(d.peer)
                entity = entities.get(pid)
                out.append(
                    ChatInfo(
                        id=pid,
                        title=display_name(entity),
                        kind=_chat_kind(entity),
                        link_base=_link_base(entity),
                        unread=d.unread_count,
                        last_date=dates.get((pid, d.top_message)),
                    )
                )
            return out

        infos: list[ChatInfo] = []
        for start in range(0, len(wanted), PEER_DIALOGS_CHUNK):
            part = wanted[start : start + PEER_DIALOGS_CHUNK]
            infos += await self._retry(lambda part=part: chunk(part))
        return infos

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        async def run() -> list[TopicInfo]:
            peer = await self.client.get_input_entity(chat_id)
            found: list[TopicInfo] = []
            offset_date, offset_id, offset_topic = None, 0, 0
            while len(found) < TOPICS_MAX:
                page = await self.client(
                    GetForumTopicsRequest(
                        peer=peer,
                        offset_date=offset_date,
                        offset_id=offset_id,
                        offset_topic=offset_topic,
                        limit=TOPIC_PAGE,
                    )
                )
                # ForumTopicDeleted has no title.
                found += [TopicInfo(t.id, t.title) for t in page.topics if getattr(t, "title", None)]
                if len(page.topics) < TOPIC_PAGE or len(found) >= page.count:
                    break
                last = page.topics[-1]
                offset_date, offset_id, offset_topic = last.date, last.top_message, last.id
            return found

        return await self._retry(run)

    async def _collect(
        self, chat_id: int, limit: int, since: datetime | None, **kwargs: Any
    ) -> list[MessageData]:
        async def run() -> list[MessageData]:
            out: list[MessageData] = []
            it: AsyncIterator = self.client.iter_messages(chat_id, limit=RAW_SCAN_MAX, wait_time=0, **kwargs)
            async for msg in it:
                if since is not None and msg.date < since:
                    break
                data = to_message_data(msg, chat_id)
                if data is not None:
                    out.append(data)
                    if len(out) >= limit:
                        break
            return await self._with_snippets(chat_id, out)

        return await self._retry(run)

    async def _with_snippets(self, chat_id: int, msgs: list[MessageData]) -> list[MessageData]:
        ids = sorted({m.reply_to_id for m in msgs if m.reply_to_id is not None})
        if not ids:
            return msgs
        fetched = await self.client.get_messages(chat_id, ids=ids)
        snippets = {}
        for original in fetched:
            data = to_message_data(original, chat_id) if original is not None else None
            if data is not None:
                snippets[data.id] = data.text or (data.media.kind if data.media else None)
        return [replace(m, reply_snippet=snippets.get(m.reply_to_id)) for m in msgs]

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
        return await self._collect(
            chat_id, limit, since, offset_date=until, max_id=before_id or 0, reply_to=topic
        )

    async def search(
        self,
        chat_id: int,
        query: str = "",
        *,
        limit: int,
        topic: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        from_user: Any = None,
        filter: SearchFilter | None = None,
    ) -> list[MessageData]:
        """from_user is an entity from resolve_user(). filter narrows to files or links (list_files/list_links)."""
        flt = _SEARCH_FILTERS[filter]() if filter is not None else None
        if topic is not None:
            # Telethon's iter_messages drops `search` when reply_to is set, so query the topic directly.
            return await self._retry(
                lambda: self._search_topic(chat_id, query, limit, topic, since, until, from_user, flt)
            )
        return await self._collect(
            chat_id, limit, since, search=query, offset_date=until, from_user=from_user, filter=flt
        )

    async def _search_topic(
        self,
        chat_id: int,
        query: str,
        limit: int,
        topic: int,
        since: datetime | None,
        until: datetime | None,
        from_user: Any,
        flt: Any = None,
    ) -> list[MessageData]:
        peer = await self.client.get_input_entity(chat_id)
        out: list[MessageData] = []
        offset_id = 0
        done = False
        for _ in range(RAW_SCAN_MAX // SEARCH_PAGE):
            if done or len(out) >= limit:
                break
            page = min(SEARCH_PAGE, limit - len(out) + 20)
            result = await self.client(
                SearchRequest(
                    peer=peer,
                    q=query,
                    filter=flt or types.InputMessagesFilterEmpty(),
                    min_date=since,
                    max_date=until,
                    offset_id=offset_id,
                    add_offset=0,
                    limit=page,
                    max_id=0,
                    min_id=0,
                    hash=0,
                    from_id=from_user,
                    top_msg_id=topic,
                )
            )
            entities = {utils.get_peer_id(e): e for e in [*result.users, *result.chats]}
            for msg in result.messages:
                # Telegram may ignore max_date when only a filter is set (see Telethon's iter_messages),
                # so enforce the period here; pages come newest first.
                date = getattr(msg, "date", None)
                if until is not None and date is not None and date > until:
                    continue
                if since is not None and date is not None and date < since:
                    done = True
                    break
                if isinstance(msg, types.Message):
                    msg._finish_init(self.client, entities, peer)
                data = to_message_data(msg, chat_id)
                if data is not None and len(out) < limit:
                    out.append(data)
            if len(result.messages) < page:
                break
            offset_id = result.messages[-1].id
        return await self._with_snippets(chat_id, out)

    async def resolve_user(self, chat_id: int, ref: str) -> Any | None:
        """Find the author for search_messages(from_user=…) among participants of chat_id.

        ref is a username (with or without @) or an exact display name. Never resolved across
        all of Telegram. Returns an input peer, or None if no participant matches.
        """
        stripped = ref.strip()
        query = stripped.removeprefix("@").strip()
        if not query or _NUMERIC.fullmatch(stripped):
            raise InvalidArgument(f"from_user must be a username or a chat member's name: {ref}")

        async def run() -> list[Any]:
            found = []
            try:
                async for user in self.client.iter_participants(
                    chat_id, search=query, limit=PARTICIPANT_SEARCH_LIMIT
                ):
                    found.append(user)
            except _PARTICIPANTS_FORBIDDEN:
                return []
            return found

        users = [u for u in await self._retry(run) if isinstance(u, types.User)]
        by_username = [u for u in users if u.username and u.username.casefold() == query.casefold()]
        if by_username:
            return utils.get_input_peer(by_username[0])
        by_name = [u for u in users if display_name(u) == stripped]
        if not by_name:
            return None
        if len(by_name) > 1:
            names = ", ".join(clip(f"@{u.username}" if u.username else display_name(u), NAME_MAX) for u in by_name)
            raise InvalidArgument(
                f"Several members are named {clip(stripped, NAME_MAX)}: {names}. Specify via @username."
            )
        return utils.get_input_peer(by_name[0])

    async def fetch_around(self, chat_id: int, message_id: int, before: int, after: int) -> list[MessageData]:
        self._ensure_allowed(chat_id)

        async def run() -> list[MessageData]:
            client = self.client
            target = await client.get_messages(chat_id, ids=message_id)
            if target is None:
                raise InvalidArgument(f"Message #{message_id} not found")
            topic = _topic_of(target)  # in forums, stay inside the target's topic
            older = (
                [m async for m in client.iter_messages(chat_id, limit=before, max_id=message_id, reply_to=topic)]
                if before
                else []
            )
            newer = (
                [
                    m
                    async for m in client.iter_messages(
                        chat_id, limit=after, min_id=message_id, reverse=True, reply_to=topic
                    )
                ]
                if after
                else []
            )
            raw = [*reversed(older), target, *newer]
            data = [d for d in (to_message_data(m, chat_id) for m in raw) if d is not None]
            return await self._with_snippets(chat_id, data)

        return await self._retry(run)

    def _ensure_allowed(self, chat_id: int) -> None:
        if chat_id not in self._allowed:
            # Private chats and basic groups fetch by id without a peer, so the request guard can't
            # refuse them; check here so a removed chat reads as "no access", not "not found".
            raise PermissionError(f"telegram-reader: chat {chat_id} is outside the whitelist")

    async def _file_message(self, chat_id: int, message_id: int) -> tuple[Any, MediaInfo]:
        msg = await self.client.get_messages(chat_id, ids=message_id)
        data = to_message_data(msg, chat_id) if msg is not None else None
        media = data.media if data is not None else None
        if media is None or media.kind == "other" or _photo_without_sizes(msg):
            raise InvalidArgument(f"Message #{message_id} has no file")
        return msg, media

    async def media_of(self, chat_id: int, message_id: int) -> MediaInfo:
        self._ensure_allowed(chat_id)
        _, media = await self._retry(lambda: self._file_message(chat_id, message_id))
        return media

    async def download(self, chat_id: int, message_id: int, dest: Path, max_bytes: int) -> int:
        """Stream the message's file into `dest` (truncated first), refusing more than `max_bytes`."""
        self._ensure_allowed(chat_id)

        async def write(msg: Any) -> int:
            location, dc_id = _file_location(msg)
            written = 0
            with disk_errors():
                out = open(dest, "wb")
            try:
                async for chunk in self.client.iter_download(location, dc_id=dc_id):
                    written += len(chunk)
                    if written > max_bytes:
                        raise InvalidArgument(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                    with disk_errors():
                        out.write(chunk)
            finally:
                with disk_errors():
                    out.close()
            return written

        async def run() -> int:
            # The file location sent to Telegram carries no peer the guard could check, so only download
            # media of a message just fetched through the guarded client from this whitelisted chat.
            msg, _ = await self._file_message(chat_id, message_id)
            try:
                return await write(msg)
            except errors.FileReferenceExpiredError:
                msg, _ = await self._file_message(chat_id, message_id)  # fresh file_reference, once
                return await write(msg)

        return await self._retry(run)
