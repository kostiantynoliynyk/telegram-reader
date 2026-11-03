from datetime import UTC, datetime

from types import SimpleNamespace

import pytest
from telethon import errors, utils
from telethon.tl import functions, types

from telegram_reader.errors import LoginRequired, NetworkError, RateLimited
from telegram_reader.models import LinkInfo, MediaInfo
from telegram_reader.tg import DOWNLOAD_REQUESTS, display_name, to_message_data, with_flood_retry

DT = datetime(2026, 10, 12, 11, 3, tzinfo=UTC)
CHAT_ID = utils.get_peer_id(types.PeerChannel(1234567))  # chat of message() below


def channel(title="News", **kw):
    return types.Channel(id=4, title=title, photo=types.ChatPhotoEmpty(), date=None, **kw)


def message(text="Hello", sender=None, chat=None, **kw):
    m = types.Message(id=10, peer_id=types.PeerChannel(1234567), date=DT, message=text, **kw)
    m._sender = sender
    m._chat = chat
    return m


def test_display_name_fallbacks():
    assert display_name(types.User(id=1, first_name="John", last_name="Smith")) == "John Smith"
    assert display_name(types.User(id=1, first_name="John")) == "John"
    assert display_name(types.User(id=2, username="sam")) == "@sam"
    assert display_name(types.User(id=3)) == "User 3"
    assert display_name(types.User(id=3, deleted=True)) == "Deleted account"
    assert display_name(channel()) == "News"
    assert display_name(None) == "Unknown"


def test_service_messages_skipped():
    svc = types.MessageService(
        id=1,
        peer_id=types.PeerChat(1),
        date=DT,
        action=types.MessageActionChatJoinedByLink(inviter_id=2),
    )
    assert to_message_data(svc, CHAT_ID) is None


def test_empty_message_skipped():
    assert to_message_data(message(text=""), CHAT_ID) is None


def test_text_message_converted():
    m = message(
        sender=types.User(id=1, first_name="John"),
        reply_to=types.MessageReplyHeader(reply_to_msg_id=7),
    )
    data = to_message_data(m, CHAT_ID)
    assert data is not None
    assert (data.id, data.chat_id, data.date, data.sender, data.text, data.reply_to_id) == (
        10,
        CHAT_ID,
        DT,
        "John",
        "Hello",
        7,
    )
    assert data.media is None and data.forwarded_from is None


def test_topic_root_reply_is_not_a_reply():
    # In forums every message replies to the topic's root; that is not a real reply.
    m = message(reply_to=types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=5))
    assert to_message_data(m, CHAT_ID).reply_to_id is None


def _doc(attributes, mime="application/pdf", size=1):
    return types.Document(
        id=1, access_hash=1, file_reference=b"", date=DT, mime_type=mime, size=size, dc_id=1, attributes=attributes
    )


def test_document_media_info():
    doc = _doc([types.DocumentAttributeFilename("a.pdf")], size=2_411_724)
    m = message(text="", media=types.MessageMediaDocument(document=doc))
    assert to_message_data(m, CHAT_ID).media == MediaInfo(
        "document", name="a.pdf", mime="application/pdf", size=2_411_724
    )


def test_photo_media_info_uses_largest_size():
    photo = types.Photo(
        id=1,
        access_hash=1,
        file_reference=b"",
        date=DT,
        dc_id=1,
        sizes=[
            types.PhotoStrippedSize(type="i", bytes=b"\x01"),
            types.PhotoSize(type="m", w=320, h=240, size=10_000),
            types.PhotoSizeProgressive(type="y", w=1280, h=960, sizes=[50_000, 215_040]),
        ],
    )
    m = message(text="caption", media=types.MessageMediaPhoto(photo=photo))
    data = to_message_data(m, CHAT_ID)
    assert data.media == MediaInfo("photo", mime="image/jpeg", width=1280, height=960, size=215_040) and data.text == "caption"


def test_photo_without_sizes_has_only_kind():
    m = message(text="", media=types.MessageMediaPhoto(photo=types.PhotoEmpty(id=1)))
    assert to_message_data(m, CHAT_ID).media == MediaInfo("photo", mime="image/jpeg")


def test_voice_media_info_has_duration():
    doc = _doc([types.DocumentAttributeAudio(duration=47, voice=True)], mime="audio/ogg", size=184_320)
    m = message(text="", media=types.MessageMediaDocument(document=doc, voice=True))
    data = to_message_data(m, CHAT_ID)
    assert data.media.kind == "voice" and data.media.duration == 47 and data.media.size == 184_320


def test_poll_is_other():
    poll = types.MessageMediaPoll(
        poll=types.Poll(id=1, question=types.TextWithEntities("q", []), answers=[], hash=0),
        results=types.PollResults(),
    )
    assert to_message_data(message(text="", media=poll), CHAT_ID).media == MediaInfo("other", other="poll")


def test_channel_post_sender_is_channel():
    m = message(post=True, sender=None, chat=channel("News"))
    assert to_message_data(m, CHAT_ID).sender == "News"


def test_forward_from_name():
    m = message(fwd_from=types.MessageFwdHeader(date=DT, from_name="Anonymous"))
    assert to_message_data(m, CHAT_ID).forwarded_from == "Anonymous"


def calls(*outcomes):
    it = iter(outcomes)

    async def call():
        item = next(it)
        if isinstance(item, BaseException):
            raise item
        return item

    return call


class Sleeper:
    def __init__(self):
        self.slept = []

    async def __call__(self, seconds):
        self.slept.append(seconds)


async def test_flood_short_waits_and_retries():
    sleep = Sleeper()
    result = await with_flood_retry(calls(errors.FloodWaitError(None, capture=5), "ok"), sleep=sleep)
    assert result == "ok" and sleep.slept == [5]


async def test_flood_long_raises_rate_limited():
    sleep = Sleeper()
    with pytest.raises(RateLimited, match="120"):
        await with_flood_retry(calls(errors.FloodWaitError(None, capture=120)), sleep=sleep)
    assert sleep.slept == []


async def test_flood_twice_raises_rate_limited():
    flood = errors.FloodWaitError(None, capture=5)
    with pytest.raises(RateLimited):
        await with_flood_retry(calls(flood, errors.FloodWaitError(None, capture=5)), sleep=Sleeper())


@pytest.mark.parametrize(
    "exc",
    [
        errors.SessionRevokedError(None),
        errors.AuthKeyUnregisteredError(None),
        errors.UserDeactivatedError(None),
    ],
)
async def test_revoked_session_maps_to_login_required(exc):
    with pytest.raises(LoginRequired):
        await with_flood_retry(calls(exc), sleep=Sleeper())


async def test_connection_error_maps_to_network_error():
    with pytest.raises(NetworkError):
        await with_flood_retry(calls(ConnectionError("down")), sleep=Sleeper())


# --- TgClient against a stand-in for the Telethon client -------------------

from telethon.tl.functions.messages import SearchRequest  # noqa: E402

from telegram_reader import tg as tg_module  # noqa: E402
from telegram_reader.errors import InvalidArgument  # noqa: E402
from telegram_reader.models import FolderInfo  # noqa: E402
from telegram_reader.tg import TgClient  # noqa: E402


class FakeTelethon:
    def __init__(self, raw=(), response=None, by_id=None):
        self.raw = list(raw)
        self.response = response  # a list is served one item per call
        self.by_id = by_id or {}
        self.requests = []
        self.iter_kwargs = []
        self.entity_args = []
        self.disconnected = False
        self._self_id = 1
        self._mb_entity_cache = SimpleNamespace(get=lambda _id: None)

    async def disconnect(self):
        self.disconnected = True

    def iter_messages(self, chat_id, **kwargs):
        self.iter_kwargs.append(kwargs)

        cap = kwargs.get("limit")

        async def gen():
            for i, m in enumerate(self.raw):
                if cap is not None and i >= cap:
                    return
                yield m

        return gen()

    async def get_messages(self, chat_id, ids):
        if isinstance(ids, int):
            return self.by_id.get(ids)
        return [self.by_id.get(i) for i in ids]

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(self.response, list):
            return self.response.pop(0)
        return self.response

    async def get_input_entity(self, ref):
        self.entity_args.append(ref)
        if ref == "bad":
            raise ValueError("no such user")
        if ref == "rpc":
            raise errors.UsernameInvalidError(None)
        return types.InputPeerUser(user_id=42, access_hash=0)


def client_with(fake):
    client = TgClient(1)
    client._client = fake
    return client


def service(id):
    return types.MessageService(
        id=id, peer_id=types.PeerChat(1), date=DT, action=types.MessageActionChatJoinedByLink(inviter_id=2)
    )


async def test_fetch_skips_many_service_messages():
    raw = [service(1000 - i) for i in range(100)] + [message(text=f"m{i}") for i in range(3)]
    result = await client_with(FakeTelethon(raw)).fetch_messages(CHAT_ID, limit=3)
    assert [m.text for m in result] == ["m0", "m1", "m2"]


async def test_topic_search_sends_search_request_with_top_msg_id():
    response = types.messages.Messages(messages=[message(text="meeting")], topics=[], chats=[], users=[])
    fake = FakeTelethon(response=response)
    result = await client_with(fake).search(CHAT_ID, "meeting", limit=5, topic=7)
    (request,) = fake.requests
    assert isinstance(request, SearchRequest)
    assert request.q == "meeting" and request.top_msg_id == 7
    assert [m.text for m in result] == ["meeting"]


async def test_list_folders_accepts_shared_chatlist():
    folder = types.DialogFilterChatlist(
        id=1,
        title=types.TextWithEntities(text="Work", entities=[]),
        pinned_peers=[],
        include_peers=[types.InputPeerChannel(channel_id=1234567, access_hash=0)],
    )
    fake = FakeTelethon(response=types.messages.DialogFilters(filters=[folder]))
    expected_id = utils.get_peer_id(types.PeerChannel(1234567))
    assert await client_with(fake).list_folders() == [FolderInfo(1, "Work", (expected_id,), False)]


def test_cross_chat_reply_has_no_reply_id():
    header = types.MessageReplyHeader(reply_to_msg_id=7, reply_to_peer_id=types.PeerChannel(999))
    assert to_message_data(message(reply_to=header), CHAT_ID).reply_to_id is None


async def test_client_disables_telethon_auto_flood_sleep(monkeypatch):
    created = {}

    class Recorder:
        def __init__(self, *args, **kwargs):
            created.update(kwargs)

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        def is_connected(self):
            return True

        async def get_me(self):
            return types.User(id=42)

    monkeypatch.setattr(tg_module, "TelegramClient", Recorder)
    monkeypatch.setattr(tg_module, "StringSession", lambda s: s)
    monkeypatch.setattr(tg_module.keychain, "get_api_hash", lambda: "hash")
    monkeypatch.setattr(tg_module.keychain, "get_session", lambda: "session")
    await TgClient(1).connect()
    assert created["flood_sleep_threshold"] == 0


@pytest.mark.parametrize(
    "header,topic",
    [
        (types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=7), 7),
        (types.MessageReplyHeader(forum_topic=True, reply_to_msg_id=20, reply_to_top_id=7), 7),
        (types.MessageReplyHeader(reply_to_msg_id=20), None),
        (None, None),
    ],
)
async def test_context_stays_inside_targets_topic(header, topic):
    target = message(reply_to=header)
    fake = FakeTelethon(by_id={10: target})
    client = client_with(fake)
    client._allowed = frozenset({CHAT_ID})
    await client.fetch_around(CHAT_ID, 10, before=2, after=2)
    assert [kw.get("reply_to") for kw in fake.iter_kwargs] == [topic, topic]


async def test_context_of_removed_chat_is_access_denied():
    fake = FakeTelethon(by_id={10: message()})
    with pytest.raises(PermissionError, match="outside the whitelist"):
        await client_with(fake).fetch_around(CHAT_ID, 10, before=2, after=2)
    assert fake.iter_kwargs == []


async def test_topics_paginated():
    from types import SimpleNamespace as NS

    def topics(start, n):
        return [NS(id=i, title=f"t{i}", date=DT, top_message=1000 + i) for i in range(start, start + n)]

    pages = [NS(count=105, topics=topics(1, 100)), NS(count=105, topics=topics(101, 5))]
    fake = FakeTelethon(response=pages)
    result = await client_with(fake).list_topics(CHAT_ID)
    assert len(result) == 105 and result[-1].id == 105
    assert fake.requests[1].offset_topic == 100 and fake.requests[1].offset_id == 1100


async def test_deleted_topics_skipped():
    from types import SimpleNamespace as NS

    fake = FakeTelethon(response=NS(count=2, topics=[NS(id=1, title="a", date=DT, top_message=5), NS(id=2)]))
    assert [t.id for t in await client_with(fake).list_topics(CHAT_ID)] == [1]


# --- forwarded messages and guards -----------------------------------------


def test_message_from_another_chat_is_dropped():
    # e.g. channel comments: GetReplies on a broadcast channel returns discussion-group messages
    other = types.Message(id=3, peer_id=types.PeerChannel(555), date=DT, message="comment")
    assert to_message_data(other, CHAT_ID) is None


async def test_session_error_resets_client_so_relogin_is_picked_up():
    class Revoked(FakeTelethon):
        def iter_messages(self, chat_id, **kwargs):
            raise errors.SessionRevokedError(None)

    fake = Revoked()
    client = client_with(fake)
    with pytest.raises(LoginRequired):
        await client.fetch_messages(CHAT_ID, limit=5)
    assert client._client is None and fake.disconnected


@pytest.mark.parametrize(
    "request_cls",
    ["ReadHistoryRequest", "SetTypingRequest", "SendMessageRequest", "GetMessagesViewsRequest", "ReadDiscussionRequest"],
)
def test_runtime_guard_rejects_writes(request_cls):
    from telethon.tl.functions import messages as m

    from telegram_reader.tg import ensure_read_only

    request = getattr(m, request_cls).__new__(getattr(m, request_cls))
    with pytest.raises(PermissionError):
        ensure_read_only(request)


@pytest.mark.parametrize(
    "path",
    [
        "messages.GetHistoryRequest",
        "messages.SearchRequest",
        "messages.GetRepliesRequest",
        "channels.GetMessagesRequest",
        "contacts.ResolveUsernameRequest",
        "users.GetUsersRequest",
        "updates.GetStateRequest",
    ],
)
def test_runtime_guard_allows_reads(path):
    from telethon.tl import functions

    from telegram_reader.tg import ensure_read_only

    module, name = path.split(".")
    cls = getattr(getattr(functions, module), name)
    ensure_read_only(cls.__new__(cls))
    ensure_read_only([cls.__new__(cls)])


def test_session_client_uses_read_only_class(monkeypatch):
    from telegram_reader.tg import ReadOnlyTelegramClient

    assert tg_module.TelegramClient is ReadOnlyTelegramClient


async def test_topic_search_keeps_forward_names():
    fwd = types.MessageFwdHeader(date=DT, from_id=types.PeerUser(9))
    user = types.User(id=9, first_name="Mark")
    response = types.messages.Messages(messages=[message(text="x", fwd_from=fwd)], topics=[], chats=[], users=[user])
    result = await client_with(FakeTelethon(response=response)).search(CHAT_ID, "x", limit=5, topic=7)
    assert result[0].forwarded_from == "Mark"


# --- peer guard, whitelisted metadata, author among participants ----------

from telethon.tl.functions.channels import GetParticipantsRequest  # noqa: E402
from telethon.tl.functions.messages import (  # noqa: E402
    GetDialogsRequest,
    GetFullChatRequest,
    GetHistoryRequest,
    GetPeerDialogsRequest,
    SearchGlobalRequest,
    SendMessageRequest,
)

from telegram_reader.models import ChatInfo  # noqa: E402
from telegram_reader.tg import PeerGuard, ReadOnlyTelegramClient, ensure_read_only  # noqa: E402

OUTSIDE = "outside the whitelist"


def history(peer):
    return GetHistoryRequest(
        peer=peer, offset_id=0, offset_date=None, add_offset=0, limit=1, max_id=0, min_id=0, hash=0
    )


def search_req(peer, from_id=None):
    return SearchRequest(
        peer=peer,
        q="x",
        filter=types.InputMessagesFilterEmpty(),
        min_date=None,
        max_date=None,
        offset_id=0,
        add_offset=0,
        limit=1,
        max_id=0,
        min_id=0,
        hash=0,
        from_id=from_id,
    )


def mk_msg(peer, id=1):
    return types.Message(id=id, peer_id=peer, date=DT, message="m")


def channel_id(cid):
    return utils.get_peer_id(types.PeerChannel(cid))


def test_guard_rejects_request_to_outside_peer():
    g = PeerGuard(allowed=frozenset({-1001}), self_id=42)
    with pytest.raises(PermissionError, match=OUTSIDE):
        g.check_request(history(types.InputPeerChannel(2, 0)))


def test_guard_allows_request_to_whitelisted_peer():
    g = PeerGuard(allowed=frozenset({channel_id(2), 100}), self_id=42)
    g.check_request(history(types.InputPeerChannel(2, 0)))
    g.check_request(history(types.InputPeerUser(100, 0)))


def test_guard_empty_until_filled():
    with pytest.raises(PermissionError, match=OUTSIDE):
        PeerGuard(allowed=frozenset(), self_id=None).check_request(history(types.InputPeerUser(100, 0)))


def test_guard_checks_every_peer_in_peers_list():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    ok = types.InputDialogPeer(types.InputPeerUser(100, 0))
    bad = types.InputDialogPeer(types.InputPeerUser(200, 0))
    g.check_request(GetPeerDialogsRequest(peers=[ok]))
    with pytest.raises(PermissionError, match="200"):
        g.check_request(GetPeerDialogsRequest(peers=[ok, bad]))


def test_guard_rejects_folder_dialog_peer():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    with pytest.raises(PermissionError):
        g.check_request(GetPeerDialogsRequest(peers=[types.InputDialogPeerFolder(folder_id=1)]))


def test_guard_checks_basic_chat_id():
    PeerGuard(allowed=frozenset({-5}), self_id=42).check_request(GetFullChatRequest(chat_id=5))
    with pytest.raises(PermissionError, match=OUTSIDE):
        PeerGuard(allowed=frozenset({-6}), self_id=42).check_request(GetFullChatRequest(chat_id=5))


def test_guard_checks_channel_field():
    req = GetParticipantsRequest(
        channel=types.InputChannel(7, 0), filter=types.ChannelParticipantsSearch(""), offset=0, limit=1, hash=0
    )
    PeerGuard(allowed=frozenset({channel_id(7)}), self_id=42).check_request(req)
    with pytest.raises(PermissionError, match=OUTSIDE):
        PeerGuard(allowed=frozenset({channel_id(8)}), self_id=42).check_request(req)


def test_guard_saved_messages_need_self_in_whitelist():
    with pytest.raises(PermissionError, match=OUTSIDE):
        PeerGuard(allowed=frozenset({100}), self_id=42).check_request(history(types.InputPeerSelf()))
    with pytest.raises(PermissionError):
        PeerGuard(allowed=frozenset({100}), self_id=None).check_request(history(types.InputPeerSelf()))
    PeerGuard(allowed=frozenset({42}), self_id=42).check_request(history(types.InputPeerSelf()))


def test_guard_unresolved_string_peer_fails_closed():
    with pytest.raises(PermissionError):
        PeerGuard(allowed=frozenset({100}), self_id=42).check_request(history("someone"))


def test_guard_does_not_check_from_id():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    g.check_request(search_req(types.InputPeerUser(100, 0), from_id=types.InputPeerUser(777, 0)))


def test_guard_passes_peerless_reads():
    # Telethon's own internals (get_me, GetState, get_messages by ids) carry no peer field.
    from telethon.tl.functions.users import GetUsersRequest

    PeerGuard(allowed=frozenset(), self_id=None).check_request(GetUsersRequest(id=[types.InputUserSelf()]))


def test_guard_checks_each_request_in_a_batch():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    with pytest.raises(PermissionError):
        g.check_request([history(types.InputPeerUser(100, 0)), history(types.InputPeerUser(200, 0))])


def test_guard_drops_messages_from_other_chats():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    no_peer = mk_msg(peer=types.PeerUser(100), id=3)
    no_peer.peer_id = None  # e.g. MessageEmpty without a peer
    res = types.messages.Messages(
        messages=[mk_msg(peer=types.PeerUser(100)), mk_msg(peer=types.PeerUser(200)), no_peer],
        chats=[],
        users=[],
        topics=[],
    )
    g.filter_response(res)
    assert [utils.get_peer_id(m.peer_id) for m in res.messages] == [100]


def test_guard_filter_ignores_results_without_messages():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    g.filter_response(types.User(id=1))
    g.filter_response(None)


def test_dialogs_and_global_search_denied():
    dialogs = GetDialogsRequest(
        offset_date=None, offset_id=0, offset_peer=types.InputPeerEmpty(), limit=1, hash=0
    )
    global_search = SearchGlobalRequest(
        q="x",
        filter=types.InputMessagesFilterEmpty(),
        min_date=None,
        max_date=None,
        offset_rate=0,
        offset_peer=types.InputPeerEmpty(),
        offset_id=0,
        limit=1,
    )
    for req in (dialogs, global_search):
        with pytest.raises(PermissionError):
            ensure_read_only(req)


def test_extra_requests_allow_exact_names():
    req = SendMessageRequest(peer=types.InputPeerUser(100, 0), message="hi")
    ensure_read_only(req, extra=frozenset({"SendMessageRequest"}))
    with pytest.raises(PermissionError):
        ensure_read_only(req)
    with pytest.raises(PermissionError):
        ensure_read_only(req, extra=frozenset({"SendMessage"}))


async def test_read_only_client_runs_guards_in_order(monkeypatch):
    from telethon import TelegramClient as Base

    sent = []

    async def fake_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        sent.append(request)
        return types.messages.Messages(
            messages=[mk_msg(types.PeerUser(100)), mk_msg(types.PeerUser(200))], chats=[], users=[], topics=[]
        )

    monkeypatch.setattr(Base, "_call", fake_call)
    client = ReadOnlyTelegramClient.__new__(ReadOnlyTelegramClient)
    client._sender = object()  # Telethon's __call__ passes it to _call
    client.peer_guard = PeerGuard(allowed=frozenset({100}), self_id=42)
    client.extra_requests = frozenset()
    res = await ReadOnlyTelegramClient.__call__(client, history(types.InputPeerUser(100, 0)))
    assert [utils.get_peer_id(m.peer_id) for m in res.messages] == [100]
    with pytest.raises(PermissionError):
        await ReadOnlyTelegramClient.__call__(client, history(types.InputPeerUser(200, 0)))
    assert len(sent) == 1


def guarded_client(monkeypatch, allowed):
    from telethon import TelegramClient as Base

    sent = []

    async def fake_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        sent.append(request)

    monkeypatch.setattr(Base, "_call", fake_call)
    client = ReadOnlyTelegramClient.__new__(ReadOnlyTelegramClient)
    client.peer_guard = PeerGuard(allowed=frozenset(allowed), self_id=42)
    client.extra_requests = frozenset()
    client.sent = sent
    return client


async def test_guard_runs_on_internal_call(monkeypatch):
    # Telethon's downloader uses _call directly, bypassing __call__.
    client = guarded_client(monkeypatch, allowed={100})
    req = functions.messages.SendMessageRequest(peer=types.InputPeerUser(100, 0), message="x")
    with pytest.raises(PermissionError):
        await ReadOnlyTelegramClient._call(client, object(), req)
    assert client.sent == []


@pytest.mark.parametrize(
    "req",
    [
        functions.upload.GetFileRequest(location=types.InputDocumentFileLocation(1, 2, b"", ""), offset=0, limit=1024),
        functions.auth.ExportAuthorizationRequest(dc_id=2),
    ],
)
async def test_download_requests_allowed_on_internal_call(monkeypatch, req):
    client = guarded_client(monkeypatch, allowed={100})
    await ReadOnlyTelegramClient._call(client, object(), req)  # no PermissionError
    assert client.sent == [req]


def test_cdn_config_request_passes_peer_guard():
    PeerGuard().check_request(functions.help.GetCdnConfigRequest())
    ensure_read_only(functions.help.GetCdnConfigRequest())


def test_download_allowlist_is_exact():
    assert DOWNLOAD_REQUESTS == {
        "GetFileRequest",
        "GetCdnFileRequest",
        "ReuploadCdnFileRequest",
        "ExportAuthorizationRequest",
    }


def test_read_only_client_defaults_to_empty_whitelist():
    from telethon.sessions import StringSession

    client = ReadOnlyTelegramClient(StringSession(), 1, "hash")
    assert client.peer_guard.allowed == frozenset() and client.extra_requests == frozenset()


async def test_list_folders_returns_ids_and_caches_input_peers():
    chan = types.InputPeerChannel(channel_id=1234567, access_hash=11)
    user = types.InputPeerUser(user_id=100, access_hash=22)
    folder = types.DialogFilter(
        id=3,
        title=types.TextWithEntities(text="Work", entities=[]),
        pinned_peers=[user],
        include_peers=[chan],
        exclude_peers=[],
        groups=True,
    )
    client = client_with(FakeTelethon(response=types.messages.DialogFilters(filters=[folder])))
    folders = await client.list_folders()
    assert folders == [FolderInfo(3, "Work", (100, CHAT_ID), True)]
    assert client._input_peers == {100: user, CHAT_ID: chan}


def peer_dialogs_for(request):
    dialogs, messages, users = [], [], []
    for i, dp in enumerate(request.peers):
        uid = dp.peer.user_id
        dialogs.append(
            types.Dialog(
                peer=types.PeerUser(uid),
                top_message=1000 + i,
                read_inbox_max_id=0,
                read_outbox_max_id=0,
                unread_count=uid % 7,
                unread_mentions_count=0,
                unread_reactions_count=0,
                unread_poll_votes_count=0,
                notify_settings=types.PeerNotifySettings(),
            )
        )
        messages.append(mk_msg(types.PeerUser(uid), id=1000 + i))
        users.append(types.User(id=uid, first_name=f"U{uid}"))
    return types.messages.PeerDialogs(dialogs=dialogs, messages=messages, chats=[], users=users, state=None)


class DialogsTelethon(FakeTelethon):
    async def __call__(self, request):
        self.requests.append(request)
        return peer_dialogs_for(request)


async def test_chat_infos_chunks_by_100():
    fake = DialogsTelethon()
    client = client_with(fake)
    ids = list(range(1, 231))
    client._input_peers = {i: types.InputPeerUser(i, 0) for i in ids}
    infos = await client.chat_infos(ids)
    assert [len(r.peers) for r in fake.requests] == [100, 100, 30]
    assert all(isinstance(r, GetPeerDialogsRequest) for r in fake.requests)
    assert len(infos) == 230
    assert infos[0] == ChatInfo(id=1, title="U1", kind="private", link_base=None, unread=1, last_date=DT)


async def test_chat_infos_channel_metadata():
    ch = types.Channel(id=1234567, title="Book club", photo=types.ChatPhotoEmpty(), date=DT, megagroup=True, access_hash=1)
    dialog = types.Dialog(
        peer=types.PeerChannel(1234567),
        top_message=10,
        read_inbox_max_id=0,
        read_outbox_max_id=0,
        unread_count=3,
        unread_mentions_count=0,
        unread_reactions_count=0,
        unread_poll_votes_count=0,
        notify_settings=types.PeerNotifySettings(),
    )
    response = types.messages.PeerDialogs(
        dialogs=[dialog], messages=[message()], chats=[ch], users=[], state=None
    )
    client = client_with(FakeTelethon(response=response))
    client._input_peers = {CHAT_ID: types.InputPeerChannel(1234567, 1)}
    (info,) = await client.chat_infos([CHAT_ID])
    assert info == ChatInfo(
        id=CHAT_ID, title="Book club", kind="group", link_base="https://t.me/c/1234567", unread=3, last_date=DT
    )


async def test_chat_infos_skips_ids_without_cached_peer():
    fake = DialogsTelethon()
    client = client_with(fake)
    client._input_peers = {1: types.InputPeerUser(1, 0)}
    infos = await client.chat_infos([1, 2])
    assert [i.id for i in infos] == [1]
    assert [len(r.peers) for r in fake.requests] == [1]


async def test_chat_infos_empty_sends_nothing():
    fake = DialogsTelethon()
    assert await client_with(fake).chat_infos([]) == []
    assert fake.requests == []


class ParticipantsTelethon(FakeTelethon):
    def __init__(self, users=(), error=None):
        super().__init__()
        self.users = list(users)
        self.error = error
        self.participant_calls = []

    def iter_participants(self, chat_id, **kwargs):
        self.participant_calls.append((chat_id, kwargs))
        error, users = self.error, self.users

        async def gen():
            if error is not None:
                raise error
            for u in users:
                yield u

        return gen()


async def test_resolve_user_matches_username_case_insensitive():
    sam = types.User(id=7, first_name="John", username="Sam_P", access_hash=5)
    fake = ParticipantsTelethon([types.User(id=8, first_name="Joanna", username="samantha"), sam])
    found = await client_with(fake).resolve_user(CHAT_ID, "@sam_p")
    assert utils.get_peer_id(found) == 7
    assert fake.participant_calls == [(CHAT_ID, {"search": "sam_p", "limit": 50})]


async def test_resolve_user_matches_exact_display_name():
    fake = ParticipantsTelethon([types.User(id=7, first_name="John", last_name="Smith", access_hash=1)])
    found = await client_with(fake).resolve_user(CHAT_ID, "John Smith")
    assert utils.get_peer_id(found) == 7


async def test_resolve_user_none_when_not_participant():
    fake = ParticipantsTelethon([types.User(id=8, first_name="Joanna", username="samantha")])
    assert await client_with(fake).resolve_user(CHAT_ID, "@sam") is None
    assert await client_with(ParticipantsTelethon()).resolve_user(CHAT_ID, "John") is None


async def test_resolve_user_ambiguous_name_lists_candidates():
    a = types.User(id=1, first_name="Anna", username="anna_k")
    b = types.User(id=2, first_name="Anna")
    with pytest.raises(InvalidArgument) as exc:
        await client_with(ParticipantsTelethon([a, b])).resolve_user(CHAT_ID, "Anna")
    assert "@anna_k" in str(exc.value) and "Anna" in str(exc.value)


async def test_resolve_user_forbidden_participants_is_not_found():
    fake = ParticipantsTelethon(error=errors.ChatAdminRequiredError(None))
    assert await client_with(fake).resolve_user(CHAT_ID, "@sam") is None


@pytest.mark.parametrize("ref", ["", "   ", "@", "123456789"])
async def test_resolve_user_rejects_empty_and_numeric(ref):
    fake = ParticipantsTelethon()
    with pytest.raises(InvalidArgument):
        await client_with(fake).resolve_user(CHAT_ID, ref)
    assert fake.participant_calls == []


async def test_resolve_user_never_resolves_globally():
    fake = ParticipantsTelethon()
    await client_with(fake).resolve_user(CHAT_ID, "@sam")
    assert fake.entity_args == [] and fake.requests == []


def test_cross_chat_reply_has_no_snippet():
    header = types.MessageReplyHeader(reply_to_msg_id=7, reply_to_peer_id=types.PeerUser(999))
    data = to_message_data(message(reply_to=header), CHAT_ID)
    assert data.reply_to_id is None and data.reply_snippet is None


async def test_connect_sets_account_id_and_guard(monkeypatch):
    class Recorder:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        def is_connected(self):
            return True

        async def get_me(self):
            return types.User(id=42)

    monkeypatch.setattr(tg_module, "TelegramClient", Recorder)
    monkeypatch.setattr(tg_module, "StringSession", lambda s: s)
    monkeypatch.setattr(tg_module.keychain, "get_api_hash", lambda: "hash")
    monkeypatch.setattr(tg_module.keychain, "get_session", lambda: "session")
    client = TgClient(1)
    client.set_allowed(frozenset({100}))
    await client.connect()
    assert client.account_id == 42
    guard = client.client.peer_guard
    assert guard.self_id == 42 and guard.allowed == frozenset({100})
    client.set_allowed(frozenset({200}))
    assert client.client.peer_guard.allowed == frozenset({200})


def test_set_features_sets_extra_requests(monkeypatch):
    from telegram_reader import features

    monkeypatch.setitem(
        features.FEATURES,
        "demo",
        features.Feature("demo", "d", "d", "low", True, requests=("SendMessageRequest",)),
    )
    fake = FakeTelethon()
    client = client_with(fake)
    client.set_features(frozenset({"demo"}))
    assert fake.extra_requests == frozenset({"SendMessageRequest"})


def test_list_dialogs_removed():
    assert not hasattr(TgClient, "list_dialogs")


# --- peerless allowlist, guard denials bubble up -----------------------------

from telethon import TelegramClient as _BaseClient  # noqa: E402
from fakes import real_readonly_client  # noqa: E402
from telethon.tl.functions import channels as channels_fn  # noqa: E402
from telethon.tl.functions import contacts as contacts_fn  # noqa: E402
from telethon.tl.functions import help as help_fn  # noqa: E402
from telethon.tl.functions import messages as messages_fn  # noqa: E402
from telethon.tl.functions import updates as updates_fn  # noqa: E402
from telethon.tl.functions import users as users_fn  # noqa: E402

GUARDED = PeerGuard(allowed=frozenset({100, channel_id(7)}), self_id=42)


@pytest.mark.parametrize(
    "request_obj",
    [
        updates_fn.GetDifferenceRequest(pts=1, date=DT, qts=0),
        messages_fn.GetAllDraftsRequest(),
        contacts_fn.ResolveUsernameRequest(username="someone"),
        contacts_fn.SearchRequest(q="x", limit=1),
        messages_fn.GetPinnedDialogsRequest(folder_id=0),
        messages_fn.GetCommonChatsRequest(user_id=types.InputUser(100, 0), max_id=0, limit=1),
    ],
    ids=lambda r: type(r).__module__.rsplit(".", 1)[-1] + "." + type(r).__name__,
)
def test_guard_refuses_peerless_requests_outside_allowlist(request_obj):
    with pytest.raises(PermissionError, match="refused"):
        GUARDED.check_request(request_obj)


@pytest.mark.parametrize(
    "request_obj",
    [
        users_fn.GetUsersRequest(id=[types.InputUserSelf()]),
        updates_fn.GetStateRequest(),
        help_fn.GetConfigRequest(),
        messages_fn.GetDialogFiltersRequest(),
        messages_fn.GetMessagesRequest(id=[types.InputMessageID(1)]),
    ],
)
def test_guard_allows_peerless_requests_telethon_needs(request_obj):
    # Allowed even before Access fills the whitelist: connect() runs these first.
    PeerGuard(allowed=frozenset(), self_id=None).check_request(request_obj)


def test_guard_checks_user_and_channel_ids_of_allowed_peerless_requests():
    GUARDED.check_request(users_fn.GetUsersRequest(id=[types.InputUser(100, 0)]))
    GUARDED.check_request(users_fn.GetUsersRequest(id=[types.InputPeerUser(100, 0)]))
    GUARDED.check_request(channels_fn.GetChannelsRequest(id=[types.InputChannel(7, 0)]))
    with pytest.raises(PermissionError, match=OUTSIDE):
        GUARDED.check_request(users_fn.GetUsersRequest(id=[types.InputUserSelf(), types.InputUser(200, 0)]))
    with pytest.raises(PermissionError, match=OUTSIDE):
        GUARDED.check_request(channels_fn.GetChannelsRequest(id=[types.InputChannel(8, 0)]))


def test_guard_peerless_feature_request_allowed_by_exact_name():
    req = messages_fn.GetAllDraftsRequest()
    GUARDED.check_request(req, extra=frozenset({"GetAllDraftsRequest"}))
    with pytest.raises(PermissionError):
        GUARDED.check_request(req, extra=frozenset({"SendMessageRequest"}))


def test_guard_filters_new_messages():
    g = PeerGuard(allowed=frozenset({100}), self_id=42)
    state = types.updates.State(pts=1, qts=0, date=DT, seq=0, unread_count=0)
    diff = types.updates.Difference(
        new_messages=[mk_msg(types.PeerUser(100)), mk_msg(types.PeerUser(200))],
        new_encrypted_messages=[],
        other_updates=[],
        chats=[],
        users=[],
        state=state,
    )
    g.filter_response(diff)
    assert [utils.get_peer_id(m.peer_id) for m in diff.new_messages] == [100]


async def test_flood_retry_lets_guard_denial_through():
    with pytest.raises(PermissionError):
        await with_flood_retry(calls(PermissionError("chat 1 is outside the whitelist")), sleep=Sleeper())


async def test_real_tg_client_guard_denial_is_not_network_error(monkeypatch):
    raw, sent = real_readonly_client(monkeypatch, allowed=())
    tg = TgClient(1)
    tg._client = raw
    with pytest.raises(PermissionError, match=OUTSIDE):
        await tg.fetch_messages(100, limit=5)
    with pytest.raises(PermissionError, match=OUTSIDE):
        await tg.search(100, "x", limit=5)
    assert sent == []


async def test_read_only_client_login_hook_skips_get_difference(monkeypatch):
    # Telethon's connect() calls _on_login, which would send GetState + GetDifference
    # (new messages of every chat). The session client never receives updates: skip both.
    import inspect

    assert "_on_login" in inspect.getsource(_BaseClient.connect)
    raw, sent = real_readonly_client(monkeypatch, allowed=())
    me = types.User(id=42, access_hash=1)
    assert await raw._on_login(me) is me
    assert sent == [] and raw._authorized is True and raw._mb_entity_cache.self_id == 42
    assert raw._message_box.is_empty()  # so the update loop never asks for a difference


async def test_resolve_user_ambiguous_names_are_clipped():
    from telegram_reader.format import NAME_MAX
    from telegram_reader.sanitize import clip

    evil = "Anna\u202e\U000e0041" + "я" * 100
    a, b = types.User(id=1, first_name=evil), types.User(id=2, first_name=evil)
    with pytest.raises(InvalidArgument) as exc:
        await client_with(ParticipantsTelethon([a, b])).resolve_user(CHAT_ID, evil)
    text = str(exc.value)
    assert clip(evil, NAME_MAX) in text and "\u202e" not in text and "\U000e0041" not in text


async def test_connect_secret_store_unavailable_is_tool_error(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    def locked():
        raise tg_module.keychain.SecretStoreUnavailable("locked")

    monkeypatch.setattr(tg_module.keychain, "get_api_hash", locked)
    with pytest.raises(ToolError, match="No access to the secret store"):
        await TgClient(1).connect()


async def test_connect_with_stored_but_unauthorized_session_is_session_revoked(monkeypatch):
    from telegram_reader.errors import SessionRevoked

    class Unauthorized:
        def __init__(self, *args, **kwargs):
            self.disconnected = False

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return False

        async def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(tg_module, "TelegramClient", Unauthorized)
    monkeypatch.setattr(tg_module, "StringSession", lambda s: s)
    monkeypatch.setattr(tg_module.keychain, "get_api_hash", lambda: "hash")
    monkeypatch.setattr(tg_module.keychain, "get_session", lambda: "session")
    with pytest.raises(SessionRevoked, match="Login required"):
        await TgClient(1).connect()


async def test_connect_without_secrets_is_plain_login_required(monkeypatch):
    from telegram_reader.errors import SessionRevoked

    monkeypatch.setattr(tg_module.keychain, "get_api_hash", lambda: None)
    monkeypatch.setattr(tg_module.keychain, "get_session", lambda: None)
    with pytest.raises(LoginRequired) as exc:
        await TgClient(1).connect()
    assert not isinstance(exc.value, SessionRevoked)


def test_links_from_entities_with_emoji_offsets():
    text = "🎉 see here and https://a.com"  # emoji = 2 UTF-16 units
    m = message(
        text,
        entities=[types.MessageEntityTextUrl(offset=7, length=4, url="https://b.com"), types.MessageEntityUrl(offset=16, length=13)],
    )
    assert to_message_data(m, CHAT_ID).links == (LinkInfo("https://b.com", "here"), LinkInfo("https://a.com"))


def test_duplicate_links_collapsed():
    urls = [f"https://a.com/{i}" for i in range(25)] + ["https://a.com/0"]
    text = " ".join(urls)
    entities, off = [], 0
    for u in urls:
        entities.append(types.MessageEntityUrl(offset=off, length=len(u)))
        off += len(u) + 1
    links = to_message_data(message(text, entities=entities), CHAT_ID).links
    assert links == tuple(LinkInfo(u) for u in urls[:25])


# --- media_of / download ----------------------------------------------------

from telegram_reader.errors import DownloadFailed  # noqa: E402


class DownloadTelethon(FakeTelethon):
    """get_messages serves `target`; each iter_download call takes the next outcome (chunks or an error)."""

    def __init__(self, target, outcomes):
        super().__init__(by_id={10: target})
        self.outcomes = list(outcomes)
        self.fetches = 0
        self.downloaded = []

    async def get_messages(self, chat_id, ids):
        self.fetches += 1
        return await super().get_messages(chat_id, ids)

    def iter_download(self, file, **kwargs):
        self.downloaded.append((file, kwargs))
        outcome = self.outcomes.pop(0)

        async def gen():
            if isinstance(outcome, Exception):
                raise outcome
            for chunk in outcome:
                if isinstance(chunk, Exception):
                    raise chunk  # fails mid-stream, after some bytes were written
                yield chunk

        return gen()


def doc_message():
    doc = _doc([types.DocumentAttributeFilename("a.pdf")], size=2)
    return message(text="", media=types.MessageMediaDocument(document=doc))


def download_client(target, outcomes):
    fake = DownloadTelethon(target, outcomes)
    client = client_with(fake)
    client._allowed = frozenset({CHAT_ID})
    return client, fake


async def test_media_of_returns_media_info():
    client, _ = download_client(doc_message(), [])
    assert await client.media_of(CHAT_ID, 10) == MediaInfo("document", name="a.pdf", mime="application/pdf", size=2)


@pytest.mark.parametrize(
    "target",
    [
        None,
        message("just text"),
        message("", media=types.MessageMediaGeo(geo=types.GeoPointEmpty())),
        message("", media=types.MessageMediaPhoto(photo=types.PhotoEmpty(id=1))),
    ],
)
async def test_media_of_without_file_refused(target):
    client, _ = download_client(target, [])
    with pytest.raises(InvalidArgument, match="Message #10 has no file"):
        await client.media_of(CHAT_ID, 10)


async def test_media_of_message_from_other_chat_refused():
    other = types.Message(id=10, peer_id=types.PeerUser(5), date=DT, message="", media=doc_message().media)
    client, _ = download_client(other, [])
    with pytest.raises(InvalidArgument, match="has no file"):
        await client.media_of(CHAT_ID, 10)


async def test_download_outside_whitelist_is_permission_error(tmp_path):
    client, fake = download_client(doc_message(), [[b"ok"]])
    client._allowed = frozenset()
    with pytest.raises(PermissionError):
        await client.download(CHAT_ID, 10, tmp_path / "f", 100)
    with pytest.raises(PermissionError):
        await client.media_of(CHAT_ID, 10)
    assert fake.fetches == 0 and fake.downloaded == []


async def test_download_writes_chunks(tmp_path):
    client, fake = download_client(doc_message(), [[b"ab", b"cd"]])
    dest = tmp_path / "f"
    assert await client.download(CHAT_ID, 10, dest, 100) == 4
    assert dest.read_bytes() == b"abcd"
    assert fake.downloaded[0][0] is fake.by_id[10].media.document


async def test_download_photo_uses_largest_size(tmp_path):
    photo = types.Photo(
        id=1,
        access_hash=2,
        file_reference=b"ref",
        date=DT,
        dc_id=4,
        sizes=[
            types.PhotoSize(type="y", w=1280, h=960, size=300),
            types.PhotoSize(type="m", w=320, h=240, size=30),
            types.PhotoStrippedSize(type="i", bytes=b"x"),
        ],
    )
    client, fake = download_client(message("", media=types.MessageMediaPhoto(photo=photo)), [[b"jpg"]])
    await client.download(CHAT_ID, 10, tmp_path / "f", 100)
    location, kwargs = fake.downloaded[0]
    assert location == types.InputPhotoFileLocation(id=1, access_hash=2, file_reference=b"ref", thumb_size="y")
    assert kwargs["dc_id"] == 4


async def test_download_retries_once_on_expired_file_reference(tmp_path):
    expired = errors.FileReferenceExpiredError(None)
    client, fake = download_client(doc_message(), [[b"stale", expired], [b"ok"]])
    dest = tmp_path / "f"
    assert await client.download(CHAT_ID, 10, dest, 100) == 2
    assert fake.fetches == 2 and dest.read_bytes() == b"ok"


async def test_download_expired_twice_gives_up(tmp_path):
    expired = errors.FileReferenceExpiredError(None)
    client, fake = download_client(doc_message(), [expired, expired, [b"never"]])
    with pytest.raises(errors.FileReferenceExpiredError):
        await client.download(CHAT_ID, 10, tmp_path / "f", 100)
    assert fake.fetches == 2


async def test_download_enforces_max_bytes_while_streaming(tmp_path):
    client, _ = download_client(doc_message(), [[b"12345", b"67890"]])
    with pytest.raises(InvalidArgument, match="exceeds the"):
        await client.download(CHAT_ID, 10, tmp_path / "f", 8)


async def test_download_disk_error_is_download_failed_not_network(tmp_path):
    client, _ = download_client(doc_message(), [[b"ok"]])
    with pytest.raises(DownloadFailed, match="Could not write the file: ") as exc:
        await client.download(CHAT_ID, 10, tmp_path / "missing-dir" / "f", 100)
    assert not isinstance(exc.value, NetworkError)


async def test_download_network_error_still_network_error(tmp_path):
    client, _ = download_client(doc_message(), [ConnectionError("down")])
    with pytest.raises(NetworkError):
        await client.download(CHAT_ID, 10, tmp_path / "f", 100)


# --- search filters (list_files / list_links) --------------------------------


async def test_search_filter_passed_to_iter_messages():
    fake = FakeTelethon([message(text="report")])
    await client_with(fake).search(CHAT_ID, limit=5, filter="documents")
    (kwargs,) = fake.iter_kwargs
    assert isinstance(kwargs["filter"], types.InputMessagesFilterDocument)
    assert kwargs["search"] == ""


async def test_search_without_filter_passes_none():
    fake = FakeTelethon([message(text="report")])
    await client_with(fake).search(CHAT_ID, "report", limit=5)
    assert fake.iter_kwargs[0]["filter"] is None


async def test_topic_search_uses_filter():
    response = types.messages.Messages(messages=[message(text="https://a.com")], topics=[], chats=[], users=[])
    fake = FakeTelethon(response=response)
    await client_with(fake).search(CHAT_ID, limit=5, topic=7, filter="url")
    (request,) = fake.requests
    assert isinstance(request.filter, types.InputMessagesFilterUrl) and request.q == ""


async def test_topic_search_without_filter_is_empty_filter():
    response = types.messages.Messages(messages=[], topics=[], chats=[], users=[])
    fake = FakeTelethon(response=response)
    await client_with(fake).search(CHAT_ID, "x", limit=5, topic=7)
    assert isinstance(fake.requests[0].filter, types.InputMessagesFilterEmpty)


@pytest.mark.parametrize(
    "name,cls",
    [
        ("documents", types.InputMessagesFilterDocument),
        ("photos", types.InputMessagesFilterPhotos),
        ("videos", types.InputMessagesFilterVideo),
        ("photo_video", types.InputMessagesFilterPhotoVideo),
        ("voice", types.InputMessagesFilterVoice),
        ("url", types.InputMessagesFilterUrl),
    ],
)
async def test_search_filter_map(name, cls):
    fake = FakeTelethon([])
    await client_with(fake).search(CHAT_ID, limit=5, filter=name)
    assert isinstance(fake.iter_kwargs[0]["filter"], cls)


async def test_topic_search_drops_messages_outside_period():
    newer = message(text="https://new.com")
    newer.date = datetime(2026, 10, 20, tzinfo=UTC)
    inside = message(text="https://in.com")
    older = message(text="https://old.com")
    older.date = datetime(2026, 10, 1, tzinfo=UTC)
    response = types.messages.Messages(messages=[newer, inside, older], topics=[], chats=[], users=[])
    fake = FakeTelethon(response=[response])
    result = await client_with(fake).search(
        CHAT_ID,
        limit=5,
        topic=7,
        filter="url",
        since=datetime(2026, 10, 10, tzinfo=UTC),
        until=datetime(2026, 10, 15, tzinfo=UTC),
    )
    assert [m.text for m in result] == ["https://in.com"]
    assert len(fake.requests) == 1
