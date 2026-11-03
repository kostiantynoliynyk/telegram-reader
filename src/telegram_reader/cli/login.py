"""Interactive login (QR or code) and logout, driven through the UI abstraction."""

from __future__ import annotations

import asyncio
import dataclasses
import re
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl import types

from .. import keychain, paths
from ..config import Config, ConfigError, ConfigOutdated, ConfigTampered, read_api_id, write_config
from ..keychain import SecretStoreUnavailable
from ..tg import DEVICE_MODEL, display_name
from .common import load_store
from .messages import (
    API_ID_INVALID,
    BAD_2FA,
    EMAIL_REQUIRED,
    FLOOD_WAIT,
    NO_NETWORK,
    NO_SECRET_STORE,
    QR_EXPIRED_MANY,
    Problem,
    format_problem,
)
from .ui import UI, Cancelled

T = TypeVar("T")

MY_TELEGRAM = "https://my.telegram.org"
QR_AUTO_RENEWALS = 5

TELEGRAM_REJECTED = Problem(
    what="Telegram rejected the login: {error}",
    why="the Telegram server rejected the request",
    todo="check what you entered and try again",
)
SECRETS_CLEARED = "Secrets removed from the secret store"
REVOKE_FAILED = (
    "Could not end the session on the Telegram server ({error}). "
    "End it manually: Settings → Devices → telegram-reader."
)


class LoginFailed(Exception):
    """Login failed and the reason has already been shown to the user."""


@dataclass(frozen=True)
class LoginResult:
    account_id: int
    name: str
    changed_account: bool
    api_id: int | None = None  # set when the user had to re-enter credentials


def _problem(p: Problem, **values: object) -> str:
    return format_problem(
        dataclasses.replace(p, what=p.what.format(**values), why=p.why.format(**values), todo=p.todo.format(**values))
    )


def _client(session: str, api_id: int, api_hash: str, *, receive_updates: bool = False) -> TelegramClient:
    return TelegramClient(StringSession(session), api_id, api_hash, device_model=DEVICE_MODEL, receive_updates=receive_updates)


# --- credentials --------------------------------------------------------------

_API_HASH = re.compile(r"[0-9a-f]{32}")
_PHONE = re.compile(r"\+\d{7,15}")


def _valid_api_id(text: str) -> str | None:
    text = text.strip()
    if text.isascii() and text.isdigit() and int(text) > 0:
        return None
    return "A positive integer from my.telegram.org is required"


def _valid_api_hash(text: str) -> str | None:
    value = text.strip().lower()
    if _API_HASH.fullmatch(value):
        return None
    return f"Expected 32 characters 0-9a-f, got {len(value)}"


def _valid_phone(text: str) -> str | None:
    if _PHONE.fullmatch(re.sub(r"[\s()-]", "", text)):
        return None
    return "A number with a country code is required, e.g. +15551234567"


async def _ask_api_hash(ui: UI) -> str:
    value = await ui.ask(
        "api_hash from my.telegram.org (32 characters, input is hidden)", validate=_valid_api_hash, secret=True
    )
    return value.strip().lower()


async def ask_api_credentials(ui: UI) -> tuple[int, str]:
    ui.say(f"You need your app's api_id and api_hash: {MY_TELEGRAM} → API development tools.")
    if await ui.confirm("Open my.telegram.org in the browser?"):
        webbrowser.open(MY_TELEGRAM)
    api_id = int((await ui.ask("api_id", validate=_valid_api_id)).strip())
    return api_id, await _ask_api_hash(ui)


# --- helpers ---------------------------------------------------------------------


async def _retry_flood(ui: UI, call: Callable[[], Awaitable[T]]) -> T:
    """Run `call`; on FloodWait offer to wait it out, otherwise cancel."""
    while True:
        try:
            return await call()
        except errors.FloodWaitError as e:
            seconds = int(getattr(e, "seconds", 0) or 0)
            ui.fail(_problem(FLOOD_WAIT, seconds=seconds))
            if not await ui.wait(seconds, "Waiting"):
                raise Cancelled from None


async def _revoke(ui: UI, session: str, api_id: int, api_hash: str) -> bool:
    """Log the session out on Telegram's side; on failure tell the user how to finish it by hand."""
    client = _client(session, api_id, api_hash)
    try:
        await client.connect()
        await client.log_out()
        return True
    except Exception as e:
        ui.warn(REVOKE_FAILED.format(error=type(e).__name__))
        return False
    finally:
        await client.disconnect()


def _where(code_type: object) -> str | None:
    """Human description of where Telegram sent the login code; None if it sent none."""
    t = types.auth
    if isinstance(code_type, t.SentCodeTypeApp):
        return "to the Telegram app on your other device (the «Telegram» chat with a blue check mark, possibly archived)"
    if isinstance(code_type, (t.SentCodeTypeSms, t.SentCodeTypeSmsWord, t.SentCodeTypeSmsPhrase, t.SentCodeTypeFirebaseSms)):
        return "by SMS"
    if isinstance(code_type, (t.SentCodeTypeCall, t.SentCodeTypeFlashCall, t.SentCodeTypeMissedCall)):
        return "by phone call (the code is the last digits of the number or dictated)"
    if isinstance(code_type, t.SentCodeTypeEmailCode):
        return f"to email {code_type.email_pattern}"
    if isinstance(code_type, t.SentCodeTypeFragmentSms):
        return f"via Fragment: {code_type.url}"
    return None


async def _send_code(ui: UI, client: TelegramClient, phone: str, *, retry_flood: bool = True) -> None:
    async def send():
        return await client.send_code_request(phone)  # a repeat call for the same phone resends the code

    sent = await (_retry_flood(ui, send) if retry_flood else send())
    where = _where(sent.type)
    if where is None:
        ui.fail(format_problem(EMAIL_REQUIRED))
        raise LoginFailed
    ui.say(f"Code sent {where}.")


async def _ask_2fa(ui: UI, client: TelegramClient) -> None:
    while True:
        password = await ui.ask("2FA password", secret=True)
        try:
            await _retry_flood(ui, lambda: client.sign_in(password=password))
            return
        except errors.PasswordHashInvalidError:
            ui.fail(format_problem(BAD_2FA))


async def _by_code(ui: UI, client: TelegramClient) -> None:
    phone = re.sub(r"[\s()-]", "", await ui.ask("Phone in international format (+1…)", validate=_valid_phone))
    await _send_code(ui, client, phone)
    while True:
        code = (await ui.ask("Code from Telegram (Enter to resend)")).strip()
        if not code:
            try:
                await _send_code(ui, client, phone, retry_flood=False)
            except (errors.SendCodeUnavailableError, errors.FloodWaitError) as e:
                # The code already sent stays valid; only resending is blocked.
                ui.warn(
                    f"The code cannot be resent right now ({type(e).__name__}). "
                    "Enter the code you already received, or stop (Ctrl+C) and try later."
                )
            continue
        try:
            await _retry_flood(ui, lambda: client.sign_in(phone=phone, code=code))
            return
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
            ui.fail("Wrong code, try again.")
        except errors.SessionPasswordNeededError:
            await _ask_2fa(ui, client)
            return


async def _by_qr(ui: UI, client: TelegramClient) -> None:
    qr = await _retry_flood(ui, client.qr_login)
    renewals = 0
    while True:
        ui.say(
            "Scan the QR in Telegram on your phone: "
            "Settings → Devices → Link Desktop Device."
        )
        ui.qr(qr.url)
        try:
            timeout = max((qr.expires - datetime.now(UTC)).total_seconds(), 1)
            await _retry_flood(ui, lambda: qr.wait(timeout=timeout))
            return
        except asyncio.TimeoutError:
            if renewals >= QR_AUTO_RENEWALS:
                ui.fail(format_problem(QR_EXPIRED_MANY))
                if not await ui.confirm("Show another QR?"):
                    raise Cancelled from None
                renewals = 0
            else:
                renewals += 1
                ui.say("QR code expired, showing a new one…")
            await _retry_flood(ui, qr.recreate)
        except errors.SessionPasswordNeededError:
            await _ask_2fa(ui, client)
            return


async def _attempt(ui: UI, api_id: int, api_hash: str, method: str) -> tuple[int, str, str]:
    """One authorization run on a fresh client. Returns (account id, name, session string)."""
    # QR login completes on an UpdateLoginToken, so that client must receive updates.
    client = _client("", api_id, api_hash, receive_updates=method == "qr")
    try:
        await _retry_flood(ui, client.connect)
        if method == "qr":
            await _by_qr(ui, client)
        else:
            await _by_code(ui, client)
        me = await _retry_flood(ui, client.get_me)
        return me.id, display_name(me), client.session.save()
    except errors.ApiIdInvalidError:
        raise
    except errors.RPCError as e:
        ui.fail(_problem(TELEGRAM_REJECTED, error=type(e).__name__))
        raise LoginFailed from e
    except OSError as e:  # includes ConnectionError
        ui.fail(format_problem(NO_NETWORK))
        raise LoginFailed from e
    finally:
        await client.disconnect()


# --- commands --------------------------------------------------------------------


async def login(
    ui: UI,
    api_id: int,
    *,
    method: Literal["qr", "code"] = "qr",
    previous_account: int | None = None,
    api_hash: str | None = None,
) -> LoginResult:
    """Sign in. Secrets are stored only after success; the previous session is revoked afterwards."""
    api_hash = api_hash or keychain.get_api_hash() or await _ask_api_hash(ui)
    previous_session = keychain.get_session()
    # The previous session belongs to the credentials in use before this login started.
    previous_creds = (api_id, api_hash)
    entered = False
    while True:
        try:
            account_id, name, session = await _attempt(ui, api_id, api_hash, method)
            break
        except errors.ApiIdInvalidError:
            keychain.clear_api_hash()
            ui.fail(format_problem(API_ID_INVALID))
            api_id, api_hash = await ask_api_credentials(ui)
            entered = True
    keychain.set_api_hash(api_hash)
    keychain.set_session(session)
    ui.ok(f"Logged in as {name}")
    if previous_session:
        # Don't leave the old authorized session orphaned on the account.
        await _revoke(ui, previous_session, *previous_creds)
    return LoginResult(
        account_id=account_id,
        name=name,
        changed_account=previous_account is not None and account_id != previous_account,
        api_id=api_id if entered else None,
    )


async def logout(ui: UI, api_id: int) -> None:
    api_hash, session = keychain.get_api_hash(), keychain.get_session()
    if api_hash and session:
        await _revoke(ui, session, api_id, api_hash)
    keychain.clear()
    ui.ok(SECRETS_CLEARED)


def _unusable_config_api_id(e: ToolError) -> int | None:
    """api_id of a v1 or tampered config, which `folders` can still repair after login; None otherwise."""
    if not isinstance(e.__cause__, (ConfigOutdated, ConfigTampered)):
        return None
    try:
        return read_api_id(paths.config_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ConfigError):
        return None


async def _login_then_folders(ui: UI, e: ToolError, api_id: int, method: Literal["qr", "code"]) -> int:
    """Outdated / tampered config: `folders` needs a session and login needs no folders, so log in first."""
    if isinstance(e.__cause__, ConfigOutdated):
        ui.say("Old config format (v1): after login the folder picker opens and updates the config.")
    else:
        ui.say("After login the folder picker opens to rewrite the config.")  # folders explains the tampering
    try:
        key = keychain.get_or_create_config_key()
        result = await login(ui, api_id, method=method)
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    except LoginFailed:
        return 1
    if result.api_id is not None:
        # The old file still names the rejected api_id: start a fresh signed config with the new one.
        write_config(paths.config_path(), Config(api_id=result.api_id, account_id=result.account_id), key)
    from .folders import run_folders  # local import: folders imports from this package too

    return await run_folders(ui)


async def run_login(ui: UI, *, method: Literal["qr", "code"] = "qr") -> int:
    store = load_store()
    try:
        cfg = store.current()
        key = keychain.get_or_create_config_key()
        result = await login(ui, cfg.api_id, method=method, previous_account=cfg.account_id)
    except ToolError as e:
        api_id = _unusable_config_api_id(e)
        if api_id is not None:
            return await _login_then_folders(ui, e, api_id, method)
        ui.fail(str(e))  # no/broken config: the message already names the fix (setup)
        return 1
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    except LoginFailed:
        return 1
    updated = dataclasses.replace(
        cfg,
        api_id=result.api_id or cfg.api_id,
        account_id=result.account_id,
        folders=() if result.changed_account else cfg.folders,
    )
    if updated != cfg:
        write_config(paths.config_path(), updated, key)
    if result.changed_account:
        from .folders import run_folders  # local import: folders imports from this package too

        return await run_folders(ui)
    return 0


async def run_logout(ui: UI) -> int:
    store = load_store()
    try:
        cfg = store.current()
    except ToolError:
        cfg = None
    try:
        if cfg is None:
            ui.warn("Config unavailable — the session on the Telegram server was not ended; end it manually in Devices")
            keychain.clear()
            ui.ok(SECRETS_CLEARED)
            return 0
        await logout(ui, cfg.api_id)
        # keychain.clear() also dropped the config signing key; re-sign so the config stays valid.
        write_config(paths.config_path(), cfg, keychain.get_or_create_config_key())
    except SecretStoreUnavailable:
        ui.fail(format_problem(NO_SECRET_STORE))
        return 1
    return 0
