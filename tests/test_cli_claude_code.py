import subprocess

import pytest

from telegram_reader.cli import claude_code as cc


class Run:
    def __init__(self, returncode=0, stderr=b""):
        self.calls = []
        self.returncode, self.stderr = returncode, stderr

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if kw.get("check") and self.returncode:
            raise subprocess.CalledProcessError(self.returncode, argv, stderr=self.stderr)
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


def which(table):
    return lambda name: table.get(name)


def test_register_uses_user_scope_and_absolute_path(monkeypatch):
    run = Run()
    monkeypatch.setattr(cc.subprocess, "run", run)
    monkeypatch.setattr(cc.shutil, "which", which({"telegram-reader": "/abs/telegram-reader"}))
    cc.register("/bin/claude")
    argv, kw = run.calls[0]
    assert argv == ["/bin/claude", "mcp", "add", "--scope", "user", "telegram-reader", "--", "/abs/telegram-reader", "serve"]
    assert kw["check"] and kw["capture_output"]


def test_server_command_falls_back_to_python_module(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", which({}))
    monkeypatch.setattr(cc.sys, "executable", "/py")
    assert cc.server_command() == ["/py", "-m", "telegram_reader", "serve"]


def test_register_failure_surfaces_stderr(monkeypatch):
    monkeypatch.setattr(cc.subprocess, "run", Run(1, b"boom happened"))
    monkeypatch.setattr(cc.shutil, "which", which({}))
    with pytest.raises(RuntimeError, match="boom happened"):
        cc.register("claude")


@pytest.mark.parametrize("code,expected", [(0, True), (1, False)])
def test_is_registered(monkeypatch, code, expected):
    run = Run(code)
    monkeypatch.setattr(cc.subprocess, "run", run)
    assert cc.is_registered("claude") is expected
    assert run.calls[0][0] == ["claude", "mcp", "get", "telegram-reader"]


def test_manual_command_is_shell_quoted(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", which({"telegram-reader": "/my dir/telegram-reader"}))
    assert cc.manual_command() == "claude mcp add --scope user telegram-reader -- '/my dir/telegram-reader' serve"


def _raising(exc):
    def run(argv, **kw):
        assert kw.get("timeout") == cc.TIMEOUT_SECONDS
        raise exc

    return run


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(["claude"], 30), OSError("exec format error")])
def test_is_registered_survives_timeout_and_oserror(monkeypatch, exc):
    monkeypatch.setattr(cc.subprocess, "run", _raising(exc))
    assert cc.is_registered("claude") is False


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(["claude"], 30), OSError("exec format error")])
def test_register_timeout_and_oserror_are_runtime_errors(monkeypatch, exc):
    monkeypatch.setattr(cc.subprocess, "run", _raising(exc))
    monkeypatch.setattr(cc.shutil, "which", which({}))
    with pytest.raises(RuntimeError, match="claude mcp add"):
        cc.register("claude")


def test_subprocess_calls_have_timeout(monkeypatch):
    run = Run()
    monkeypatch.setattr(cc.subprocess, "run", run)
    monkeypatch.setattr(cc.shutil, "which", which({}))
    cc.is_registered("claude")
    cc.register("claude")
    assert [kw["timeout"] for _, kw in run.calls] == [cc.TIMEOUT_SECONDS, cc.TIMEOUT_SECONDS]
