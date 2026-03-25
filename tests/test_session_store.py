from __future__ import annotations

import json
from pathlib import Path

from telegram_pair.session_store import SessionRecord, SessionStore


def test_touch_success_persists_session_record(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)

    record = store.touch_success(
        123,
        "CodexPairBot",
        session_id="sess-123",
        transport_kind="codex",
        last_message_id=77,
        last_model="gpt-5.4",
    )

    saved = store.load(123, "CodexPairBot")

    assert record.session_id == "sess-123"
    assert saved is not None
    assert saved.session_id == "sess-123"
    assert saved.transport_kind == "codex"
    assert saved.last_message_id == 77
    assert saved.last_model == "gpt-5.4"
    assert saved.broken is False
    assert store.path_for(123, "CodexPairBot").exists()


def test_mark_broken_preserves_existing_session_id(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.save(
        SessionRecord.fresh(chat_id=1, bot_name="CodexPairBot").with_success(
            session_id="sess-1",
            transport_kind="codex",
            last_message_id=10,
            last_model="gpt-5.4",
        )
    )

    broken = store.mark_broken(1, "CodexPairBot", reason="expired", last_message_id=11)

    assert broken.broken is True
    assert broken.session_id == "sess-1"
    assert broken.broken_reason == "expired"
    assert broken.last_message_id == 11


def test_clear_and_clear_all_remove_session_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.touch_success(1, "ClaudeCodeBot", session_id="claude-1", transport_kind="none", last_message_id=None, last_model=None)
    store.touch_success(1, "CodexPairBot", session_id="codex-1", transport_kind="codex", last_message_id=None, last_model=None)

    assert store.clear(1, "ClaudeCodeBot") is True
    assert store.clear(1, "ClaudeCodeBot") is False
    assert store.clear_all(1, ("ClaudeCodeBot", "CodexPairBot")) == 1
    assert not (store.root / "chat_1").exists()


def test_load_ignores_invalid_json_payloads(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    path = store.path_for(9, "CodexPairBot")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    assert store.load(9, "CodexPairBot") is None


def test_status_lines_report_stateless_active_broken_and_missing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.touch_success(55, "CodexPairBot", session_id="codex-live", transport_kind="codex", last_message_id=3, last_model="gpt-5.4")
    store.mark_broken(55, "GeminiPairBot", reason="expired")

    lines = store.status_lines(
        55,
        ("ClaudeCodeBot", "CodexPairBot", "GeminiPairBot", "OpenCodeBot"),
        stateless_bot_names=frozenset({"ClaudeCodeBot"}),
    )

    assert lines == [
        "현재 세션 상태:",
        "- ClaudeCodeBot: stateless",
        "- CodexPairBot: active (codex-live)",
        "- GeminiPairBot: no active session",
        "- OpenCodeBot: no active session",
    ]


def test_status_lines_report_broken_session_when_session_id_present(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    path = store.path_for(88, "CodexPairBot")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "chat_id": 88,
                "bot_name": "CodexPairBot",
                "session_id": "broken-88",
                "transport_kind": "codex",
                "created_at": "2026-03-25T00:00:00+00:00",
                "updated_at": "2026-03-25T00:01:00+00:00",
                "last_message_id": 2,
                "last_model": "gpt-5.4",
                "broken": True,
                "broken_reason": "expired",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    lines = store.status_lines(
        88,
        ("CodexPairBot",),
        stateless_bot_names=frozenset(),
    )

    assert lines == [
        "현재 세션 상태:",
        "- CodexPairBot: broken (broken-88)",
    ]
