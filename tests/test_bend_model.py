"""Differential tests: the Bend models in proofs/model against the real Python code.

proofs/PROOF.bend proves the security laws about the models. These tests are what ties a model
to the code it stands for: Hypothesis generates inputs, the real code (Access, ensure_read_only,
PeerGuard, ReadOnlyTelegramClient._call, allowed_requests, clean, clip) decides, the model decides
on the same input through the binary built from proofs/harness/main.bend, and any difference
fails the test with a minimal example.

Every generator builds the abstract input (what the model sees) and the concrete one (real
Telethon objects, real ChatInfo) side by side, so the abstraction is by construction and does
not reuse the code under test. The line format is described in proofs/harness/main.bend.

Without `bend` on the machine the module is skipped; under CI that is an error.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeStore, FakeTg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from telethon import TelegramClient as TelethonClient
from telethon import types, utils
from telethon.sessions import StringSession
from telethon.tl import functions as fn

from telegram_reader import features as features_mod
from telegram_reader import tg as tg_mod
from telegram_reader.access import FOLDER_TTL_SECONDS, Access
from telegram_reader.config import Config, FolderRef
from telegram_reader.errors import AccessDenied, AccountMismatch, AmbiguousChat, NetworkError
from telegram_reader.features import Feature, allowed_requests
from telegram_reader.models import ChatInfo, FolderInfo
from telegram_reader.sanitize import HIDDEN_MARK, clean, clip
from telegram_reader.tg import DOWNLOAD_REQUESTS, PeerGuard, ReadOnlyTelegramClient, ensure_read_only

ROOT = Path(__file__).parent.parent
HARNESS = ROOT / "proofs" / "harness" / "main.bend"
EXAMPLES = 500

check = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


# The model binary
# ----------------


def _find_bend() -> str | None:
    found = shutil.which("bend")
    if found:
        return found
    home = Path(os.environ.get("BEND_HOME", Path.home() / ".bend")) / "bin" / "bend"
    return str(home) if home.exists() else None


class Model:
    """The harness process: one request line in, one answer line out."""

    def __init__(self, binary: Path):
        self._proc = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8"
        )

    def ask(self, *fields: Any) -> str:
        line = "|".join(str(f) for f in fields)
        assert "\n" not in line
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        answer = self._proc.stdout.readline()
        assert answer.endswith("\n"), f"the model binary stopped answering at: {line}"
        return answer.rstrip("\n")

    def close(self) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.close()
        self._proc.wait(timeout=10)


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    bend = _find_bend()
    if bend is None:
        if os.environ.get("CI"):
            pytest.fail("bend is not installed; under CI the model tests may not be skipped")
        pytest.skip("bend is not installed (https://bend-lang.com)")
    binary = tmp_path_factory.mktemp("bend") / "harness"
    env = {**os.environ, "BEND_NO_TELEMETRY": "1"}
    built = subprocess.run([bend, str(HARNESS), "-o", str(binary)], capture_output=True, text=True, env=env)
    assert built.returncode == 0 and binary.exists(), f"building the harness failed:\n{built.stdout}\n{built.stderr}"
    m = Model(binary)
    yield m
    m.close()


def nats(xs) -> str:
    return " ".join(str(x) for x in xs)


def opt(x: int | None) -> int:
    """None is 0, n is n + 1."""
    return 0 if x is None else x + 1


def run(coro):
    return asyncio.run(coro)


# A. access.py
# ============

# Real chat ids; a chat id in the model is the index here. Unknown ids get one index past the end.
IDS = [1, 2, 77, 2026, -5, -1001234567, 100, 0]
# Normalized titles (what access._norm returns); a title in the model is the index here. Some look
# like numbers, some are the decimal form of an id above: a chat named "2026", a chat named "77".
TITLES = ["club", "example group", "2026", "77", "-5", "a b", "1", "straße"]
UNKNOWN_ID = len(IDS)
UNKNOWN_TITLE = len(TITLES)


@st.composite
def spelling(draw, title: str) -> str:
    """A string access._norm maps to `title`: other case, other whitespace."""
    words = [draw(st.sampled_from([w, w.upper(), w.capitalize()])) for w in title.split()]
    gap = st.sampled_from([" ", "  ", "\t", " \n "])
    text = words[0]
    for w in words[1:]:
        text += draw(gap) + w
    edge = st.sampled_from(["", " ", "\t", "  "])
    return draw(edge) + text + draw(edge)


@st.composite
def whitelists(draw) -> list[tuple[ChatInfo, int, int]]:
    """Chats with distinct ids (Access keeps them in a dict), as (real chat, id index, title index)."""
    ids = draw(st.lists(st.sampled_from(range(len(IDS))), unique=True, max_size=6))
    out = []
    for i in ids:
        t = draw(st.sampled_from(range(len(TITLES))))
        out.append((ChatInfo(id=IDS[i], title=draw(spelling(TITLES[t])), kind="group", link_base=None), i, t))
    return out


def _index(value, pool, unknown):
    return pool.index(value) if value in pool else unknown


@st.composite
def refs(draw) -> tuple[str | int, str]:
    """A chat reference as a tool passes it, and the same in the model: kind:id:title."""
    kind = draw(st.sampled_from(["int", "title", "number"]))
    if kind == "int":
        n = draw(st.sampled_from([*IDS, 999, -77]))
        return n, f"0:{_index(n, IDS, UNKNOWN_ID)}:0"
    if kind == "title":
        t = draw(st.sampled_from(range(len(TITLES))))
        text = draw(spelling(TITLES[t]))
    else:
        n = draw(st.sampled_from([*IDS, 999, -77]))
        t = _index(str(n), TITLES, UNKNOWN_TITLE)
        edge = st.sampled_from(["", " ", "\t"])
        text = draw(edge) + str(n) + draw(edge)
    digits = text.strip().removeprefix("-")
    if digits.isascii() and digits.isdigit():
        return text, f"2:{_index(int(text), IDS, UNKNOWN_ID)}:{t}"
    return text, f"1:0:{t}"


def chats_field(chats) -> str:
    return " ".join(f"{i}:{t}" for _, i, t in chats)


def found(info: ChatInfo, chats) -> str:
    (hit,) = [(i, t) for c, i, t in chats if c is info]
    return f"F {hit[0]}:{hit[1]}"


async def python_resolve(access: Access, ref, chats) -> str:
    try:
        return found(await access.resolve(ref), chats)
    except AccessDenied:
        return "D"
    except AmbiguousChat:
        return "A"
    except AccountMismatch:
        return "M"
    except NetworkError:
        return "E"


def make_access(chats, peers, account=1):
    tg = FakeTg(dialogs=[c for c, _, _ in chats], folders=[FolderInfo(3, "Work", tuple(peers), False)])
    store = FakeStore(Config(api_id=1, account_id=account, folders=(FolderRef(3, "f3"),)))
    clock = Clock()
    return Access(tg, store, clock=clock), tg, store, clock


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@check
@given(chats=whitelists(), ref=refs())
def test_resolve_matches_the_model(model, chats, ref):
    """A1-A4: Access.resolve (through the real _match) against the model's resolve."""
    real_ref, model_ref = ref
    access, _, _, _ = make_access(chats, [c.id for c, _, _ in chats])
    python = run(python_resolve(access, real_ref, chats))
    assert model.ask(1, model_ref, chats_field(chats)) == python


@dataclass
class Step:
    new_config: bool  # the store hands out another Config object
    config_account: int | None
    session_account: int | None
    wait: bool  # FOLDER_TTL_SECONDS pass before the call
    folders_fail: bool  # Telegram raises while listing folders
    peers: list[int]  # indexes into IDS: what the selected folder holds
    ref: tuple[str | int, str]


ACCOUNTS = st.sampled_from([1, 1, 1, 2, None])
steps = st.builds(
    Step,
    new_config=st.booleans(),
    config_account=ACCOUNTS,
    session_account=ACCOUNTS,
    wait=st.booleans(),
    folders_fail=st.booleans(),
    peers=st.lists(st.sampled_from(range(len(IDS))), unique=True, max_size=5),
    ref=refs(),
)


@check
@given(chats=whitelists(), script=st.lists(steps, min_size=1, max_size=6))
def test_whitelist_state_matches_the_model(model, chats, script):
    """A5, A6: a sequence of Access.resolve calls with refreshes that succeed, fail or hit another
    account, against the model's state machine: the answer, Access._allowed, the ids given to the
    PeerGuard and whether the cache is valid, after every call."""
    by_id = {c.id: (i, t) for c, i, t in chats}
    access, tg, store, clock = make_access(chats, [], account=script[0].config_account)
    python, calls = [], []
    account = script[0].config_account
    for n, step in enumerate(script):
        new_config = step.new_config or n == 0
        if new_config:
            account = step.config_account
            store.cfg = Config(api_id=1, account_id=account, folders=(FolderRef(3, "f3"),))
        if step.wait:
            clock.now += FOLDER_TTL_SECONDS
        tg.account_id = step.session_account
        tg.folders_error = NetworkError() if step.folders_fail else None
        tg.folders = [FolderInfo(3, "Work", tuple(IDS[i] for i in step.peers), False)]

        answer = run(python_resolve(access, step.ref[0], chats))
        python.append(
            (
                answer,
                access._refreshed_at is not None,
                {IDS.index(i) for i in tg.allowed},
                {by_id[c.id] for c in access._allowed.values()},
            )
        )
        known = [(i, t) for c, i, t in chats if i in step.peers]
        calls.append(
            ",".join(
                [
                    str(int(not new_config and not step.wait)),
                    str(opt(account)),
                    str(opt(step.session_account)),
                    str(int(not step.folders_fail)),
                    nats(step.peers),
                    " ".join(f"{i}:{t}" for i, t in known),
                    step.ref[1],
                ]
            )
        )

    answers = model.ask(2, ";".join(calls)).split(";")
    assert len(answers) == len(python)
    for line, (answer, valid, guard, allowed) in zip(answers, python, strict=True):
        m_answer, m_valid, m_guard, m_allowed = line.split(",")
        assert m_answer == answer
        assert m_valid == str(int(valid))
        assert {int(x) for x in m_guard.split()} == guard
        assert {tuple(int(x) for x in c.split(":")) for c in m_allowed.split()} == allowed


# B. tg.py and features.py
# ========================

# Request class names the generated features may allow; the index is the name in the model.
FEATURE_KEYS = ["write", "reactions", "drafts"]
GRANTABLE = ["SendMessageRequest", "GetAllDraftsRequest", "GetDifferenceRequest", "DeleteMessagesRequest"]


@st.composite
def registries(draw) -> dict[str, Feature]:
    reg = {}
    for key in draw(st.lists(st.sampled_from(FEATURE_KEYS), unique=True)):
        reg[key] = Feature(
            key=key,
            title=key,
            description="",
            risk="high",
            available=draw(st.booleans()),
            requests=tuple(draw(st.lists(st.sampled_from(GRANTABLE), unique=True))),
        )
    return reg


enabled_keys = st.lists(st.sampled_from([*FEATURE_KEYS, "unknown"]), unique=True)


class Names:
    """Numbers request class names and feature keys as the model wants them."""

    def __init__(self):
        self._ids: dict[str, int] = {}

    def __call__(self, name: str) -> int:
        return self._ids.setdefault(name, len(self._ids))


def registry_field(reg: dict[str, Feature], names: Names) -> str:
    return ";".join(
        f"{names('key:' + f.key)},{int(f.available)},{nats(names(r) for r in f.requests)}" for f in reg.values()
    )


def enabled_field(enabled, names: Names) -> str:
    return nats(names("key:" + k) for k in enabled)


@check
@given(reg=registries(), enabled=enabled_keys)
def test_allowed_requests_matches_the_model(model, monkeypatch, reg, enabled):
    """B2: features.allowed_requests over a generated registry against the model's."""
    names = Names()
    with monkeypatch.context() as patch:
        patch.setattr(features_mod, "FEATURES", reg)
        python = {names(r) for r in allowed_requests(frozenset(enabled))}
    answer = model.ask(3, registry_field(reg, names), enabled_field(enabled, names))
    assert {int(x) for x in answer.split()} == python


def test_model_registry_is_the_shipped_one(model):
    """model/features.bend hard-codes FEATURES for law b2_shipped_registry_adds_nothing."""
    keys = {"write": 0}  # the key numbers used by registry() in the model
    shipped = sorted((keys[f.key], int(f.available), len(f.requests)) for f in features_mod.FEATURES.values())
    modelled = []
    for item in model.ask(0).split(";"):
        key, available, requests = item.split(",")
        modelled.append((int(key), int(available), len(requests.split())))
    assert sorted(modelled) == shipped


# Peers the generated requests point at; a peer id in the model is the index here.
PEERS = [("user", 100), ("user", 200), ("user", 42), ("chat", 5), ("chat", 6), ("channel", 7), ("channel", 8)]
SELF = 2  # the account itself, when the guard knows it


def peer_id(index: int) -> int:
    kind, raw = PEERS[index]
    if kind == "user":
        return raw
    if kind == "chat":
        return -raw
    return utils.get_peer_id(types.PeerChannel(raw))


def input_peer(index: int):
    kind, raw = PEERS[index]
    if kind == "user":
        return types.InputPeerUser(raw, 0)
    if kind == "chat":
        return types.InputPeerChat(raw)
    return types.InputPeerChannel(raw, 0)


# What the model calls a peer: 0 cannot be verified, 1 InputUserSelf, 2 InputPeerSelf, n + 3 PEERS[n].
BAD, USER_SELF, PEER_SELF = 0, 1, 2


@st.composite
def peers(draw, *, dialog: bool = False) -> tuple[Any, int]:
    """A value for a peer field, and the model's peer."""
    kind = draw(st.sampled_from(["id", "id", "id", "raw", "self", "user_self", "bad"]))
    if kind == "id":
        i = draw(st.sampled_from(range(len(PEERS))))
        value = input_peer(i)
        if PEERS[i][0] == "channel" and draw(st.booleans()):
            value = types.InputChannel(PEERS[i][1], 0)
        if PEERS[i][0] == "user" and draw(st.booleans()):
            value = types.InputUser(PEERS[i][1], 0)
        code = i + 3
    elif kind == "raw":
        i = draw(st.sampled_from(range(len(PEERS))))
        value, code = peer_id(i), i + 3  # an int is taken as a marked peer id
    elif kind == "self":
        value, code = types.InputPeerSelf(), PEER_SELF
    elif kind == "user_self":
        value, code = types.InputUserSelf(), USER_SELF
    else:
        value, code = draw(st.sampled_from(["someone", types.InputPeerEmpty()])), BAD
    if dialog:
        if code == BAD and draw(st.booleans()):
            return types.InputDialogPeerFolder(folder_id=1), BAD
        if not isinstance(value, (int, str)):
            value = types.InputDialogPeer(value)
    return value, code


@dataclass
class Request:
    obj: Any
    fields: list[list[int]]  # one list of model peers per peer field that is not None
    ids: list[int] | None = None  # the `id` list of an _ID_PEERS request


def _one(build):
    """A request with one peer field holding one peer."""
    return peers().map(lambda p: Request(build(p[0]), [[p[1]]]))


chat_ids = st.sampled_from([i for i, (kind, _) in enumerate(PEERS) if kind == "chat"])


@st.composite
def requests(draw) -> Request:
    kind = draw(
        st.sampled_from(
            [
                "history", "search", "send", "read", "views", "peer_dialogs", "full_channel",
                "channel_messages", "full_chat", "two_fields", "users", "channels", "peerless",
            ]
        )
    )  # fmt: skip
    if kind == "history":
        return draw(_one(lambda p: fn.messages.GetHistoryRequest(p, 0, None, 0, 10, 0, 0, 0)))
    if kind == "search":
        author = draw(peers())[0]  # from_id is not a peer field: never checked
        return draw(
            _one(
                lambda p: fn.messages.SearchRequest(
                    p, "q", types.InputMessagesFilterEmpty(), None, None, 0, 0, 10, 0, 0, 0, from_id=author
                )
            )
        )
    if kind == "send":
        return draw(_one(lambda p: fn.messages.SendMessageRequest(p, "hi")))
    if kind == "read":
        return draw(_one(lambda p: fn.messages.ReadHistoryRequest(p, 0)))
    if kind == "views":
        return draw(_one(lambda p: fn.messages.GetMessagesViewsRequest(p, [1], increment=False)))
    if kind == "peer_dialogs":
        items = draw(st.lists(peers(dialog=True), max_size=3))
        return Request(fn.messages.GetPeerDialogsRequest(peers=[v for v, _ in items]), [[c for _, c in items]])
    if kind == "full_channel":
        return draw(_one(lambda p: fn.channels.GetFullChannelRequest(channel=p)))
    if kind == "channel_messages":
        return draw(_one(lambda p: fn.channels.GetMessagesRequest(channel=p, id=[1, 2])))
    if kind == "full_chat":
        i = draw(chat_ids)
        return Request(fn.messages.GetFullChatRequest(chat_id=PEERS[i][1]), [[i + 3]])
    if kind == "two_fields":
        # No Telegram request has both; the guard looks at every peer field all the same.
        (a, ca), (b, cb) = draw(peers()), draw(peers())
        obj = fn.messages.GetHistoryRequest(a, 0, None, 0, 10, 0, 0, 0)
        obj.channel = b
        return Request(obj, [[ca], [cb]])
    if kind in ("users", "channels"):
        # InputUserSelf is the one item the guard skips; put it next to items it must still check.
        me = st.builds(lambda: (types.InputUserSelf(), USER_SELF))
        items = draw(st.lists(st.one_of(peers(), me), max_size=3))
        build = fn.users.GetUsersRequest if kind == "users" else fn.channels.GetChannelsRequest
        return Request(build(id=[v for v, _ in items]), [], [c for _, c in items])
    return Request(
        draw(
            st.sampled_from(
                [
                    fn.updates.GetStateRequest(),
                    fn.help.GetConfigRequest(),
                    fn.help.GetCdnConfigRequest(),
                    fn.messages.GetMessagesRequest(id=[types.InputMessageID(1)]),
                    fn.messages.GetDialogFiltersRequest(),
                    fn.upload.GetFileRequest(types.InputDocumentFileLocation(1, 2, b"", ""), 0, 4096),
                    fn.upload.ReuploadCdnFileRequest(b"", b""),
                    fn.auth.ExportAuthorizationRequest(dc_id=2),
                    fn.updates.GetDifferenceRequest(pts=1, date=None, qts=1),
                    fn.messages.GetAllDraftsRequest(),
                    fn.messages.DeleteMessagesRequest(id=[1]),
                    fn.messages.GetDialogsRequest(None, 0, types.InputPeerEmpty(), 10, 0),
                    fn.messages.SearchGlobalRequest(
                        "q", types.InputMessagesFilterEmpty(), None, None, 0, types.InputPeerEmpty(), 0, 10
                    ),
                    fn.messages.GetPinnedDialogsRequest(folder_id=0),
                    fn.contacts.ResolveUsernameRequest("someone"),
                    fn.contacts.GetContactsRequest(hash=0),
                    fn.account.CheckUsernameRequest("someone"),
                    fn.messages.CheckChatInviteRequest("hash"),
                ]
            )
        ),
        [],
    )


def request_field(r: Request, names: Names) -> str:
    """name,reads,denied,fields,kind,ids: what the guards read off a request, by the constants in tg.py."""
    name = type(r.obj).__name__
    qualified = f"{type(r.obj).__module__.rsplit('.', 1)[-1]}.{name}"
    if qualified in tg_mod._ID_PEERS:
        kind = 2
    elif qualified in tg_mod._PEERLESS_ALLOWED:
        kind = 1
    else:
        kind = 0
    assert (r.ids is not None) == (kind == 2)
    return ",".join(
        [
            str(names(name)),
            str(int(name.startswith(tg_mod._READ_PREFIXES))),
            str(int(name in tg_mod._DENIED_READS)),
            "/".join("f " + nats(f) for f in r.fields),
            str(kind),
            nats(r.ids or []),
        ]
    )


def refused(call) -> bool:
    try:
        call()
    except PermissionError:
        return True
    return False


@st.composite
def guards(draw) -> tuple[PeerGuard, str]:
    # Mostly generous whitelists: with a random one nearly every batch is refused for many reasons at
    # once, and a guard that forgets one of them goes unnoticed.
    everyone = list(range(len(PEERS)))
    allowed = draw(
        st.one_of(
            st.just(everyone),
            st.sampled_from(everyone).map(lambda out: [i for i in everyone if i != out]),
            st.lists(st.sampled_from(everyone), unique=True),
        )
    )
    knows_self = draw(st.sampled_from([True, True, False]))
    guard = PeerGuard(
        allowed=frozenset(peer_id(i) for i in allowed), self_id=peer_id(SELF) if knows_self else None
    )
    return guard, f"{nats(allowed)},{opt(SELF if knows_self else None)}"


@pytest.fixture
def client(monkeypatch):
    """A real ReadOnlyTelegramClient on its own event loop; a request that gets past the guards
    reaches `network`, which stands in for Telethon's sender."""
    loop = asyncio.new_event_loop()

    class ReachedNetwork(Exception):
        pass

    async def network(self, sender, request, ordered=False, flood_sleep_threshold=None):
        raise ReachedNetwork

    monkeypatch.setattr(TelethonClient, "_call", network)

    async def make():
        return ReadOnlyTelegramClient(StringSession(), 1, "0" * 32, receive_updates=False)

    real = loop.run_until_complete(make())

    def passes(request) -> bool:
        try:
            loop.run_until_complete(real._call(None, request))
        except ReachedNetwork:
            return True
        except PermissionError:
            return False
        raise AssertionError("the patched network returned")

    yield real, passes
    loop.close()


@check
@given(
    reg=registries(),
    enabled=enabled_keys,
    guard=guards(),
    batch=st.one_of(st.lists(requests(), min_size=1, max_size=1), st.lists(requests(), min_size=2, max_size=3)),
)
def test_guards_match_the_model(model, monkeypatch, client, reg, enabled, guard, batch):
    """B1, B3, B4, B5: ensure_read_only, PeerGuard.check_request and the two together as
    ReadOnlyTelegramClient._call runs them, on batches of real Telethon requests."""
    real_guard, model_guard = guard
    real_client, passes = client
    names = Names()
    with monkeypatch.context() as patch:
        patch.setattr(features_mod, "FEATURES", reg)
        from_features = allowed_requests(frozenset(enabled))
    extra = from_features | DOWNLOAD_REQUESTS  # as ReadOnlyTelegramClient._call builds it
    objs = [r.obj for r in batch]
    request = objs[0] if len(objs) == 1 else objs

    real_client.peer_guard = real_guard
    real_client.extra_requests = from_features
    python = (
        not refused(lambda: ensure_read_only(request, extra)),
        not refused(lambda: real_guard.check_request(request, extra)),
        passes(request),
    )
    answer = model.ask(
        4,
        registry_field(reg, names),
        enabled_field(enabled, names),
        nats(names(n) for n in sorted(DOWNLOAD_REQUESTS)),
        model_guard,
        ";".join(request_field(r, names) for r in batch),
    )
    assert answer == " ".join(str(int(b)) for b in python)


@check
@given(guard=guards(), batch=st.lists(requests(), min_size=1, max_size=3))
def test_a_tuple_is_a_batch_too(guard, batch):
    """B5: _requests treats a tuple like a list. No model here: both spellings must agree."""
    real_guard, _ = guard
    objs = [r.obj for r in batch]
    assert refused(lambda: ensure_read_only(tuple(objs))) == refused(lambda: ensure_read_only(objs))
    assert refused(lambda: real_guard.check_request(tuple(objs))) == refused(lambda: real_guard.check_request(objs))


# What the model calls a message: 0 no peer_id, 1 a peer_id that is no peer, n + 2 a message of PEERS[n].
@st.composite
def messages(draw) -> tuple[Any, int]:
    kind = draw(st.sampled_from(["chat", "chat", "chat", "none", "odd"]))
    if kind == "none":
        return types.MessageEmpty(id=1, peer_id=None), 0
    if kind == "odd":
        return types.Message(id=1, peer_id=draw(st.sampled_from(["junk", types.InputPeerEmpty()]))), 1
    i = draw(st.sampled_from(range(len(PEERS))))
    name, raw = PEERS[i]
    peer = {"user": types.PeerUser, "chat": types.PeerChat, "channel": types.PeerChannel}[name](raw)
    made = types.MessageService(id=1, peer_id=peer) if draw(st.booleans()) else types.Message(id=1, peer_id=peer)
    return made, i + 2


@st.composite
def responses(draw) -> tuple[Any, list[tuple[Any, int]]]:
    """What a request returns, and its messages in the order filter_response walks them."""
    parts, flat = [], []
    for _ in range(draw(st.integers(0, 3))):
        msgs = draw(st.lists(messages(), max_size=4))
        shape = draw(st.sampled_from(["messages", "difference", "other"]))
        if shape == "messages":
            parts.append(types.messages.Messages(messages=[m for m, _ in msgs], chats=[], users=[], topics=[]))
            flat += msgs
        elif shape == "difference":
            more = draw(st.lists(messages(), max_size=3))
            obj = types.updates.Difference(
                new_messages=[m for m, _ in msgs], new_encrypted_messages=[], other_updates=[], chats=[], users=[],
                state=None,
            )  # fmt: skip
            obj.messages = [m for m, _ in more]  # filter_response reads `messages` first
            parts.append(obj)
            flat += more + msgs
        else:
            parts.append(types.User(id=1))
    if len(parts) == 1 and draw(st.booleans()):
        return parts[0], flat
    return parts, flat


@check
@given(guard=guards(), response=responses())
def test_filter_response_matches_the_model(model, guard, response):
    """B6: PeerGuard.filter_response on real Telethon results against the model's filter."""
    real_guard, model_guard = guard
    result, flat = response
    codes = {id(m): c for m, c in flat}
    real_guard.filter_response(result)
    left = []
    for r in result if isinstance(result, list) else [result]:
        for attr in ("messages", "new_messages"):
            left += [codes[id(m)] for m in getattr(r, attr, None) or []]
    answer = model.ask(5, model_guard, nats(c for _, c in flat))
    assert [int(x) for x in answer.split()] == left


# C. sanitize.py
# ==============

PLAIN, HIDDEN, SPACE, DOTS, MARK = range(5)
ALPHABET = {
    PLAIN: "aБ7.]",
    HIDDEN: "​‌⁠﻿‮⁦\U000e0041",
    SPACE: " \t\n ",
}
texts = st.lists(
    st.sampled_from([(ch, cls) for cls, chars in ALPHABET.items() for ch in chars]), max_size=14
).map(lambda xs: ("".join(ch for ch, _ in xs), [cls for _, cls in xs]))


def classes(out: str) -> list[int]:
    """The output of clean/clip in the model's alphabet."""
    tail = []
    if out.endswith(" " + HIDDEN_MARK):
        out, tail = out[: -len(HIDDEN_MARK) - 1], [SPACE, MARK]
    body = []
    for ch in out:
        if ch == "…":
            body.append(DOTS)
        elif ch.isspace():
            body.append(SPACE)
        else:
            body.append(HIDDEN if ch in ALPHABET[HIDDEN] else PLAIN)
    return body + tail


@check
@given(text=texts, limit=st.integers(-2, 16))
def test_clip_matches_the_model(model, text, limit):
    """C1-C3: sanitize.clip against the model's clip. A limit below 0 is 0 in the model."""
    raw, syms = text
    assert [int(x) for x in model.ask(6, max(limit, 0), nats(syms)).split()] == classes(clip(raw, limit))


@check
@given(text=texts)
def test_clean_matches_the_model(model, text):
    """C2, C3: sanitize.clean against the model's clean."""
    raw, syms = text
    assert [int(x) for x in model.ask(7, nats(syms)).split()] == classes(clean(raw))
