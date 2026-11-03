import os
from dataclasses import replace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from telegram_reader import store as store_module
from telegram_reader.config import Config, FolderRef, write_config
from telegram_reader.keychain import SecretStoreUnavailable
from telegram_reader.store import ConfigStore

KEY = b"k" * 32
CFG = Config(api_id=1, account_id=42, folders=(FolderRef(3, "Work"),), features=frozenset())
CFG2 = replace(CFG, folders=(FolderRef(4, "Other"),))


def _bump(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_store_reloads_on_mtime_change(tmp_path):
    p = tmp_path / "c.toml"
    write_config(p, CFG, KEY)
    s = ConfigStore(p, lambda: KEY)
    assert s.current() == CFG
    write_config(p, CFG2, KEY)
    _bump(p)
    assert s.current() == CFG2


def test_store_does_not_reparse_unchanged(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    write_config(p, CFG, KEY)
    calls = []
    real = store_module.parse_config
    monkeypatch.setattr(store_module, "parse_config", lambda t, k: calls.append(1) or real(t, k))
    s = ConfigStore(p, lambda: KEY)
    s.current()
    s.current()
    assert len(calls) == 1


def test_store_missing_file_is_explained(tmp_path):
    with pytest.raises(ToolError, match="Config not found — run telegram-reader setup"):
        ConfigStore(tmp_path / "none.toml", lambda: KEY).current()


def test_store_tampered_fails_closed_after_good_read(tmp_path):
    p = tmp_path / "c.toml"
    write_config(p, CFG, KEY)
    s = ConfigStore(p, lambda: KEY)
    s.current()
    p.write_text(p.read_text().replace("id = 3", "id = 4"))
    _bump(p)
    with pytest.raises(ToolError, match="changed outside"):
        s.current()
    with pytest.raises(ToolError, match="changed outside"):
        s.current()


def test_store_garbage_file_is_config_error(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("not = [valid")
    with pytest.raises(ToolError, match="Config error"):
        ConfigStore(p, lambda: KEY).current()


def test_store_keyring_error_is_explained(tmp_path):
    p = tmp_path / "c.toml"
    write_config(p, CFG, KEY)

    def broken():
        raise SecretStoreUnavailable()

    with pytest.raises(ToolError, match="secret store"):
        ConfigStore(p, broken).current()


def test_store_recovers_after_error(tmp_path):
    p = tmp_path / "c.toml"
    s = ConfigStore(p, lambda: KEY)
    with pytest.raises(ToolError):
        s.current()
    write_config(p, CFG, KEY)
    assert s.current() == CFG


def test_store_path_is_directory(tmp_path):
    d = tmp_path / "c.toml"
    d.mkdir()
    with pytest.raises(ToolError, match="Config error"):
        ConfigStore(d, lambda: KEY).current()


def test_store_invalid_utf8(tmp_path):
    p = tmp_path / "c.toml"
    p.write_bytes(b"\xff\xfe\x80")
    with pytest.raises(ToolError, match="Config error"):
        ConfigStore(p, lambda: KEY).current()
