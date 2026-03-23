from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_CONTEXT_TURNS = 12
DEFAULT_DEDUP_TTL_SECONDS = 300


class ConfigError(ValueError):
    """Raised when the runtime configuration is invalid."""


@dataclass(slots=True, frozen=True)
class BotConfig:
    name: str
    telegram_token: str
    cli_executable: str
    cli_args: tuple[str, ...]
    priority: int
    mention_aliases: tuple[str, ...]
    default_model: str | None = None

    @property
    def canonical_mention(self) -> str:
        return f"@{self.name.lstrip('@')}"

    def validate(self) -> None:
        missing_fields: list[str] = []
        if not self.telegram_token.strip():
            missing_fields.append("telegram_token")
        if not self.name.strip():
            missing_fields.append("name")
        if not self.cli_executable.strip():
            missing_fields.append("cli_executable")
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise ConfigError(f"Bot config '{self.name or '<unnamed>'}' is missing: {joined}")

        executable = self.cli_executable.strip()
        if shutil.which(executable) is None and not Path(executable).expanduser().exists():
            raise ConfigError(
                f"CLI executable for bot '{self.name}' was not found: {self.cli_executable}"
            )


@dataclass(slots=True, frozen=True)
class RuntimeConfig:
    workspace_dir: Path
    context_md_path: Path
    timeout_seconds: int
    max_context_turns: int
    dedup_ttl_seconds: int
    target_chat_id: int | None
    log_level: str
    bot_configs: tuple[BotConfig, ...]

    def validate(self) -> None:
        if len(self.bot_configs) < 2:
            raise ConfigError("At least two bot configurations are required")
        if self.timeout_seconds <= 0:
            raise ConfigError("TELEGRAM_PAIR_TIMEOUT_SECONDS must be > 0")
        if self.max_context_turns <= 0:
            raise ConfigError("TELEGRAM_PAIR_MAX_CONTEXT_TURNS must be > 0")
        if self.dedup_ttl_seconds <= 0:
            raise ConfigError("TELEGRAM_PAIR_DEDUP_TTL_SECONDS must be > 0")
        for bot in self.bot_configs:
            bot.validate()

    @property
    def bots_by_priority(self) -> tuple[BotConfig, ...]:
        return tuple(sorted(self.bot_configs, key=lambda bot: bot.priority))

    def get_bot(self, name: str) -> BotConfig:
        for bot in self.bot_configs:
            if bot.name == name:
                return bot
        raise KeyError(name)

    def prepare_workspace(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.context_md_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    values = dict(_load_default_env() if env is None else env)
    workspace_dir = Path(values.get("TELEGRAM_PAIR_WORKSPACE_DIR", "./runtime")).expanduser().resolve()
    context_default = workspace_dir / "context.md"
    context_md_path = Path(values.get("TELEGRAM_PAIR_CONTEXT_PATH", str(context_default))).expanduser().resolve()

    runtime = RuntimeConfig(
        workspace_dir=workspace_dir,
        context_md_path=context_md_path,
        timeout_seconds=_parse_int(values, "TELEGRAM_PAIR_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_context_turns=_parse_int(
            values,
            "TELEGRAM_PAIR_MAX_CONTEXT_TURNS",
            DEFAULT_MAX_CONTEXT_TURNS,
        ),
        dedup_ttl_seconds=_parse_int(
            values,
            "TELEGRAM_PAIR_DEDUP_TTL_SECONDS",
            DEFAULT_DEDUP_TTL_SECONDS,
        ),
        target_chat_id=_parse_optional_int(values.get("TELEGRAM_PAIR_TARGET_CHAT_ID")),
        log_level=values.get("TELEGRAM_PAIR_LOG_LEVEL", "INFO").upper(),
        bot_configs=(
            _load_bot_config(
                values,
                name_key="CLAUDE_BOT_NAME",
                token_key="TELEGRAM_TOKEN_CLAUDE",
                executable_key="CLAUDE_CLI_EXECUTABLE",
                args_key="CLAUDE_CLI_ARGS",
                aliases_key="CLAUDE_MENTION_ALIASES",
                default_name="ClaudeCodeBot",
                default_executable="claude",
                default_args="-p",
                model_key="CLAUDE_MODEL",
                priority=1,
            ),
            _load_bot_config(
                values,
                name_key="CODEX_BOT_NAME",
                token_key="TELEGRAM_TOKEN_CODEX",
                executable_key="CODEX_CLI_EXECUTABLE",
                args_key="CODEX_CLI_ARGS",
                aliases_key="CODEX_MENTION_ALIASES",
                default_name="CodexPairBot",
                default_executable="codex",
                default_args="",
                model_key="CODEX_MODEL",
                priority=2,
            ),
        ),
    )
    runtime.validate()
    return runtime


def _load_default_env() -> dict[str, str]:
    values = dict(os.environ)
    dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.exists():
        return values

    for key, value in _parse_dotenv(dotenv_path).items():
        values.setdefault(key, value)
    return values


def _parse_dotenv(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        parsed[key] = value
    return parsed


def _load_bot_config(
    values: Mapping[str, str],
    *,
    name_key: str,
    token_key: str,
    executable_key: str,
    args_key: str,
    aliases_key: str,
    default_name: str,
    default_executable: str,
    default_args: str,
    model_key: str,
    priority: int,
) -> BotConfig:
    name = values.get(name_key, default_name).strip() or default_name
    aliases = _parse_aliases(name, values.get(aliases_key, ""))
    return BotConfig(
        name=name,
        telegram_token=values.get(token_key, "").strip(),
        cli_executable=values.get(executable_key, default_executable).strip() or default_executable,
        cli_args=_parse_args(values.get(args_key, default_args)),
        priority=priority,
        mention_aliases=aliases,
        default_model=values.get(model_key, "").strip() or None,
    )


def _parse_args(raw: str) -> tuple[str, ...]:
    stripped = raw.strip()
    return tuple(shlex.split(stripped)) if stripped else ()


def _parse_aliases(name: str, raw: str) -> tuple[str, ...]:
    aliases: list[str] = [f"@{name.lstrip('@')}", name.lstrip("@")]
    if raw.strip():
        aliases.extend(part.strip() for part in raw.split(",") if part.strip())

    normalized: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if alias not in seen:
            normalized.append(alias)
            seen.add(alias)
    return tuple(normalized)


def _parse_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got: {raw!r}") from exc


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"TELEGRAM_PAIR_TARGET_CHAT_ID must be an integer, got: {raw!r}") from exc
