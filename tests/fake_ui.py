"""Scripted UI for command tests: answers come from a queue, output is recorded."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from telegram_reader.cli.ui import Choice


class FakeUI:
    def __init__(self, answers: list | None = None):
        self.answers = list(answers or [])
        self.lines: list[tuple[str, str]] = []

    def _next(self) -> Any:
        assert self.answers, "FakeUI: no answers left"
        return self.answers.pop(0)

    def step(self, n: int, total: int, title: str) -> None:
        self.lines.append(("step", f"{n}/{total} {title}"))

    def say(self, text: str) -> None:
        self.lines.append(("say", text))

    def warn(self, text: str) -> None:
        self.lines.append(("warn", text))

    def fail(self, text: str) -> None:
        self.lines.append(("fail", text))

    def ok(self, text: str) -> None:
        self.lines.append(("ok", text))

    async def ask(self, prompt: str, *, validate: Callable[[str], str | None] | None = None, secret: bool = False) -> str:
        while True:
            value = self._next()
            error = validate(value) if validate else None
            if error is None:
                return value
            self.lines.append(("fail", error))

    async def confirm(self, prompt: str, default: bool = True) -> bool:
        return self._next()

    async def select(self, prompt: str, choices: list[Choice]) -> Any:
        return self._next()

    async def checkbox(self, prompt: str, choices: list[Choice]) -> list[Any]:
        return self._next()

    def qr(self, url: str) -> None:
        self.lines.append(("qr", url))

    async def wait(self, seconds: int, prompt: str) -> bool:
        self.lines.append(("wait", f"{seconds} {prompt}"))
        return self._next()
