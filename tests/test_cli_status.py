from fake_ui import FakeUI
from fakes import FakeStore, FakeTg

from telegram_reader import paths
from telegram_reader.cli import common
from telegram_reader.cli.status import run_status
from telegram_reader.config import Config, FolderRef
from telegram_reader.errors import AccountMismatch, LoginRequired, NetworkError
from telegram_reader.models import ChatInfo, FolderInfo
from telegram_reader.store import ConfigStore


def chat(id, title):
    return ChatInfo(id=id, title=title, kind="group", link_base=None)


def setup(chats=(chat(10, "Alpha"), chat(11, "Beta")), auto=False, **cfg):
    folder = FolderInfo(3, "Work", tuple(c.id for c in chats), auto)
    tg = FakeTg(dialogs=list(chats), folders=[folder])
    store = FakeStore(Config(api_id=1, account_id=1, folders=(FolderRef(3, "Work"),), **cfg))
    return tg, store


def text(ui, kind=None):
    return "\n".join(t for k, t in ui.lines if kind is None or k == kind)


async def test_status_happy_path():
    tg, store = setup()
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 0
    out = text(ui)
    assert "Account: John (1)" in out
    assert "Folders: Work" in out
    assert "Claude sees 2 chats" in out
    assert "10 · Alpha" in out and "11 · Beta" in out


async def test_status_without_login_says_login():
    tg, store = setup()
    tg.connect_error = LoginRequired()
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "telegram-reader login" in text(ui, "fail")


async def test_status_shows_feature_states():
    tg, store = setup()
    ui = FakeUI()
    await run_status(ui, store=store, tg=tg)
    assert "Features: Sending messages — disabled (unavailable)" in text(ui)


async def test_status_shows_warnings():
    tg, store = setup(auto=True)
    ui = FakeUI()
    await run_status(ui, store=store, tg=tg)
    assert "automatic rules" in text(ui, "warn")


async def test_status_reports_claude_registration():
    for value, expected in [(True, "Claude Code: connected"), (False, "Claude Code: not connected"), (None, "Claude Code: claude not found")]:
        tg, store = setup()
        ui = FakeUI()
        await run_status(ui, store=store, tg=tg, registered=lambda v=value: v)
        assert expected in text(ui)
    tg, store = setup()
    ui = FakeUI()
    await run_status(ui, store=store, tg=tg)
    assert "Claude Code" not in text(ui)


async def test_status_returns_1_without_chats():
    tg, store = setup(chats=())
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "Claude sees 0 chats" in text(ui)


async def test_status_account_mismatch_and_network():
    tg, store = setup()
    tg.account_id = 2
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "telegram-reader folders" in text(ui, "fail")
    tg, store = setup()
    tg.connect_error = NetworkError()
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "connect" in text(ui, "fail")


async def test_status_missing_config_is_message_not_traceback(fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "none.toml")
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    ui = FakeUI()
    assert await run_status(ui, tg=FakeTg()) == 1
    assert text(ui, "fail")
    assert not (tmp_path / "none.toml").exists()


async def test_status_does_not_migrate_or_move_legacy_config(fake_keyring, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "none.toml")
    monkeypatch.setattr(paths, "migrate_location", lambda: calls.append(1))
    await run_status(FakeUI(), tg=FakeTg())
    assert calls == []


async def test_status_unexpected_oserror_is_not_reported_as_network():
    import pytest

    tg, store = setup()

    async def boom():
        raise PermissionError("denied")

    tg.connect = boom
    ui = FakeUI()
    with pytest.raises(PermissionError):
        await run_status(ui, store=store, tg=tg)
    assert "network" not in text(ui)


async def test_status_disconnects_and_hints_when_empty():
    tg, store = setup(chats=())
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "telegram-reader folders" in text(ui)
    assert ("disconnect",) in tg.calls


async def test_status_revoked_session_says_session_ended():
    from telegram_reader.errors import SessionRevoked

    tg, store = setup()
    tg.connect_error = SessionRevoked()
    ui = FakeUI()
    assert await run_status(ui, store=store, tg=tg) == 1
    assert "Session ended" in text(ui, "fail") and "telegram-reader login" in text(ui, "fail")
