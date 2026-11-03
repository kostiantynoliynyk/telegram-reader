import pytest
from fake_ui import FakeUI
from fakes import FakeTg

from telegram_reader import keychain, paths
from telegram_reader.cli import folders as fm
from telegram_reader.cli.ui import Cancelled
from telegram_reader.config import Config, FolderRef, parse_config, write_config
from telegram_reader.errors import LoginRequired
from telegram_reader.models import FolderInfo


def F(id, title, peers=(1, 2), auto=False):
    return FolderInfo(id=id, title=title, peer_ids=tuple(peers), has_auto_rules=auto)


def text(ui):
    return "\n".join(t for _, t in ui.lines)


class CaptureUI(FakeUI):
    def __init__(self, answers=None):
        super().__init__(answers)
        self.checkbox_choices = []

    async def checkbox(self, prompt, choices):
        self.checkbox_choices.append(choices)
        return await super().checkbox(prompt, choices)


async def test_choose_folders_preselects_current():
    ui = CaptureUI([[2]])
    tg = FakeTg(folders=[F(1, "A"), F(2, "B")])
    cfg = await fm.choose_folders(ui, tg, Config(api_id=1, folders=(FolderRef(2, "B"),)))
    assert [(c.value, c.checked) for c in ui.checkbox_choices[0]] == [(1, False), (2, True)]
    assert ui.checkbox_choices[0][1].title == "B — 2 chats"
    assert cfg.folders == (FolderRef(2, "B"),)


async def test_empty_selection_is_refused():
    ui = FakeUI([[], [1]])
    cfg = await fm.choose_folders(ui, FakeTg(folders=[F(1, "A")]), Config(api_id=1))
    assert ("warn", "Select at least one folder") in ui.lines
    assert cfg.folders == (FolderRef(1, "A"),)


async def test_no_folders_offers_refresh():
    tg = FakeTg()
    ui = FakeUI([fm.REFRESH, [1]])

    async def refreshed():
        tg.folders = [F(1, "A")]
        return list(tg.folders)

    calls = []
    orig = tg.list_folders

    async def lf():
        calls.append(1)
        if len(calls) == 2:
            tg.folders = [F(1, "A")]
        return await orig()

    tg.list_folders = lf
    cfg = await fm.choose_folders(ui, tg, Config(api_id=1))
    assert "Settings → Folders → Create a folder" in text(ui)
    assert cfg.folders == (FolderRef(1, "A"),)


async def test_no_folders_quit_cancels():
    with pytest.raises(Cancelled):
        await fm.choose_folders(FakeUI([fm.QUIT]), FakeTg(), Config(api_id=1))


async def test_auto_rules_marked():
    ui = CaptureUI([[1]])
    await fm.choose_folders(ui, FakeTg(folders=[F(1, "A", auto=True)]), Config(api_id=1))
    assert ui.checkbox_choices[0][0].title.endswith(" ⚠ auto rules are ignored")


async def test_vanished_folder_shown_disabled():
    ui = CaptureUI([[1]])
    cfg = await fm.choose_folders(
        ui, FakeTg(folders=[F(1, "A")]), Config(api_id=1, folders=(FolderRef(9, "Old"),))
    )
    gone = ui.checkbox_choices[0][1]
    assert (gone.value, gone.title, gone.disabled) == (9, "Old", "gone")
    assert cfg.folders == (FolderRef(1, "A"),)


# --- run_folders --------------------------------------------------------------


@pytest.fixture
def env(fake_keyring, monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(paths, "migrate_location", lambda: False)
    tg = FakeTg(folders=[F(1, "Work", (10, 11)), F(2, "Team", (11, 12))])
    tg.account_id = 5
    monkeypatch.setattr(fm, "TgClient", lambda api_id: tg)

    def write(cfg):
        write_config(path, cfg, keychain.get_or_create_config_key())

    def read():
        return parse_config(path.read_text(encoding="utf-8"), keychain.get_or_create_config_key())

    from types import SimpleNamespace

    return SimpleNamespace(path=path, tg=tg, write=write, read=read)


LEGACY = """
[telegram]
api_id = 77
[access]
folders = ["Work", "Gone"]
chats = ["x"]
"""


async def test_run_folders_migrates_v1_names_to_ids(env):
    env.path.write_text(LEGACY)
    ui = CaptureUI([[1]])
    assert await fm.run_folders(ui) == 0
    assert [c.checked for c in ui.checkbox_choices[0]] == [True, False]
    cfg = env.read()
    assert (cfg.api_id, cfg.account_id, cfg.folders) == (77, 5, (FolderRef(1, "Work"),))
    assert "«Gone»" in text(ui)


async def test_run_folders_warns_about_dropped_chats(env):
    env.path.write_text(LEGACY)
    ui = FakeUI([[1]])
    await fm.run_folders(ui)
    assert "Chats outside folders are no longer supported — add them to a folder in Telegram" in text(ui)


async def test_run_folders_rewrites_tampered_config(env):
    env.write(Config(api_id=3, account_id=5, folders=(FolderRef(1, "Work"),)))
    env.path.write_text(env.path.read_text().replace('"Work"', '"Evil"'))
    ui = FakeUI([[2]])
    assert await fm.run_folders(ui) == 0
    assert "Config was changed outside telegram-reader" in text(ui)
    cfg = env.read()
    assert (cfg.api_id, cfg.folders) == (3, (FolderRef(2, "Team"),))


async def test_run_folders_without_session_says_login_first(env):
    env.write(Config(api_id=3))
    env.tg.connect_error = LoginRequired()
    ui = FakeUI([])
    assert await fm.run_folders(ui) == 1
    assert "telegram-reader login" in text(ui)


async def test_run_folders_missing_config_points_to_setup(env):
    ui = FakeUI([])
    assert await fm.run_folders(ui) == 1
    assert "setup" in text(ui)


async def test_summary_counts_chats_and_delta(env):
    env.write(Config(api_id=3, account_id=5, folders=(FolderRef(1, "Work"),)))
    ui = FakeUI([[2]])
    assert await fm.run_folders(ui) == 0
    # old chats {10, 11}; new {11, 12}
    assert ("ok", "Done: Claude will see 2 chats from 1 folders (+1 / −1)") in ui.lines


async def test_summary_without_change_has_no_delta(env):
    env.write(Config(api_id=3, account_id=5, folders=(FolderRef(1, "Work"),)))
    ui = FakeUI([[1]])
    await fm.run_folders(ui)
    assert ("ok", "Done: Claude will see 2 chats from 1 folders") in ui.lines


async def test_run_folders_disconnects(env):
    env.write(Config(api_id=3, account_id=5, folders=(FolderRef(1, "Work"),)))
    assert await fm.run_folders(FakeUI([[1]])) == 0
    assert env.tg.calls[-1] == ("disconnect",)


async def test_run_folders_disconnects_on_failure(env):
    env.write(Config(api_id=3))
    env.tg.folders_error = LoginRequired()
    assert await fm.run_folders(FakeUI([])) == 1
    assert env.tg.calls[-1] == ("disconnect",)


async def test_run_folders_revoked_session_says_session_ended(env):
    from telegram_reader.errors import SessionRevoked

    env.write(Config(api_id=3))
    env.tg.connect_error = SessionRevoked()
    ui = FakeUI([])
    assert await fm.run_folders(ui) == 1
    assert "Session ended" in text(ui) and "telegram-reader login" in text(ui)
