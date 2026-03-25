from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class SessionRecord:
    chat_id: int
    bot_name: str
    session_id: str | None = None
    transport_kind: str = "none"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    last_message_id: int | None = None
    last_model: str | None = None
    broken: bool = False
    broken_reason: str | None = None

    def with_success(
        self,
        *,
        session_id: str | None,
        transport_kind: str,
        last_message_id: int | None,
        last_model: str | None,
    ) -> "SessionRecord":
        now = _utcnow()
        return SessionRecord(
            chat_id=self.chat_id,
            bot_name=self.bot_name,
            session_id=session_id,
            transport_kind=transport_kind,
            created_at=self.created_at,
            updated_at=now,
            last_message_id=last_message_id,
            last_model=last_model,
            broken=False,
            broken_reason=None,
        )

    def with_broken(self, *, reason: str | None = None, last_message_id: int | None = None) -> "SessionRecord":
        return SessionRecord(
            chat_id=self.chat_id,
            bot_name=self.bot_name,
            session_id=self.session_id,
            transport_kind=self.transport_kind,
            created_at=self.created_at,
            updated_at=_utcnow(),
            last_message_id=last_message_id if last_message_id is not None else self.last_message_id,
            last_model=self.last_model,
            broken=True,
            broken_reason=reason,
        )

    @classmethod
    def fresh(cls, *, chat_id: int, bot_name: str) -> "SessionRecord":
        return cls(chat_id=chat_id, bot_name=bot_name)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SessionRecord":
        return cls(
            chat_id=int(payload["chat_id"]),
            bot_name=str(payload["bot_name"]),
            session_id=_optional_string(payload.get("session_id")),
            transport_kind=_optional_string(payload.get("transport_kind")) or "none",
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
            last_message_id=_optional_int(payload.get("last_message_id")),
            last_model=_optional_string(payload.get("last_model")),
            broken=bool(payload.get("broken", False)),
            broken_reason=_optional_string(payload.get("broken_reason")),
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        payload["updated_at"] = self.updated_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        return payload


class SessionStore:
    def __init__(self, workspace_dir: Path) -> None:
        self._root = workspace_dir / "sessions"

    @property
    def root(self) -> Path:
        return self._root

    def load(self, chat_id: int, bot_name: str) -> SessionRecord | None:
        path = self.path_for(chat_id, bot_name)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return SessionRecord.from_dict(payload)

    def save(self, record: SessionRecord) -> None:
        self._atomic_write(record.chat_id, record.bot_name, record.to_dict())

    def mark_broken(
        self,
        chat_id: int,
        bot_name: str,
        *,
        reason: str | None = None,
        last_message_id: int | None = None,
    ) -> SessionRecord:
        current = self.load(chat_id, bot_name) or SessionRecord.fresh(chat_id=chat_id, bot_name=bot_name)
        updated = current.with_broken(reason=reason, last_message_id=last_message_id)
        self.save(updated)
        return updated

    def touch_success(
        self,
        chat_id: int,
        bot_name: str,
        *,
        session_id: str | None,
        transport_kind: str,
        last_message_id: int | None,
        last_model: str | None,
    ) -> SessionRecord:
        current = self.load(chat_id, bot_name) or SessionRecord.fresh(chat_id=chat_id, bot_name=bot_name)
        updated = current.with_success(
            session_id=session_id,
            transport_kind=transport_kind,
            last_message_id=last_message_id,
            last_model=last_model,
        )
        self.save(updated)
        return updated

    def clear(self, chat_id: int, bot_name: str) -> bool:
        path = self.path_for(chat_id, bot_name)
        if not path.exists():
            return False
        path.unlink()
        self._prune_empty_dirs(path.parent)
        return True

    def clear_all(self, chat_id: int, bot_names: tuple[str, ...]) -> int:
        cleared = 0
        for bot_name in bot_names:
            cleared += int(self.clear(chat_id, bot_name))
        return cleared

    def path_for(self, chat_id: int, bot_name: str) -> Path:
        return self._root / f"chat_{chat_id}" / f"{bot_name}.json"

    def status_lines(self, chat_id: int, bot_names: tuple[str, ...], *, stateless_bot_names: frozenset[str]) -> list[str]:
        lines = ["현재 세션 상태:"]
        for bot_name in bot_names:
            if bot_name in stateless_bot_names:
                lines.append(f"- {bot_name}: stateless")
                continue
            record = self.load(chat_id, bot_name)
            if record is None or not record.session_id:
                lines.append(f"- {bot_name}: no active session")
                continue
            if record.broken:
                lines.append(f"- {bot_name}: broken ({record.session_id})")
                continue
            lines.append(f"- {bot_name}: active ({record.session_id})")
        return lines

    def _atomic_write(self, chat_id: int, bot_name: str, payload: dict[str, object]) -> None:
        path = self.path_for(chat_id, bot_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(path)

    def _prune_empty_dirs(self, path: Path) -> None:
        current = path
        while current != self._root and current.exists():
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_datetime(value: object) -> datetime:
    if value is None:
        return _utcnow()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
