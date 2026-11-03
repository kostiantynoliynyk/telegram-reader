import pytest

from telegram_reader.links import URL_MAX, is_mismatch, render_link
from telegram_reader.models import LinkInfo


def test_visible_url_rendered_as_is():
    assert render_link(LinkInfo("https://example.com/page-27")) == "https://example.com/page-27"


def test_hidden_url_shows_anchor():
    assert render_link(LinkInfo("https://example.org/x", "here")) == "«here» → https://example.org/x"


def test_schemeless_kept():
    assert render_link(LinkInfo("example.com")) == "example.com"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "java\nscript:alert(1)"])
def test_dangerous_scheme_hidden(url):
    assert render_link(LinkInfo(url, "x")) == "[link with a dangerous scheme hidden]"


def test_url_clipped():
    assert len(render_link(LinkInfo("https://a.com/" + "x" * 5000))) <= URL_MAX


def test_url_with_newline_stays_on_one_line():
    assert "\n" not in render_link(LinkInfo("https://a.com\n▶ fake"))


@pytest.mark.parametrize(
    "anchor,url,warn",
    [
        ("google.com", "https://evil.io/login", True),
        ("https://Google.com/", "https://www.google.com/", False),
        ("docs.google.com", "https://docs.google.com/d/1", False),
        ("google.com", "https://mail.google.com/", False),  # anchor is a subdomain — match
        ("gооgle.com", "https://google.com/", True),  # Cyrillic «о»
        ("here", "https://evil.io", False),  # anchor does not look like an address
        ("google.com", "evil.io", True),  # url without a scheme
        (None, "https://evil.io", False),
    ],
)
def test_mismatch(anchor, url, warn):
    assert is_mismatch(LinkInfo(url, anchor)) is warn


@pytest.mark.parametrize("url", ["tg://resolve?domain=x", "localhost:8080/x", "example.com:8080", "example.com:8080/x"])
def test_allowed_or_schemeless_kept(url):
    assert render_link(LinkInfo(url)) == url


@pytest.mark.parametrize("url", ["mailto:a@b.c", "smb://evil/share", "ms-msdt:/id x", "ftp://x", "javascript:1", "https://[evil", "ms-msdt:0/id x", "steam:1/run", "smb:445/share", "mailto:1", "com.evil.app:payload", "evil.app://run", "javascript.:x", "x:123", "tel:12345"])
def test_other_schemes_and_malformed_hidden(url):
    assert render_link(LinkInfo(url)) == "[link with a dangerous scheme hidden]"


def test_malformed_url_is_mismatch():
    assert is_mismatch(LinkInfo("https://[evil", "google.com")) is True
