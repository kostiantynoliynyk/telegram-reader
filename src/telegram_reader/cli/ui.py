"""Terminal UI abstraction: commands talk to `UI`, tests substitute a fake."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import qrcode
import questionary
from rich.console import Console


class Cancelled(Exception):
    """The user aborted (Ctrl+C / Esc) at a prompt."""


@dataclass(frozen=True)
class Choice:
    title: str
    value: Any
    checked: bool = False
    disabled: str | None = None


class UI(Protocol):
    def step(self, n: int, total: int, title: str) -> None: ...
    def say(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def fail(self, text: str) -> None: ...
    def ok(self, text: str) -> None: ...
    async def ask(
        self, prompt: str, *, validate: Callable[[str], str | None] | None = None, secret: bool = False
    ) -> str: ...
    async def confirm(self, prompt: str, default: bool = True) -> bool: ...
    async def select(self, prompt: str, choices: list[Choice]) -> Any: ...
    async def checkbox(self, prompt: str, choices: list[Choice]) -> list[Any]: ...
    def qr(self, url: str) -> None: ...
    async def wait(self, seconds: int, prompt: str) -> bool: ...


def _answer(value: Any) -> Any:
    if value is None:  # questionary returns None on Ctrl+C
        raise Cancelled
    return value


def _choices(choices: list[Choice]) -> list[questionary.Choice]:
    return [questionary.Choice(c.title, value=c.value, checked=c.checked, disabled=c.disabled) for c in choices]


class RichUI:
    def __init__(self) -> None:
        self._console = Console()

    def step(self, n: int, total: int, title: str) -> None:
        self._console.print(f"\n[bold]Step {n} of {total}.[/bold] {title}")

    def say(self, text: str) -> None:
        self._console.print(text, markup=False)

    def warn(self, text: str) -> None:
        self._console.print(f"⚠ {text}", style="yellow", markup=False)

    def fail(self, text: str) -> None:
        self._console.print(text, style="red", markup=False)

    def ok(self, text: str) -> None:
        self._console.print(f"✓ {text}", style="green", markup=False)

    async def ask(
        self, prompt: str, *, validate: Callable[[str], str | None] | None = None, secret: bool = False
    ) -> str:
        field = questionary.password if secret else questionary.text
        while True:
            value = _answer(await field(prompt).ask_async())
            error = validate(value) if validate else None
            if error is None:
                return value
            self.fail(error)

    async def confirm(self, prompt: str, default: bool = True) -> bool:
        return bool(_answer(await questionary.confirm(prompt, default=default).ask_async()))

    async def select(self, prompt: str, choices: list[Choice]) -> Any:
        return _answer(await questionary.select(prompt, choices=_choices(choices)).ask_async())

    async def checkbox(self, prompt: str, choices: list[Choice]) -> list[Any]:
        if all(c.disabled for c in choices):
            # questionary's checkbox crashes when nothing is selectable: just show the list.
            self.say(prompt + ":")
            for c in choices:
                self.say(f"  {c.title} ({c.disabled})")
            return [c.value for c in choices if c.checked]
        return _answer(await questionary.checkbox(prompt, choices=_choices(choices)).ask_async())

    def qr(self, url: str) -> None:
        code = qrcode.QRCode(border=1)
        code.add_data(url)
        code.print_ascii(tty=sys.stdout.isatty(), invert=not sys.stdout.isatty())

    async def wait(self, seconds: int, prompt: str) -> bool:
        """Count down; True if the wait finished, False if the user chose to quit (Ctrl+C)."""
        try:
            for left in range(seconds, 0, -1):
                self._console.print(f"{prompt} {left} s (Ctrl+C to quit)", end="\r", markup=False)
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._console.print()
            return False
        self._console.print(" " * 60, end="\r")
        return True
