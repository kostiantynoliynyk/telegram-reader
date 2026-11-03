"""Guard: the package must never call anything that changes state in Telegram."""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "telegram_reader"

FORBIDDEN = re.compile(
    r"\.(send_\w*|edit_\w*|delete_\w*|forward_\w*|pin_\w*|unpin_\w*|read_acknowledge|mark_read"
    r"|respond|reply|click|action|inline_query|kick_participant|upload_file|download_\w*)\s*\("
)
ALLOWED_REQUESTS = {"GetDialogFiltersRequest", "GetForumTopicsRequest", "GetPeerDialogsRequest", "SearchRequest"}
# Calls that match FORBIDDEN but do not touch Telegram.
ALLOWED_CALLS = (
    "keyring.delete_password(",
    "client.send_code_request(",  # login only, on a separate plain client
)


def sources():
    files = list(SRC.rglob("*.py"))
    assert files, "no sources found"
    return files


def test_no_mutating_calls():
    for f in sources():
        text = f.read_text(encoding="utf-8")
        for allowed in ALLOWED_CALLS:
            text = text.replace(allowed, "")
        assert not FORBIDDEN.search(text), f


def test_only_allowed_raw_requests():
    for f in sources():
        # names inside string literals (the runtime deny-list) are not requests being made
        used = re.findall(r"(?<![\"'\w])(\w+Request)\b(?![\"'])", f.read_text(encoding="utf-8"))
        assert set(used) <= ALLOWED_REQUESTS, f


def test_guard_catches_a_mutating_call():
    assert FORBIDDEN.search("await client.send_message(chat, 'hi')")
    assert FORBIDDEN.search("await client.send_read_acknowledge(chat)")


def test_server_never_lists_dialogs():
    for f in sources():
        text = f.read_text(encoding="utf-8")
        assert "iter_dialogs(" not in text and "get_dialogs(" not in text, f
