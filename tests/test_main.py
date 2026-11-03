import pytest

from telegram_reader import __main__ as m


@pytest.mark.parametrize("argv,cmd", [([], "serve"), (["folders"], "folders"), (["login", "--code"], "login")])
def test_main_dispatch(argv, cmd, monkeypatch):
    calls = []
    monkeypatch.setattr(m, "serve", lambda: calls.append(("serve", None)) or 0)

    def fake_run(command, *, interactive):
        calls.append((command.__name__, interactive))
        return 7

    monkeypatch.setattr(m, "run", fake_run)
    rc = m.main(argv)
    assert calls == [(cmd, None if cmd == "serve" else True)]
    assert rc == (0 if cmd == "serve" else 7)


def test_status_is_not_interactive(monkeypatch):
    seen = {}
    monkeypatch.setattr(m, "run", lambda c, *, interactive: seen.update(i=interactive) or 0)
    m.main(["status"])
    assert seen == {"i": False}


def test_login_passes_method(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "run", lambda c, *, interactive: seen.append(c.keywords) or 0)
    m.main(["login", "--code"])
    m.main(["login"])
    assert seen == [{"method": "code"}, {"method": "qr"}]


def test_setup_dispatches_to_wizard(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "run", lambda c, *, interactive: seen.append((c.__name__, interactive)) or 0)
    m.main(["setup"])
    assert seen == [("setup", True)]


async def test_status_passes_registration_probe(monkeypatch):
    seen = {}

    async def fake(ui, *, registered=None, **kw):
        seen["registered"] = registered
        return 0

    monkeypatch.setattr(m, "run_status", fake)
    monkeypatch.setattr(m, "find_claude", lambda: None)
    await m.status(None)
    assert seen["registered"]() is None
    monkeypatch.setattr(m, "find_claude", lambda: "/c")
    monkeypatch.setattr(m, "is_registered", lambda c: c == "/c")
    assert seen["registered"]() is True


def test_serve_exits_2_on_broken_config(monkeypatch, capsys, tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    class Store:
        def current(self):
            raise ToolError("Config not found")

    monkeypatch.setattr(m, "load_store", lambda: Store())
    assert m.serve() == 2
    assert "Config not found" in capsys.readouterr().err
