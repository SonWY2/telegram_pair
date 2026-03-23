from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
import re
from typing import Iterable

from .models import ConversationTurn


_HEADER_RE = re.compile(
    r"^## (?P<speaker_type>[^:]+):(?P<speaker_name>.+?) @ (?P<timestamp>[^()]+?)(?: \((?P<meta>[^)]*)\))?$"
)


class ContextManager:
    """Persist and load shared conversation history in markdown."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append_turn(self, turn: ConversationTurn) -> None:
        self.append_turns([turn])

    def append_turns(self, turns: Iterable[ConversationTurn]) -> None:
        blocks = [turn.as_markdown_block().rstrip() for turn in turns]
        if not blocks:
            return

        with self._lock:
            existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            body = existing.rstrip()
            if body:
                body += "\n\n"
            body += "\n\n".join(blocks) + "\n"
            self._atomic_write(body)

    def load_recent_context(self, max_turns: int) -> tuple[ConversationTurn, ...]:
        if max_turns <= 0 or not self.path.exists():
            return ()
        text = self.path.read_text(encoding="utf-8")
        parsed = _parse_turns(text)
        return tuple(parsed[-max_turns:])

    def load_recent_context_text(self, max_turns: int) -> str:
        turns = self.load_recent_context(max_turns)
        return format_recent_context(turns)

    def _atomic_write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(self.path)


def format_recent_context(turns: Iterable[ConversationTurn]) -> str:
    rendered: list[str] = []
    for turn in turns:
        speaker = f"{turn.speaker_type}:{turn.speaker_name}"
        rendered.append(f"[{speaker}]\n{turn.text.strip() or '<empty>'}")
    return "\n\n".join(rendered)


def _parse_turns(text: str) -> list[ConversationTurn]:
    if not text.strip():
        return []

    turns: list[ConversationTurn] = []
    chunks = [chunk for chunk in text.split("\n## ") if chunk.strip()]
    for index, chunk in enumerate(chunks):
        normalized = chunk if index == 0 and chunk.startswith("## ") else f"## {chunk}"
        header, _, body = normalized.partition("\n\n")
        match = _HEADER_RE.match(header.strip())
        if not match:
            continue

        created_at = _parse_timestamp(match.group("timestamp"))
        chat_id = None
        message_id = None
        meta = match.group("meta")
        if meta:
            for part in meta.split(","):
                item = part.strip()
                if item.startswith("chat_id="):
                    chat_id = int(item.split("=", 1)[1])
                elif item.startswith("message_id="):
                    message_id = int(item.split("=", 1)[1])

        turns.append(
            ConversationTurn(
                speaker_type=match.group("speaker_type").strip(),
                speaker_name=match.group("speaker_name").strip(),
                text=body.strip(),
                created_at=created_at,
                chat_id=chat_id,
                message_id=message_id,
            )
        )
    return turns


def _parse_timestamp(raw: str) -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
