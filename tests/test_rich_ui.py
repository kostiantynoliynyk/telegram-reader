"""Unmocked smoke test: RichUI prompts must work inside a running event loop."""

import asyncio

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from telegram_reader.cli.ui import RichUI


def _drive(keys: str, coro_fn):
    async def main():
        return await coro_fn(RichUI())

    with create_pipe_input() as inp:
        inp.send_text(keys)
        with create_app_session(input=inp, output=DummyOutput()):
            return asyncio.run(main())


def test_ask_inside_running_loop():
    assert _drive("abc\r", lambda ui: ui.ask("x")) == "abc"


def test_confirm_inside_running_loop():
    assert _drive("\r", lambda ui: ui.confirm("x")) is True


def test_ask_reasks_until_valid():
    v = lambda s: None if s == "ok" else "bad"  # noqa: E731
    assert _drive("no\rok\r", lambda ui: ui.ask("x", validate=v)) == "ok"


def test_checkbox_with_only_disabled_choices_does_not_crash():
    from telegram_reader.cli.ui import Choice

    choices = [Choice("Write", "write", disabled="soon")]
    assert _drive("", lambda ui: ui.checkbox("Choose features", choices)) == []


def test_checkbox_selects_enabled_choice():
    from telegram_reader.cli.ui import Choice

    choices = [Choice("A", "a"), Choice("B", "b", disabled="soon")]
    assert _drive(" \r", lambda ui: ui.checkbox("x", choices)) == ["a"]
