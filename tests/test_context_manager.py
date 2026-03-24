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


def test_context_manager_separates_chat_storage(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path)

    manager.append_turn(ConversationTurn("human", "user", "chat one", chat_id=100))
    manager.append_turn(ConversationTurn("human", "user", "chat two", chat_id=200))

    chat_one_path = tmp_path / "context" / "chat_100.md"
    chat_two_path = tmp_path / "context" / "chat_200.md"

    assert chat_one_path.exists()
    assert chat_two_path.exists()
    assert "chat one" in chat_one_path.read_text(encoding="utf-8")
    assert "chat two" not in chat_one_path.read_text(encoding="utf-8")
    assert [turn.text for turn in manager.load_recent_context(5, chat_id=100)] == ["chat one"]
    assert [turn.text for turn in manager.load_recent_context(5, chat_id=200)] == ["chat two"]


def test_context_manager_loads_chat_scoped_context_from_legacy_shared_file(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path)
    now = datetime(2026, 3, 23, tzinfo=timezone.utc)
    manager._atomic_write(
        path,
        "\n\n".join(
            [
                ConversationTurn("human", "user", "one", created_at=now, chat_id=1).as_markdown_block().rstrip(),
                ConversationTurn("human", "user", "two", created_at=now, chat_id=2).as_markdown_block().rstrip(),
                ConversationTurn("bot", "ClaudeCodeBot", "one-reply", created_at=now, chat_id=1).as_markdown_block().rstrip(),
            ]
        )
        + "\n",
    )

    recent = manager.load_recent_context(5, chat_id=1)

    assert [turn.text for turn in recent] == ["one", "one-reply"]


def test_context_manager_uses_configurable_chat_path_template(tmp_path: Path) -> None:
    path = tmp_path / "context.md"
    manager = ContextManager(path, chat_path_template="chat-logs/{chat_id}.history.md")

    manager.append_turn(ConversationTurn("human", "user", "templated", chat_id=33))

    chat_path = tmp_path / "chat-logs" / "33.history.md"
    assert chat_path.exists()
    assert "templated" in chat_path.read_text(encoding="utf-8")


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
