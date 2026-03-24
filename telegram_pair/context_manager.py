from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import re
from typing import Iterable

from .models import ConversationTurn


_HEADER_RE = re.compile(
    r"^## (?P<speaker_type>[^:]+):(?P<speaker_name>.+?) @ (?P<timestamp>[^()]+?)(?: \((?P<meta>[^)]*)\))?$"
)


class ContextManager:
    """Persist and load conversation history in markdown, separated per chat when possible."""

    def __init__(self, path: Path, *, chat_path_template: str = "{base_stem}/chat_{chat_id}.md") -> None:
        self.path = path
        self.chat_path_template = chat_path_template
        self._lock = threading.Lock()

    def append_turn(self, turn: ConversationTurn) -> None:
        self.append_turns([turn])

    def append_turns(self, turns: Iterable[ConversationTurn]) -> None:
        grouped_blocks: dict[int | None, list[str]] = defaultdict(list)
        for turn in turns:
            grouped_blocks[turn.chat_id].append(turn.as_markdown_block().rstrip())
        if not grouped_blocks:
            return

        with self._lock:
            for chat_id, blocks in grouped_blocks.items():
                self._append_blocks(self._storage_path(chat_id), blocks)

    def load_recent_context(self, max_turns: int, *, chat_id: int | None = None) -> tuple[ConversationTurn, ...]:
        if max_turns <= 0:
            return ()

        if chat_id is None:
            parsed = self._read_turns_from_path(self.path)
            return tuple(parsed[-max_turns:])

        scoped_turns = self._read_turns_from_path(self._storage_path(chat_id))
        if scoped_turns:
            return tuple(scoped_turns[-max_turns:])

        legacy_turns = [turn for turn in self._read_turns_from_path(self.path) if turn.chat_id == chat_id]
        return tuple(legacy_turns[-max_turns:])

    def load_recent_context_text(self, max_turns: int, *, chat_id: int | None = None) -> str:
        turns = self.load_recent_context(max_turns, chat_id=chat_id)
        return format_recent_context(turns)

    def _append_blocks(self, path: Path, blocks: Iterable[str]) -> None:
        materialized = [block for block in blocks if block]
        if not materialized:
            return
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        body = existing.rstrip()
        if body:
            body += "\n\n"
        body += "\n\n".join(materialized) + "\n"
        self._atomic_write(path, body)

    def _storage_path(self, chat_id: int | None) -> Path:
        if chat_id is None:
            return self.path
        relative_or_absolute = Path(
            self.chat_path_template.format(
                chat_id=chat_id,
                base_dir=str(self.path.parent),
                base_name=self.path.name,
                base_stem=self.path.stem,
            )
        )
        if relative_or_absolute.is_absolute():
            return relative_or_absolute
        return self.path.parent / relative_or_absolute

    def _read_turns_from_path(self, path: Path) -> list[ConversationTurn]:
        if not path.exists():
            return []
        return _parse_turns(path.read_text(encoding="utf-8"))

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)


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
