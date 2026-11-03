"""Rendering and phishing checks for links found in messages (untrusted input)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import LinkInfo
from .sanitize import clean, clip

URL_MAX = 2048
LINKS_PER_MESSAGE = 20
ANCHOR_MAX = 64  # same limit format.py uses for names; not imported to avoid a cycle
DANGEROUS_HIDDEN = "[link with a dangerous scheme hidden]"

# Only these schemes (or none) are shown; anything else could trigger a local handler.
_ALLOWED_SCHEMES = frozenset({"http", "https", "tg"})
# "host:port" without a scheme: a real hostname before the colon and a port right after it.
_HOST = re.compile(r"(?:localhost|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})", re.IGNORECASE)
_PORT_REST = re.compile(r"\d{1,5}(?:[/?#]|$)")
_SPACE_OR_CONTROL = re.compile(r"[\s\x00-\x1f\x7f]+")
_DOMAIN_LIKE = re.compile(r"^(https?://)?([\w-]+\.)+[a-z]{2,}(/\S*)?$", re.IGNORECASE)


def _flat_url(url: str) -> str:
    return _SPACE_OR_CONTROL.sub(" ", clean(url)).strip()


def _scheme_allowed(url: str) -> bool:
    """Allowlist check; raises ValueError for URLs urlsplit cannot parse (fail closed in callers)."""
    # Browsers ignore whitespace and control characters inside a scheme ("java\nscript:").
    compact = _SPACE_OR_CONTROL.sub("", url)
    scheme = urlsplit(compact).scheme.lower()
    if not scheme or scheme in _ALLOWED_SCHEMES:
        return True
    # "example.com:8080/x" and "localhost:8080" have no scheme, only a port.
    return bool(_HOST.fullmatch(scheme) and _PORT_REST.match(compact[len(scheme) + 1 :]))


def render_link(link: LinkInfo) -> str:
    """`url` for a visible link, `«anchor» → url` for a hidden one; dangerous schemes are hidden."""
    url = _flat_url(link.url)
    try:
        allowed = _scheme_allowed(url)
    except ValueError:  # e.g. "https://[evil": hide rather than fail the whole response
        allowed = False
    if not allowed:
        return DANGEROUS_HIDDEN
    if len(url) > URL_MAX:
        url = url[: URL_MAX - 1] + "…"
    if link.anchor is None:
        return url
    return f"«{clip(link.anchor, ANCHOR_MAX)}» → {url}"


def _host(value: str) -> str:
    host = urlsplit(value if "//" in value else "//" + value).hostname or ""
    host = host.lower()
    return host.removeprefix("www.")


def is_mismatch(link: LinkInfo) -> bool:
    """True when the anchor looks like a domain/URL but the link points to another host."""
    if link.anchor is None:
        return False
    anchor = clean(link.anchor).strip()
    if not _DOMAIN_LIKE.match(anchor):
        return False
    try:
        a = _host(anchor).encode("idna")
        u = _host(_flat_url(link.url)).encode("idna")
    except ValueError:  # UnicodeError (bad IDNA) or urlsplit failure
        return True
    return not (u == a or u.endswith(b"." + a))
