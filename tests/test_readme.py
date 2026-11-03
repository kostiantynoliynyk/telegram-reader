"""README promises that the code has to keep."""

from pathlib import Path


README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def test_readme_documents_v1_upgrade_path():
    section = README.split("## 6. Updating", 1)[1].split("## 7.", 1)[0]
    assert "after upgrading from v1 run `telegram-reader folders`" in section.replace("After", "after")
    assert "telegram-reader status" in section


def test_readme_cancel_wording_matches_cli():
    from telegram_reader.cli import common

    source = Path(common.__file__).read_text(encoding="utf-8")
    assert "Cancelled. Unfinished steps were not saved." in source
    assert "«Cancelled. Unfinished steps were not saved.»" in README
