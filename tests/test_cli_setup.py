from types import SimpleNamespace

import pytest
from fake_ui import FakeUI
from fakes import FakeTg

from telegram_reader import keychain, paths
from telegram_reader.cli import setup as su
from telegram_reader.cli.login import LoginResult
from telegram_reader.cli.ui import Cancelled
from telegram_reader.config import Config, FolderRef, parse_config, write_config
from telegram_reader.errors import LoginRequired
from telegram_reader.keychain import SecretStoreUnavailable
from telegram_reader.models import ChatInfo, FolderInfo

HASH = "a" * 32


def text(ui, kind=None):
    return "\n".join(t for k, t in ui.lines if kind is None or k == kind)


@pytest.fixture
def env(fake_keyring, monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    tg = FakeTg(
        dialogs=[ChatInfo(id=i, title=f"C{i}", kind="group", link_base=None) for i in (10, 11, 12)],
        folders=[FolderInfo(1, "Work", (10, 11), False), FolderInfo(2, "Team", (11, 12), False)],
    )
    tg.connect_error = LoginRequired()  # no session until login "succeeds"
    monkeypatch.setattr(su, "TgClient", lambda api_id: tg)
    monkeypatch.setattr("telegram_reader.cli.login.webbrowser.open", lambda url: None)
    logins, regs = [], []

    async def fake_login(ui, api_id, *, previous_account=None, api_hash=None, **kw):
        logins.append((api_id, previous_account, api_hash))
        keychain.set_api_hash(api_hash or HASH)
        keychain.set_session("S")
        tg.connect_error = None
        return LoginResult(account_id=1, name="John", changed_account=False)

    monkeypatch.setattr(su, "login", fake_login)
    monkeypatch.setattr(su, "find_claude", lambda: "/bin/claude")
    monkeypatch.setattr(su, "is_registered", lambda c: False)
    monkeypatch.setattr(su, "register", lambda c: regs.append(c))
    monkeypatch.setattr(su, "manual_command", lambda: "claude mcp add MANUAL")

    def read():
        return parse_config(path.read_text(encoding="utf-8"), keychain.get_or_create_config_key())

    return SimpleNamespace(path=path, tg=tg, logins=logins, regs=regs, read=read)


# answers: [open browser?, api_id, api_hash, folders, features, register?]
HAPPY = [False, "12345", HASH, [1], [], True]


async def test_setup_happy_path_writes_config_once_and_registers(env, monkeypatch):
    writes = []
    real = su.write_config
    monkeypatch.setattr(su, "write_config", lambda *a: (writes.append(a), real(*a))[1])
    ui = FakeUI(list(HAPPY))
    assert await su.run_setup(ui) == 0
    assert len(writes) == 1
    cfg = env.read()
    assert (cfg.api_id, cfg.account_id, cfg.folders) == (12345, 1, (FolderRef(1, "Work"),))
    assert env.logins == [(12345, None, HASH)]
    assert env.regs == ["/bin/claude"]
    steps = [t for k, t in ui.lines if k == "step"]
    assert [s.split()[0] for s in steps] == [f"{n}/8" for n in range(1, 9)]
    out = text(ui)
    assert "John" in out and "Work" in out and "2 chats" in out
    assert "Restart the Claude Code session or run /mcp" in out
    assert ("disconnect",) in env.tg.calls


async def test_setup_existing_config_declined_changes_nothing(env):
    write_config(env.path, Config(api_id=1), keychain.get_or_create_config_key())
    before = env.path.read_bytes()
    ui = FakeUI([False])
    assert await su.run_setup(ui) == 0
    assert env.path.read_bytes() == before
    assert "folders" in text(ui) and "login" in text(ui) and "features" in text(ui)
    assert env.logins == []


async def test_setup_stops_early_without_secret_store(env, monkeypatch):
    def broken():
        raise SecretStoreUnavailable

    monkeypatch.setattr(keychain, "check_backend", broken)
    ui = FakeUI([])
    assert await su.run_setup(ui) == 1
    assert "secret store" in text(ui, "fail")
    assert not env.path.exists()


async def test_setup_cancel_before_folders_writes_no_config(env):
    env.tg.folders = []
    ui = FakeUI([False, "12345", HASH, "quit"])  # no folders -> "Quit" cancels
    with pytest.raises(Cancelled):
        await su.run_setup(ui)
    assert not env.path.exists()
    assert ("disconnect",) in env.tg.calls


async def test_setup_without_claude_prints_manual_command(env, monkeypatch):
    monkeypatch.setattr(su, "find_claude", lambda: None)
    ui = FakeUI([False, "12345", HASH, [1], []])
    assert await su.run_setup(ui) == 0
    assert "claude mcp add MANUAL" in text(ui)
    assert "claude" in text(ui, "warn")
    assert env.regs == []


async def test_setup_already_registered_skips_add(env, monkeypatch):
    monkeypatch.setattr(su, "is_registered", lambda c: True)
    ui = FakeUI([False, "12345", HASH, [1], []])
    assert await su.run_setup(ui) == 0
    assert "Already connected to Claude Code" in text(ui, "ok")
    assert env.regs == []


async def test_setup_declined_registration_prints_manual(env):
    ui = FakeUI([False, "12345", HASH, [1], [], False])
    assert await su.run_setup(ui) == 0
    assert env.regs == [] and "MANUAL" in text(ui)


async def test_setup_register_failure_reports_and_exits_1(env, monkeypatch):
    def boom(c):
        raise RuntimeError("nope")

    monkeypatch.setattr(su, "register", boom)
    ui = FakeUI(list(HAPPY))
    assert await su.run_setup(ui) == 1
    assert "nope" in text(ui, "fail") and "MANUAL" in text(ui)
    assert env.path.exists()


async def test_setup_keeps_existing_session(env):
    keychain.set_api_hash(HASH)
    keychain.set_session("S")
    env.tg.connect_error = None
    # no api_id known (no config) -> asked; answers: browser?, api_id, hash, keep, folders, features, register
    ui = FakeUI([False, "12345", HASH, "keep", [1], [], True])
    assert await su.run_setup(ui) == 0
    assert env.logins == []
    assert env.read().account_id == 1


async def test_setup_change_account_logs_in_again(env):
    keychain.set_api_hash(HASH)
    keychain.set_session("S")
    env.tg.connect_error = None
    ui = FakeUI([False, "12345", HASH, "change", [1], [], True])
    assert await su.run_setup(ui) == 0
    assert env.logins == [(12345, 1, HASH)]


async def test_setup_reuses_stored_credentials_when_starting_over(env):
    write_config(env.path, Config(api_id=777), keychain.get_or_create_config_key())
    keychain.set_api_hash(HASH)
    keychain.set_session("S")
    env.tg.connect_error = None
    ui = FakeUI([True, "keep", [1], [], True])  # start over? yes
    assert await su.run_setup(ui) == 0
    assert env.read().api_id == 777
