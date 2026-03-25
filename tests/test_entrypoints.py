from __future__ import annotations

from pathlib import Path


def test_runtime_console_scripts_are_declared() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert 'telegram-pair = "telegram_pair.main:main"' in text
    assert 'tpair = "telegram_pair.main:main"' in text
