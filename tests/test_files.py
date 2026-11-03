import pytest

from telegram_reader.files import inline_kind, safe_name, sniff_image, target_path
from telegram_reader.models import MediaInfo


def test_safe_name_keeps_name_and_extension():
    assert safe_name(MediaInfo("document", name="Звіт.pdf")) == "Звіт.pdf"


def test_safe_name_strips_path_and_hidden():
    assert safe_name(MediaInfo("document", name="../../.zshrc\u202e")) == "zshrc"


def test_safe_name_strips_windows_path_and_forbidden_chars():
    assert safe_name(MediaInfo("document", name='C:\\x\\a:b*c?"d<e>f|g.txt')) == "abcdefg.txt"


def test_safe_name_truncates_keeping_extension():
    n = safe_name(MediaInfo("document", name="a" * 300 + ".xlsx"))
    assert len(n) == 128 and n.endswith(".xlsx")


def test_safe_name_fallbacks():
    assert safe_name(MediaInfo("photo")) == "photo.jpg"
    assert safe_name(MediaInfo("voice", mime="audio/ogg")) == "voice.oga"
    assert safe_name(MediaInfo("video")) == "video"
    assert safe_name(MediaInfo("document", name="///")) == "file"


def test_safe_name_windows_reserved_and_bare_extension():
    assert safe_name(MediaInfo("document", name="CON.txt")) == "_CON.txt"
    assert safe_name(MediaInfo("document", name="nul")) == "_nul"
    assert safe_name(MediaInfo("document", name="com1.tar.gz")) == "_com1.tar.gz"
    assert safe_name(MediaInfo("document", name=".pdf")) == "file.pdf"


def test_target_path(tmp_path):
    media = MediaInfo("document", name="a.pdf")
    assert target_path(tmp_path, -1001234, 412, media) == tmp_path / "-1001234" / "412-a.pdf"


@pytest.mark.parametrize(
    "media,size,expected",
    [
        (MediaInfo("photo", mime="image/jpeg"), 5 * 1024 * 1024, "image"),
        (MediaInfo("photo", mime="image/jpeg"), 5 * 1024 * 1024 + 1, None),
        (MediaInfo("document", name="x.svg", mime="image/svg+xml"), 100, None),
        (MediaInfo("document", name="log.txt", mime="application/octet-stream"), 100, "text"),
        (MediaInfo("document", name="d.json", mime="application/json"), 200 * 1024 + 1, None),
        (MediaInfo("document", name="a.pdf", mime="application/pdf"), 100, None),
    ],
)
def test_inline_kind(media, size, expected):
    assert inline_kind(media, size) == expected


def test_safe_name_long_extension_is_not_an_extension():
    n = safe_name(MediaInfo("document", name="a" * 140 + "." + "b" * 200))
    assert 0 < len(n) <= 128


@pytest.mark.parametrize("name,ext", [("я" * 150 + ".pdf", ".pdf"), ("漢" * 100 + ".docx", ".docx")])
def test_safe_name_multibyte_fits_byte_limit(name, ext):
    n = safe_name(MediaInfo("document", name=name))
    assert n.endswith(ext) and len(n) <= 128 and len(n.encode("utf-8")) <= 200


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"\x89PNG\r\n\x1a\n....", "image/png"),
        (b"\xff\xd8\xff\xe0....", "image/jpeg"),
        (b"GIF87a....", "image/gif"),
        (b"GIF89a....", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", None),
        (b"\x89PNG", None),
        (b"not an image", None),
        (b"", None),
    ],
)
def test_sniff_image(head, expected):
    assert sniff_image(head) == expected
