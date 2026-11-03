from dataclasses import replace

import pytest

from telegram_reader.config import (
    Config,
    ConfigError,
    ConfigOutdated,
    ConfigTampered,
    FolderRef,
    LegacyConfig,
    dump_config,
    parse_config,
    parse_legacy,
    signature,
    write_config,
)
from telegram_reader.features import FEATURES, Feature

KEY = b"k" * 32
CFG = Config(api_id=1, account_id=42, folders=(FolderRef(3, "Work"),), features=frozenset())


def test_roundtrip():
    assert parse_config(dump_config(CFG, KEY), KEY) == CFG


def test_tampered_folders_rejected():
    text = dump_config(CFG, KEY).replace("id = 3", "id = 4")
    with pytest.raises(ConfigTampered):
        parse_config(text, KEY)


def test_missing_signature_rejected():
    text = dump_config(CFG, KEY).split("[signature]")[0]
    with pytest.raises(ConfigTampered):
        parse_config(text, KEY)


def test_limits_not_signed_but_validated():
    text = dump_config(CFG, KEY).replace("max_messages = 200", "max_messages = 5000")
    with pytest.raises(ConfigError, match="limits.max_messages"):
        parse_config(text, KEY)


def test_limits_change_within_range_keeps_signature():
    text = dump_config(CFG, KEY).replace("max_messages = 200", "max_messages = 50")
    assert parse_config(text, KEY).max_messages == 50


def test_v1_is_outdated():
    with pytest.raises(ConfigOutdated):
        parse_config('[telegram]\napi_id = 1\n[access]\nfolders = ["Work"]\n', KEY)


def test_wrong_key_rejected():
    with pytest.raises(ConfigTampered):
        parse_config(dump_config(CFG, KEY), b"x" * 32)


def test_parse_legacy():
    legacy = parse_legacy('[telegram]\napi_id = 7\n[access]\nfolders = ["Work"]\nchats = ["X"]\n')
    assert legacy == LegacyConfig(api_id=7, folder_names=("Work",), had_chats=True)


def test_parse_legacy_no_chats():
    legacy = parse_legacy('[telegram]\napi_id = 7\n[access]\nfolders = ["Work"]\n')
    assert legacy.had_chats is False


def test_unavailable_feature_cannot_be_enabled():
    with pytest.raises(ConfigError, match="features.write"):
        dump_config(replace(CFG, features=frozenset({"write"})), KEY)


def test_unknown_feature_rejected_on_parse():
    text = dump_config(CFG, KEY).replace("[features]", "[features]\nbogus = true")
    with pytest.raises(ConfigError, match="features.bogus"):
        parse_config(text, KEY)


def test_write_config_is_atomic_and_private(tmp_path):
    path = tmp_path / "config.toml"
    write_config(path, CFG, KEY)
    assert parse_config(path.read_text(encoding="utf-8"), KEY) == CFG
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_dump_contains_write_false_and_roundtrips():
    text = dump_config(CFG, KEY)
    assert "write = false" in text
    assert parse_config(text, KEY) == CFG


def test_handwritten_spec_style_file_parses():
    sig = signature(CFG, KEY)
    text = (
        "version = 2\n[telegram]\napi_id = 1\naccount_id = 42\n"
        '[access]\nfolders = [{ id = 3, title = "Work" }]\n'
        f'[features]\nwrite = false\n[signature]\nhmac = "{sig}"\n'
    )
    assert parse_config(text, KEY) == CFG


@pytest.mark.parametrize("bad", ['"Ї"', "5", '""', '"zz"'])
def test_malformed_signature_is_tampered(bad):
    head = dump_config(CFG, KEY).split("[signature]")[0]
    with pytest.raises(ConfigTampered):
        parse_config(head + f"[signature]\nhmac = {bad}\n", KEY)


@pytest.mark.parametrize(
    "old,new",
    [("account_id = 42", "account_id = 43"), ("Work", "Other")],
)
def test_tampered_fields_rejected(old, new):
    with pytest.raises(ConfigTampered):
        parse_config(dump_config(CFG, KEY).replace(old, new), KEY)


def test_flipped_feature_flag_rejected(monkeypatch):
    monkeypatch.setitem(FEATURES, "demo", Feature("demo", "Demo", "d", "low", True))
    text = dump_config(CFG, KEY)
    assert "demo = false" in text
    with pytest.raises(ConfigTampered):
        parse_config(text.replace("demo = false", "demo = true"), KEY)


def test_download_max_mb_default():
    assert CFG.download_max_mb == 50
    assert parse_config(dump_config(CFG, KEY), KEY).download_max_mb == 50


@pytest.mark.parametrize("value", [0, 2001])
def test_download_max_mb_out_of_range(value):
    text = dump_config(CFG, KEY).replace("download_max_mb = 50", f"download_max_mb = {value}")
    with pytest.raises(ConfigError, match="limits.download_max_mb"):
        parse_config(text, KEY)


def test_download_max_mb_roundtrip_and_unsigned():
    cfg = replace(CFG, download_max_mb=7)
    assert parse_config(dump_config(cfg, KEY), KEY) == cfg
    assert signature(cfg, KEY) == signature(CFG, KEY)
