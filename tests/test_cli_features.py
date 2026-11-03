
from fake_ui import FakeUI

from telegram_reader import features, keychain, paths
from telegram_reader.cli import features_cmd as fc
from telegram_reader.cli.ui import Choice
from telegram_reader.config import Config, parse_config, write_config

RISKY = features.Feature("demo", "Demo", "A dangerous thing.", risk="high", available=True)
SOON = features.Feature("soon", "Soon", "Not yet.", risk="low", available=False)


class CaptureUI(FakeUI):
    choices: list[Choice]

    async def checkbox(self, prompt, choices):
        self.choices = choices
        return await super().checkbox(prompt, choices)


async def test_unavailable_feature_disabled_in_picker(monkeypatch):
    monkeypatch.setattr(fc, "FEATURES", {"soon": SOON})
    ui = CaptureUI([[]])
    await fc.choose_features(ui, Config(api_id=1))
    assert ui.choices[0].disabled == "soon"


async def test_high_risk_requires_typed_confirmation(monkeypatch):
    monkeypatch.setattr(fc, "FEATURES", {"demo": RISKY})
    cfg = Config(api_id=1)
    ui = FakeUI([["demo"], "no"])
    assert (await fc.choose_features(ui, cfg)).features == frozenset()
    ui = FakeUI([["demo"], "yes"])
    assert (await fc.choose_features(ui, cfg)).features == frozenset({"demo"})


async def test_already_enabled_high_risk_not_reconfirmed(monkeypatch):
    monkeypatch.setattr(fc, "FEATURES", {"demo": RISKY})
    ui = FakeUI([["demo"]])
    cfg = await fc.choose_features(ui, Config(api_id=1, features=frozenset({"demo"})))
    assert cfg.features == frozenset({"demo"})


async def test_run_features_saves_and_prints_restart_note(fake_keyring, monkeypatch, tmp_path):
    path = tmp_path / "c.toml"
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    write_config(path, Config(api_id=1), keychain.get_or_create_config_key())
    # `demo` must be known to the config layer too

    monkeypatch.setitem(features.FEATURES, "demo", RISKY)
    monkeypatch.setattr(fc, "FEATURES", features.FEATURES)
    ui = FakeUI([["demo"], "yes"])
    assert await fc.run_features(ui) == 0
    saved = parse_config(path.read_text(encoding="utf-8"), keychain.get_or_create_config_key())
    assert saved.features == frozenset({"demo"})
    assert ("say", fc.RESTART_NOTE) in ui.lines


async def test_run_features_without_change_is_silent_about_restart(fake_keyring, monkeypatch, tmp_path):
    path = tmp_path / "c.toml"
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    write_config(path, Config(api_id=1), keychain.get_or_create_config_key())
    ui = FakeUI([[]])
    assert await fc.run_features(ui) == 0
    assert ("say", fc.RESTART_NOTE) not in ui.lines
