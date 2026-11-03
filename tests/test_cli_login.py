import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fake_ui import FakeUI
from telethon import errors
from telethon.tl import types

from telegram_reader import keychain, paths
from telegram_reader.cli import login as lg
from telegram_reader.cli.ui import Cancelled
from telegram_reader.config import Config, FolderRef, parse_config, write_config

HASH = "0123456789abcdef0123456789abcdef"
PHONE = "+15551230000"
CANCEL = object()


class UI(FakeUI):
    """FakeUI where the CANCEL sentinel in the script raises Cancelled (Ctrl+C)."""

    def _next(self):
        value = super()._next()
        if value is CANCEL:
            raise Cancelled
        return value

    def text(self) -> str:
        return "\n".join(t for _, t in self.lines)


class FakeLoginClient:
    instances: list = []
    sent_types: list = []
    sign_in_errors: list = []

    def __init__(self, session, api_id, api_hash, **kwargs):
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.kwargs = kwargs
        self.events = []
        FakeLoginClient.instances.append(self)

    async def connect(self):
        self.events.append("connect")

    async def send_code_request(self, phone):
        self.events.append(("send_code", phone))
        return SimpleNamespace(type=FakeLoginClient.sent_types.pop(0))

    async def sign_in(self, phone=None, code=None, password=None):
        self.events.append(("sign_in", code, password))
        if FakeLoginClient.sign_in_errors:
            raise FakeLoginClient.sign_in_errors.pop(0)

    async def get_me(self):
        return types.User(id=1, first_name="Alex")

    async def log_out(self):
        self.events.append("log_out")

    async def disconnect(self):
        self.events.append("disconnect")


@pytest.fixture
def login_env(monkeypatch, fake_keyring):
    FakeLoginClient.instances = []
    FakeLoginClient.sent_types = [types.auth.SentCodeTypeApp(length=5), types.auth.SentCodeTypeSms(length=5)]
    FakeLoginClient.sign_in_errors = []
    monkeypatch.setattr(lg, "TelegramClient", FakeLoginClient)
    monkeypatch.setattr(lg, "StringSession", lambda s="": SimpleNamespace(src=s, save=lambda: "new-session"))
    monkeypatch.setattr(lg.webbrowser, "open", lambda url: True)
    keychain.set_api_hash(HASH)
    return fake_keyring


def stored(name):
    return {"api_hash": keychain.get_api_hash, "session": keychain.get_session}[name]()


@pytest.fixture
def tmp_config(login_env, monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(paths, "migrate_location", lambda: False)

    def write(cfg):
        write_config(path, cfg, keychain.get_or_create_config_key())

    def read():
        return parse_config(path.read_text(encoding="utf-8"), keychain.get_or_create_config_key())

    write(Config(api_id=1, account_id=1, folders=(FolderRef(5, "Work"),)))
    return SimpleNamespace(path=path, write=write, read=read)


# --- code login ----------------------------------------------------------


async def test_login_tells_where_code_was_sent(login_env):
    ui = UI([PHONE, "12345"])
    result = await lg.login(ui, 1, method="code")
    assert (result.account_id, result.name, result.changed_account) == (1, "Alex", False)
    assert "Telegram app" in ui.text() and "Alex" in ui.text()
    assert stored("session") == "new-session"
    client = FakeLoginClient.instances[0]
    assert client.api_id == 1 and client.api_hash == HASH and client.kwargs["receive_updates"] is False


async def test_empty_code_resends(login_env):
    ui = UI([PHONE, "", "12345"])
    await lg.login(ui, 1, method="code")
    events = FakeLoginClient.instances[0].events
    assert [e for e in events if e[0] == "send_code"] == [("send_code", PHONE)] * 2
    assert "SMS" in ui.text()


async def test_wrong_code_asks_again_then_2fa(login_env):
    FakeLoginClient.sign_in_errors = [errors.PhoneCodeInvalidError(None), errors.SessionPasswordNeededError(None)]
    ui = UI([PHONE, "11111", "12345", "2fa"])
    await lg.login(ui, 1, method="code")
    sign_ins = [e for e in FakeLoginClient.instances[0].events if e[0] == "sign_in"]
    assert sign_ins == [("sign_in", "11111", None), ("sign_in", "12345", None), ("sign_in", None, "2fa")]
    assert "Wrong code" in ui.text()


async def test_bad_2fa_shows_problem_and_asks_again(login_env):
    FakeLoginClient.sign_in_errors = [errors.SessionPasswordNeededError(None), errors.PasswordHashInvalidError(None)]
    ui = UI([PHONE, "12345", "wrong", "right"])
    await lg.login(ui, 1, method="code")
    sign_ins = [e for e in FakeLoginClient.instances[0].events if e[0] == "sign_in"]
    assert sign_ins[-2:] == [("sign_in", None, "wrong"), ("sign_in", None, "right")]
    assert "two-step" in ui.text()


async def test_email_setup_required_is_explained(login_env):
    FakeLoginClient.sent_types = [types.auth.SentCodeTypeSetUpEmailRequired()]
    ui = UI([PHONE])
    with pytest.raises(lg.LoginFailed):
        await lg.login(ui, 1, method="code")
    assert "email" in ui.text()
    assert stored("session") is None


async def test_phone_must_be_international(login_env):
    ui = UI(["501234567", "+1 555 123-45-67", "12345"])
    await lg.login(ui, 1, method="code")
    assert ("send_code", "+15551234567") in FakeLoginClient.instances[0].events
    assert "+1555" in ui.text()


@pytest.mark.parametrize("error_name", ["SendCodeUnavailableError", "FloodWaitError"])
async def test_failed_resend_keeps_waiting_for_the_code(login_env, monkeypatch, error_name):
    calls = {"n": 0}
    original = FakeLoginClient.send_code_request

    async def send(self, phone):
        calls["n"] += 1
        if calls["n"] == 2:
            raise getattr(errors, error_name)(None)
        return await original(self, phone)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", send)
    ui = UI([PHONE, "", "12345"])
    await lg.login(ui, 1, method="code")
    assert "The code cannot be resent right now" in ui.text()
    assert stored("session") == "new-session"


# --- api_hash / api_id ----------------------------------------------------


async def test_missing_api_hash_asked_until_valid(login_env):
    login_env.clear()
    ui = UI(["", "  ", "abc123", HASH[:-1] + "x", f" {HASH.upper()} ", PHONE, "12345"])
    await lg.login(ui, 1, method="code")
    assert stored("api_hash") == HASH
    assert FakeLoginClient.instances[0].api_hash == HASH
    assert "got 6" in ui.text()


async def test_ask_api_credentials_validates_and_offers_browser(login_env, monkeypatch):
    opened = []
    monkeypatch.setattr(lg.webbrowser, "open", lambda url: opened.append(url))
    ui = UI([True, "0", "12345", "abc", HASH])
    assert await lg.ask_api_credentials(ui) == (12345, HASH)
    assert opened == ["https://my.telegram.org"]
    text = ui.text()
    assert "A positive integer from my.telegram.org is required" in text
    assert "Expected 32 characters 0-9a-f, got 3" in text


async def test_api_id_invalid_returns_to_credentials_step(login_env, monkeypatch):
    original = FakeLoginClient.send_code_request
    calls = {"n": 0}

    async def send(self, phone):
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.ApiIdInvalidError(None)
        return await original(self, phone)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", send)
    new_hash = "f" * 32
    ui = UI([PHONE, False, "777", new_hash, PHONE, "12345"])
    result = await lg.login(ui, 1, method="code")
    assert "Telegram rejected api_id" in ui.text()
    assert stored("api_hash") == new_hash and result.api_id == 777
    assert [c.api_id for c in FakeLoginClient.instances][:2] == [1, 777]


# --- failures leave no trace ----------------------------------------------


async def test_login_disconnects_on_failure(login_env, monkeypatch):
    async def boom(self, phone):
        raise RuntimeError("boom")

    monkeypatch.setattr(FakeLoginClient, "send_code_request", boom)
    with pytest.raises(RuntimeError):
        await lg.login(UI([PHONE]), 1, method="code")
    assert FakeLoginClient.instances[0].events[-1] == "disconnect"
    assert stored("session") is None


async def test_telegram_rejection_is_reported(login_env, monkeypatch):
    async def reject(self, phone):
        raise errors.PhoneNumberInvalidError(None)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", reject)
    ui = UI([PHONE])
    with pytest.raises(lg.LoginFailed):
        await lg.login(ui, 1, method="code")
    assert "PhoneNumberInvalid" in ui.text() and stored("session") is None
    assert FakeLoginClient.instances[0].events[-1] == "disconnect"


async def test_secrets_not_saved_when_cancelled(login_env):
    login_env.clear()
    ui = UI([HASH, PHONE, CANCEL])
    with pytest.raises(Cancelled):
        await lg.login(ui, 1, method="code")
    assert stored("api_hash") is None and stored("session") is None
    assert FakeLoginClient.instances[0].events[-1] == "disconnect"


async def test_network_error_is_reported_not_cancelled(login_env, monkeypatch):
    async def offline(self):
        raise ConnectionError("down")

    monkeypatch.setattr(FakeLoginClient, "connect", offline)
    ui = UI([PHONE])
    with pytest.raises(lg.LoginFailed):
        await lg.login(ui, 1, method="code")
    assert "No network" in ui.text() and stored("session") is None


async def test_flood_wait_offers_wait_or_exit(login_env, monkeypatch):
    original = FakeLoginClient.send_code_request
    calls = {"n": 0}

    async def send(self, phone):
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.FloodWaitError(None, capture=42)
        return await original(self, phone)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", send)
    ui = UI([PHONE, True, "12345"])
    await lg.login(ui, 1, method="code")
    assert "wait 42 s" in ui.text()
    assert any(kind == "wait" and text.startswith("42") for kind, text in ui.lines)

    calls["n"] = 0
    FakeLoginClient.sent_types = [types.auth.SentCodeTypeApp(length=5)]
    with pytest.raises(Cancelled):
        await lg.login(UI([PHONE, False]), 1, method="code")


async def test_relogin_logs_out_previous_session(login_env):
    keychain.set_session("old-session")
    await lg.login(UI([PHONE, "12345"]), 1, method="code")
    assert stored("session") == "new-session"
    old = [c for c in FakeLoginClient.instances if c.session.src == "old-session"]
    assert old and "log_out" in old[0].events


async def test_changed_account_flag(login_env):
    result = await lg.login(UI([PHONE, "12345"]), 1, method="code", previous_account=99)
    assert result.changed_account is True


# --- QR --------------------------------------------------------------------


class FakeQR:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)  # per wait(): exception to raise, or None for success
        self.url = "tg://login?token=AAA"
        self.recreated = 0
        self.expires = datetime.now(UTC) + timedelta(seconds=30)

    async def wait(self, timeout=None):
        outcome = self.outcomes.pop(0)
        if outcome:
            raise outcome

    async def recreate(self):
        self.recreated += 1
        self.url = f"tg://login?token=NEW{self.recreated}"


@pytest.fixture
def qr_env(login_env, monkeypatch):
    def use(qr):
        async def qr_login(self):
            self.events.append("qr_login")
            return qr

        monkeypatch.setattr(FakeLoginClient, "qr_login", qr_login, raising=False)

    return SimpleNamespace(use_qr=use)


def qr_urls(ui):
    return [t for k, t in ui.lines if k == "qr"]


async def test_qr_login_success(qr_env):
    qr_env.use_qr(FakeQR([None]))
    ui = UI([])
    result = await lg.login(ui, 1)  # qr is the default method
    assert qr_urls(ui) == ["tg://login?token=AAA"]
    assert stored("session") == "new-session" and result.name == "Alex"
    assert "Devices" in ui.text()


async def test_qr_expired_is_recreated(qr_env):
    qr_env.use_qr(FakeQR([asyncio.TimeoutError(), None]))
    ui = UI([])
    await lg.login(ui, 1)
    assert qr_urls(ui) == ["tg://login?token=AAA", "tg://login?token=NEW1"]


async def test_qr_with_2fa(qr_env):
    qr_env.use_qr(FakeQR([errors.SessionPasswordNeededError(None)]))
    await lg.login(UI(["2fa"]), 1)
    assert ("sign_in", None, "2fa") in FakeLoginClient.instances[0].events


async def test_qr_client_receives_updates(qr_env):
    # qr.wait() completes on an UpdateLoginToken, which never arrives with receive_updates=False
    qr_env.use_qr(FakeQR([None]))
    await lg.login(UI([]), 1)
    assert FakeLoginClient.instances[0].kwargs["receive_updates"] is True


async def test_qr_asks_after_five_renewals(qr_env):
    qr = FakeQR([asyncio.TimeoutError()] * 6 + [None])
    qr_env.use_qr(qr)
    ui = UI([True])  # "show one more QR?" -> yes
    await lg.login(ui, 1)
    assert len(qr_urls(ui)) == 7 and qr.recreated == 6


async def test_qr_declined_after_five_renewals_cancels(qr_env):
    qr_env.use_qr(FakeQR([asyncio.TimeoutError()] * 6))
    ui = UI([False])
    with pytest.raises(Cancelled):
        await lg.login(ui, 1)
    assert "expired several times" in ui.text() and stored("session") is None


# --- logout ----------------------------------------------------------------


async def test_logout_revokes_and_clears(login_env):
    keychain.set_session("old-session")
    ui = UI([])
    await lg.logout(ui, 1)
    assert stored("session") is None and stored("api_hash") is None
    assert any("log_out" in c.events for c in FakeLoginClient.instances)
    assert "secret store" in ui.text()


async def test_logout_warns_when_server_revoke_fails(login_env, monkeypatch):
    keychain.set_session("old-session")

    async def fail(self):
        raise ConnectionError("offline")

    monkeypatch.setattr(FakeLoginClient, "connect", fail)
    ui = UI([])
    await lg.logout(ui, 1)
    assert "Could not end the session" in ui.text() and "Devices" in ui.text()
    assert stored("session") is None


# --- commands --------------------------------------------------------------


async def test_changed_account_resets_folders(tmp_config, monkeypatch):
    from telegram_reader.cli import folders as folders_mod

    opened = []

    async def fake_run_folders(ui):
        opened.append(ui)
        return 7

    monkeypatch.setattr(folders_mod, "run_folders", fake_run_folders)
    tmp_config.write(Config(api_id=1, account_id=99, folders=(FolderRef(5, "Work"),)))
    ui = UI([PHONE, "12345"])
    assert await lg.run_login(ui, method="code") == 7  # folder picker's exit code
    cfg = tmp_config.read()
    assert cfg.folders == () and cfg.account_id == 1
    assert opened == [ui]


async def test_same_account_keeps_folders(tmp_config):
    ui = UI([PHONE, "12345"])
    assert await lg.run_login(ui, method="code") == 0
    assert tmp_config.read().folders == (FolderRef(5, "Work"),)
    assert "Account changed" not in ui.text()


async def test_first_login_records_account(tmp_config):
    tmp_config.write(Config(api_id=1))
    assert await lg.run_login(UI([PHONE, "12345"]), method="code") == 0
    assert tmp_config.read().account_id == 1


async def test_run_login_without_config_points_to_setup(login_env, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "none.toml")
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    ui = UI([])
    assert await lg.run_login(ui) == 1
    assert "setup" in ui.text()


async def test_run_login_network_failure_returns_1(tmp_config, monkeypatch):
    async def offline(self):
        raise OSError("down")

    monkeypatch.setattr(FakeLoginClient, "connect", offline)
    ui = UI([PHONE])
    assert await lg.run_login(ui, method="code") == 1
    assert "No network" in ui.text()


async def test_run_logout_clears_secrets_and_keeps_config_valid(tmp_config):
    keychain.set_session("old-session")
    assert await lg.run_logout(UI([])) == 0
    assert stored("session") is None
    assert tmp_config.read().folders == (FolderRef(5, "Work"),)  # re-signed with the fresh key


# --- edge cases ------------------------------------------------------------


async def test_revoke_uses_credentials_the_previous_session_belongs_to(login_env, monkeypatch):
    keychain.set_session("old-session")
    original = FakeLoginClient.send_code_request
    calls = {"n": 0}

    async def send(self, phone):
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.ApiIdInvalidError(None)
        return await original(self, phone)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", send)
    new_hash = "f" * 32
    await lg.login(UI([PHONE, False, "777", new_hash, PHONE, "12345"]), 1, method="code")
    old = [c for c in FakeLoginClient.instances if c.session.src == "old-session"]
    assert len(old) == 1 and (old[0].api_id, old[0].api_hash) == (1, HASH)
    assert "log_out" in old[0].events


async def test_flood_wait_on_connect_goes_through_countdown(login_env, monkeypatch):
    original = FakeLoginClient.connect
    calls = {"n": 0}

    async def connect(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.FloodWaitError(None, capture=9)
        return await original(self)

    monkeypatch.setattr(FakeLoginClient, "connect", connect)
    ui = UI([True, PHONE, "12345"])
    await lg.login(ui, 1, method="code")
    assert any(kind == "wait" and text.startswith("9") for kind, text in ui.lines)
    assert stored("session") == "new-session"


@pytest.mark.parametrize("broken", ["missing", "tampered"])
async def test_run_logout_with_unusable_config_clears_secrets_without_resigning(tmp_config, broken):
    keychain.set_session("old-session")
    if broken == "missing":
        tmp_config.path.unlink()
        before = None
    else:
        tmp_config.path.write_text(tmp_config.path.read_text(encoding="utf-8").replace("Work", "Evil"), encoding="utf-8")
        before = tmp_config.path.read_text(encoding="utf-8")
    ui = UI([])
    assert await lg.run_logout(ui) == 0
    assert stored("session") is None and stored("api_hash") is None
    assert not FakeLoginClient.instances  # no api_id known: nothing revoked server-side
    assert (tmp_config.path.read_text(encoding="utf-8") if tmp_config.path.exists() else None) == before


# --- login on an outdated / tampered config -------------------------------

LEGACY_V1 = """
[telegram]
api_id = 1
[access]
folders = ["Work"]
"""


@pytest.fixture
def opened_folders(monkeypatch):
    from telegram_reader.cli import folders as folders_mod

    opened = []

    async def fake_run_folders(ui):
        opened.append(ui)
        return 0

    monkeypatch.setattr(folders_mod, "run_folders", fake_run_folders)
    return opened


async def test_run_login_on_v1_config_logs_in_then_opens_folders(tmp_config, opened_folders):
    tmp_config.path.write_text(LEGACY_V1, encoding="utf-8")
    ui = UI([PHONE, "12345"])
    assert await lg.run_login(ui, method="code") == 0
    assert FakeLoginClient.instances[0].api_id == 1 and stored("session") == "new-session"
    assert opened_folders == [ui]
    assert tmp_config.path.read_text(encoding="utf-8") == LEGACY_V1  # folders migrates it
    assert "folder picker" in ui.text()


async def test_run_login_on_tampered_config_logs_in_then_opens_folders(tmp_config, opened_folders):
    tmp_config.path.write_text(
        tmp_config.path.read_text(encoding="utf-8").replace("Work", "Evil"), encoding="utf-8"
    )
    ui = UI([PHONE, "12345"])
    assert await lg.run_login(ui, method="code") == 0
    assert FakeLoginClient.instances[0].api_id == 1 and stored("session") == "new-session"
    assert opened_folders == [ui]
    # The tampering itself is explained once, by `folders` (mocked here).
    assert "the folder picker opens" in ui.text()
    assert "Config was changed outside telegram-reader" not in ui.text()


async def test_run_login_on_tampered_config_keeps_reentered_api_id(tmp_config, opened_folders, monkeypatch):
    tmp_config.path.write_text(
        tmp_config.path.read_text(encoding="utf-8").replace("Work", "Evil"), encoding="utf-8"
    )
    original = FakeLoginClient.send_code_request
    calls = {"n": 0}

    async def send(self, phone):
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.ApiIdInvalidError(None)
        return await original(self, phone)

    monkeypatch.setattr(FakeLoginClient, "send_code_request", send)
    ui = UI([PHONE, False, "777", "f" * 32, PHONE, "12345"])
    assert await lg.run_login(ui, method="code") == 0
    cfg = tmp_config.read()  # rewritten and signed, folders chosen again
    assert (cfg.api_id, cfg.account_id, cfg.folders) == (777, 1, ())
    assert opened_folders == [ui]


async def test_run_login_on_broken_config_still_fails(tmp_config):
    tmp_config.path.write_text("not = [toml", encoding="utf-8")
    ui = UI([])
    assert await lg.run_login(ui) == 1
    assert not FakeLoginClient.instances


async def test_logout_message_names_secret_store(login_env):
    ui = UI([])
    await lg.logout(ui, 1)
    assert "Secrets removed from the secret store" in ui.text()
