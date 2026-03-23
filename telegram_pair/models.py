from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class RouteMode(str, Enum):
    IGNORE = "ignore"
    SINGLE = "single"
    BROADCAST = "broadcast"


@dataclass(slots=True, frozen=True)
class RouteDecision:
    mode: RouteMode
    normalized_text: str = ""
    target_bot_names: tuple[str, ...] = ()
    reason: str = ""

    @property
    def should_process(self) -> bool:
        return self.mode is not RouteMode.IGNORE and bool(self.normalized_text.strip())


@dataclass(slots=True, frozen=True)
class BroadcastContext:
    original_user_text: str
    first_bot_name: str
    first_bot_output: str = ""
    failure_note: str | None = None

    def render_for_second_bot(self) -> str:
        sections = [
            "Original user request:",
            self.original_user_text.strip(),
            "",
            f"{self.first_bot_name} output:",
            self.first_bot_output.strip() or "<no output>",
        ]
        if self.failure_note:
            sections.extend(["", f"Failure note: {self.failure_note.strip()}"])
        return "\n".join(sections).strip()


@dataclass(slots=True, frozen=True)
class CliRequest:
    bot_name: str
    executable: str
    args: tuple[str, ...]
    prompt: str
    cwd: Path
    timeout_seconds: int
    model_override: str | None = None
    context_excerpt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CliResult:
    bot_name: str
    ok: bool
    output: str
    duration_seconds: float
    exit_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    stderr: str = ""


@dataclass(slots=True, frozen=True)
class ConversationTurn:
    speaker_type: str
    speaker_name: str
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chat_id: int | None = None
    message_id: int | None = None

    def as_markdown_block(self) -> str:
        timestamp = self.created_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        header = f"## {self.speaker_type}:{self.speaker_name} @ {timestamp}"
        metadata: list[str] = []
        if self.chat_id is not None:
            metadata.append(f"chat_id={self.chat_id}")
        if self.message_id is not None:
            metadata.append(f"message_id={self.message_id}")
        if metadata:
            header = f"{header} ({', '.join(metadata)})"
        body = self.text.strip() if self.text.strip() else "<empty>"
        return f"{header}\n\n{body}\n"
