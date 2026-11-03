import sys

import pytest

from telegram_reader import paths
from telegram_reader.cli import messages
from telegram_reader.cli.common import NotInteractive, require_tty, run
from telegram_reader.cli.messages import Problem, format_problem
from telegram_reader.cli.ui import Cancelled
from fake_ui import FakeUI


def _tty(monkeypatch, value: bool):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: value)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: value)


async def _ok(ui):
    return 0


def test_run_refuses_without_tty(monkeypatch, capsys):
    _tty(monkeypatch, False)
    assert run(_ok, interactive=True, ui=FakeUI()) == 2
    assert "only works in a terminal" in capsys.readouterr().out


def test_require_tty_raises_when_only_stdout_is_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with pytest.raises(NotInteractive):
        require_tty()


def test_status_allowed_without_tty(monkeypatch):
    _tty(monkeypatch, False)
    assert run(_ok, interactive=False, ui=FakeUI()) == 0


def test_interactive_runs_with_tty(monkeypatch):
    _tty(monkeypatch, True)
    assert run(_ok, interactive=True, ui=FakeUI()) == 0


def test_cancel_returns_130_and_says_cancelled(monkeypatch, capsys):
    async def cmd(ui):
        raise Cancelled

    assert run(cmd, interactive=False, ui=FakeUI()) == 130
    out = capsys.readouterr().out
    # login may already have stored a session before a later step was cancelled
    assert "Cancelled." in out and "nothing changed" not in out


def test_unexpected_error_points_to_log(monkeypatch, capsys, tmp_path):
    log = tmp_path / "logs" / "tr.log"
    monkeypatch.setattr(paths, "log_path", lambda: log)

    async def cmd(ui):
        raise RuntimeError("boom-secret")

    assert run(cmd, interactive=False, ui=FakeUI()) == 1
    out = capsys.readouterr()
    assert f"Unexpected error. Details: {log}" in out.out
    assert "Traceback" not in out.out + out.err and "boom-secret" not in out.out + out.err
    assert "boom-secret" in log.read_text()
    assert log.stat().st_mode & 0o777 == 0o600


def test_format_problem_three_parts():
    assert format_problem(Problem("a", "b", "c")) == "✗ a\nWhy: b\nWhat to do: c"


def test_every_problem_has_all_parts():
    problems = [p for p in vars(messages).values() if isinstance(p, Problem)]
    assert len(problems) == 13  # FOLDER_GONE removed: list_chats reports vanished folders
    for p in problems:
        assert p.what and p.why and p.todo


def test_flood_wait_takes_seconds():
    assert "30 s" in messages.FLOOD_WAIT.what.format(seconds=30)


async def test_fake_ui_empty_queue_asserts():
    with pytest.raises(AssertionError):
        await FakeUI([]).confirm("?")


async def test_fake_ui_ask_repeats_until_valid():
    ui = FakeUI(["bad", "good"])
    assert await ui.ask("p", validate=lambda v: None if v == "good" else "no") == "good"
    assert ("fail", "no") in ui.lines
