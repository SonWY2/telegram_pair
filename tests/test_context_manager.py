from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from telegram_pair.context_manager import ContextManager, format_recent_context
from telegram_pair.models import ConversationTurn


def test_context_manager_creates_file_lazily(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path)

    manager.append_turn(ConversationTurn(speaker_type="human", speaker_name="user", text="hello"))

    assert path.exists()
    contents = path.read_text(encoding="utf-8")
    assert "human:user" in contents
    assert "hello" in contents


def test_context_manager_loads_recent_turns(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path)
    now = datetime(2026, 3, 23, tzinfo=timezone.utc)
    turns = [
        ConversationTurn("human", "user", "first", created_at=now),
        ConversationTurn("bot", "ClaudeCodeBot", "second", created_at=now),
        ConversationTurn("bot", "CodexPairBot", "third", created_at=now),
    ]

    manager.append_turns(turns)
    recent = manager.load_recent_context(2)

    assert [turn.text for turn in recent] == ["second", "third"]


def test_context_manager_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path)

    manager.append_turn(ConversationTurn("human", "user", "hello"))

    assert path.exists()
    assert not (tmp_path / "context.md.tmp").exists()


def test_format_recent_context_renders_blocks() -> None:
    rendered = format_recent_context(
        [
            ConversationTurn("human", "user", "hello"),
            ConversationTurn("bot", "ClaudeCodeBot", "world"),
        ]
    )

    assert "[human:user]" in rendered
    assert "[bot:ClaudeCodeBot]" in rendered
