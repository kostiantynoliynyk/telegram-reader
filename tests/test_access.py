import logging
from datetime import UTC, datetime

import pytest
from fakes import FakeStore, FakeTg

from telegram_reader.access import FOLDER_TTL_SECONDS, Access
from telegram_reader.config import Config, FolderRef
from telegram_reader.errors import AccessDenied, AccountMismatch, AmbiguousChat, NetworkError
from telegram_reader.models import ChatInfo, FolderInfo, TopicInfo


def chat(id, title, kind="group"):
    return ChatInfo(id=id, title=title, kind=kind, link_base=None)


A, B, C, D = chat(1, "A"), chat(2, "B"), chat(3, "C"), chat(4, "D")
CORE = chat(-1001234567, "Example group")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def cfg_for(*folder_ids, account_id=1, **kw):
    return Config(
        api_id=1, account_id=account_id, folders=tuple(FolderRef(i, f"f{i}") for i in folder_ids), **kw
    )


def make(dialogs, tg_folders=(), selected=(3,), topics=None, **cfg):
    tg = FakeTg(dialogs=list(dialogs), folders=list(tg_folders), topics=topics)
    store = FakeStore(cfg_for(*selected, **cfg))
    clock = Clock()
    return Access(tg, store, clock=clock), tg, clock, store


def folder(id, peers, title="Work", auto=False):
    return FolderInfo(id, title, tuple(peers), auto)


async def ids(access):
    return {c.id for c in await access.allowed_chats()}


async def test_only_selected_folders_by_id():
    access, tg, _, _ = make([A, B, C], [folder(3, (1, 2)), folder(5, (3,))])
    assert await ids(access) == {1, 2}
    assert tg.allowed == frozenset({1, 2})


async def test_two_selected_folders_are_merged():
    access, _, _, _ = make([A, B, C], [folder(3, (1,)), folder(5, (2,)), folder(6, (3,))], selected=(3, 5))
    assert await ids(access) == {1, 2}


async def test_chat_added_to_folder_visible_after_ttl():
    access, tg, clock, _ = make([A, B], [folder(3, (1,))])
    assert await ids(access) == {1}
    tg.folders = [folder(3, (1, 2))]
    assert await ids(access) == {1}  # still cached within TTL
    clock.now += FOLDER_TTL_SECONDS
    assert await ids(access) == {1, 2}
    assert tg.calls.count(("chat_infos", (1,))) == 1
    assert ("chat_infos", (2,)) in tg.calls
    assert tg.allowed == frozenset({1, 2})


async def test_chat_removed_from_folder_denied_after_ttl():
    access, tg, clock, _ = make([A, B], [folder(3, (1, 2))])
    await access.resolve("A")
    tg.folders = [folder(3, (2,))]
    clock.now += FOLDER_TTL_SECONDS
    with pytest.raises(AccessDenied):
        await access.resolve("A")
    assert tg.allowed == frozenset({2})


async def test_within_ttl_no_extra_folder_request():
    access, tg, clock, _ = make([A], [folder(3, (1,))])
    await access.allowed_chats()
    await access.allowed_chats()
    clock.now += FOLDER_TTL_SECONDS - 1
    await access.resolve(1)
    assert tg.calls.count(("list_folders",)) == 1
    clock.now += 1
    await access.allowed_chats()
    assert tg.calls.count(("list_folders",)) == 2


async def test_folder_request_failure_fails_closed():
    access, tg, clock, _ = make([A], [folder(3, (1,))])
    await access.allowed_chats()
    assert tg.allowed == frozenset({1})
    clock.now += FOLDER_TTL_SECONDS
    tg.folders_error = NetworkError()
    with pytest.raises(NetworkError):
        await access.allowed_chats()
    assert tg.allowed == frozenset()
    # Still failing: no stale cache may be served on the next call either.
    with pytest.raises(NetworkError):
        await access.resolve("A")
    # Recovery on the next call.
    tg.folders_error = None
    assert await ids(access) == {1}


async def test_renamed_folder_still_works():
    access, _, _, _ = make([A], [folder(3, (1,), title="Brand new name")])
    assert await ids(access) == {1}


async def test_vanished_folder_warns():
    access, _, _, _ = make([A], [folder(5, (1,))])
    assert await ids(access) == set()
    assert "Selected folder «f3» no longer exists — run telegram-reader folders" in access.warnings


async def test_auto_rules_warning_and_only_explicit_peers():
    access, _, _, _ = make([A], [folder(3, (1,), title="Work", auto=True)])
    assert await ids(access) == {1}
    assert "Folder «Work»: automatic rules are ignored" in access.warnings


async def test_no_folders_selected_means_no_chats():
    access, tg, _, _ = make([A], [folder(3, (1,))], selected=())
    assert await access.allowed_chats() == []
    assert tg.allowed == frozenset()


async def test_account_mismatch_raises_and_locks_guard():
    access, tg, _, _ = make([A], [folder(3, (1,))], account_id=999)
    tg.allowed = frozenset({1})
    with pytest.raises(AccountMismatch, match="another Telegram account"):
        await access.allowed_chats()
    assert tg.allowed == frozenset()
    assert ("list_folders",) not in tg.calls


async def test_config_change_takes_effect_without_waiting_ttl():
    access, tg, _, store = make([A, B], [folder(3, (1,)), folder(5, (2,))])
    assert await ids(access) == {1}
    store.cfg = cfg_for(5)
    assert await ids(access) == {2}
    assert tg.allowed == frozenset({2})


async def test_features_forwarded_to_tg():
    access, tg, _, _ = make([A], [folder(3, (1,))], features=frozenset({"reactions"}))
    await access.allowed_chats()
    assert tg.features == frozenset({"reactions"})


async def test_fresh_metadata_refetches_all():
    access, tg, _, _ = make([A, B], [folder(3, (1, 2))])
    await access.allowed_chats()
    tg.calls.clear()
    await access.allowed_chats()
    assert not any(c[0] == "chat_infos" for c in tg.calls)
    await access.allowed_chats(fresh_metadata=True)
    (call,) = [c for c in tg.calls if c[0] == "chat_infos"]
    assert set(call[1]) == {1, 2}


async def test_allowed_set_before_metadata_fetch():
    access, tg, _, _ = make([A], [folder(3, (1,))])
    order = []
    orig_set, orig_infos = tg.set_allowed, tg.chat_infos
    tg.set_allowed = lambda ids: (order.append("set"), orig_set(ids))[1]

    async def infos(ids):
        order.append("infos")
        return await orig_infos(ids)

    tg.chat_infos = infos
    await access.allowed_chats()
    assert order == ["set", "infos"]


async def test_allowed_sorted_by_last_date_desc():
    old = ChatInfo(1, "old", "group", None, last_date=datetime(2026, 1, 1, tzinfo=UTC))
    new = ChatInfo(2, "new", "group", None, last_date=datetime(2026, 10, 1, tzinfo=UTC))
    none = ChatInfo(3, "none", "group", None)
    access, _, _, _ = make([old, none, new], [folder(3, (1, 2, 3))])
    assert [c.id for c in await access.allowed_chats()] == [2, 1, 3]


async def test_resolve_outside_whitelist_denied():
    access, _, _, _ = make([A, B], [folder(3, (1,))])
    with pytest.raises(AccessDenied, match="No access to chat 999"):
        await access.resolve(999)
    with pytest.raises(AccessDenied):
        await access.resolve("B")


async def test_resolve_by_int_id():
    access, _, _, _ = make([A], [folder(3, (1,))])
    assert (await access.resolve(1)).title == "A"


async def test_resolve_is_case_and_space_insensitive():
    access, _, _, _ = make([CORE], [folder(3, (CORE.id,))])
    assert (await access.resolve("  example GROUP ")).id == CORE.id


async def test_resolve_numeric_string_as_id():
    access, _, _, _ = make([CORE], [folder(3, (CORE.id,))])
    assert (await access.resolve("-1001234567")).id == CORE.id


async def test_numeric_title_falls_back_to_name():
    year = chat(77, "2026")
    access, _, _, _ = make([year], [folder(3, (77,))])
    assert (await access.resolve("2026")).id == 77


async def test_resolve_ambiguous_lists_candidates():
    access, _, _, _ = make([chat(5, "Club"), chat(6, "Club")], [folder(3, (5, 6))])
    with pytest.raises(AmbiguousChat) as exc:
        await access.resolve("club")
    assert {c.id for c in exc.value.candidates} == {5, 6}
    assert "5 — Club" in str(exc.value) and "6 — Club" in str(exc.value)


async def test_forum_topics_loaded():
    forum = chat(7, "Forum", kind="forum")
    access, _, _, _ = make([forum], [folder(3, (7,))], topics={7: [TopicInfo(12, "General")]})
    (c,) = await access.allowed_chats()
    assert c.topics == (TopicInfo(12, "General"),)


async def test_failing_forum_does_not_break_whitelist():
    forum = chat(7, "Forum", kind="forum")
    access, tg, _, _ = make([A, forum], [folder(3, (1, 7))])

    async def broken(chat_id):
        raise NetworkError()

    tg.list_topics = broken
    chats = {c.id: c for c in await access.allowed_chats()}
    assert set(chats) == {1, 7} and chats[7].topics == ()
    assert any("Forum" in w for w in access.warnings)


async def test_warnings_logged_once(caplog):
    access, _, clock, _ = make([A], [folder(5, (1,))])
    with caplog.at_level(logging.WARNING, logger="telegram_reader"):
        await access.allowed_chats()
        clock.now += FOLDER_TTL_SECONDS
        await access.allowed_chats()
    assert caplog.text.count("no longer exists") == 1
