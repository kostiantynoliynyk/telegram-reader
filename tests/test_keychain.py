import keyring
import pytest
from keyring.errors import KeyringError, NoKeyringError

from telegram_reader import keychain
from telegram_reader.keychain import SecretStoreUnavailable


def test_check_backend_ok(fake_keyring):
    keychain.check_backend()
    assert fake_keyring == {}


@pytest.mark.parametrize("exc", [KeyringError, NoKeyringError])
def test_check_backend_raises_when_keyring_fails(monkeypatch, exc):
    def boom(*a):
        raise exc("nope")

    monkeypatch.setattr(keyring, "set_password", boom)
    with pytest.raises(SecretStoreUnavailable):
        keychain.check_backend()


def test_get_raises_unavailable(monkeypatch):
    def boom(*a):
        raise KeyringError("locked")

    monkeypatch.setattr(keyring, "get_password", boom)
    with pytest.raises(SecretStoreUnavailable):
        keychain.get_session()


def test_config_key_created_once(fake_keyring):
    assert keychain.get_config_key() is None
    a = keychain.get_or_create_config_key()
    b = keychain.get_or_create_config_key()
    assert a == b and len(a) == 32
    assert keychain.get_config_key() == a


def test_clear_removes_config_key(fake_keyring):
    keychain.get_or_create_config_key()
    keychain.set_session("s")
    keychain.clear()
    assert fake_keyring == {}


@pytest.mark.parametrize("bad", ["zz-not-hex", "abcd"])
def test_malformed_config_key_is_none(fake_keyring, bad):
    fake_keyring[("telegram-reader", "config_key")] = bad
    assert keychain.get_config_key() is None


def test_check_backend_detects_readback_mismatch(monkeypatch):
    monkeypatch.setattr(keyring, "set_password", lambda *a: None)
    monkeypatch.setattr(keyring, "get_password", lambda *a: None)
    with pytest.raises(SecretStoreUnavailable):
        keychain.check_backend()
