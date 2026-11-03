from telegram_reader import paths


def test_config_and_log_paths_are_os_specific(monkeypatch):
    monkeypatch.setattr(paths.platformdirs, "user_config_dir", lambda *a, **k: "/cfg")
    monkeypatch.setattr(paths.platformdirs, "user_log_dir", lambda *a, **k: "/log")
    assert str(paths.config_path()) == "/cfg/config.toml"
    assert str(paths.log_path()) == "/log/telegram-reader.log"


def _setup(tmp_path, monkeypatch):
    legacy = tmp_path / "old" / "config.toml"
    new = tmp_path / "new" / "config.toml"
    monkeypatch.setattr(paths, "LEGACY_CONFIG", legacy)
    monkeypatch.setattr(paths, "config_path", lambda: new)
    return legacy, new


def test_migrate_location_moves_legacy(tmp_path, monkeypatch):
    legacy, new = _setup(tmp_path, monkeypatch)
    legacy.parent.mkdir()
    legacy.write_text("x")
    assert paths.migrate_location() is True
    assert new.read_text() == "x"
    assert not legacy.exists()


def test_migrate_location_keeps_existing_new(tmp_path, monkeypatch):
    legacy, new = _setup(tmp_path, monkeypatch)
    legacy.parent.mkdir()
    new.parent.mkdir()
    legacy.write_text("old")
    new.write_text("new")
    assert paths.migrate_location() is False
    assert new.read_text() == "new"
    assert legacy.read_text() == "old"


def test_migrate_location_noop_when_same_or_absent(tmp_path, monkeypatch):
    legacy, new = _setup(tmp_path, monkeypatch)
    assert paths.migrate_location() is False
    monkeypatch.setattr(paths, "config_path", lambda: legacy)
    legacy.parent.mkdir()
    legacy.write_text("x")
    assert paths.migrate_location() is False
    assert legacy.read_text() == "x"


def test_downloads_dir(monkeypatch):
    monkeypatch.setattr(paths.platformdirs, "user_downloads_dir", lambda *a, **k: "/dl")
    assert str(paths.downloads_dir()) == "/dl/telegram-reader"
