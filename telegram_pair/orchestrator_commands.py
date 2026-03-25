from __future__ import annotations

from collections.abc import Awaitable, Callable

from .config import RuntimeConfig
from .model_registry import ModelRegistry
from .session_store import SessionStore

SendMessage = Callable[[str, int, str], Awaitable[None]]


class OrchestratorCommandHandler:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        model_registry: ModelRegistry,
        session_store: SessionStore,
        send_message: SendMessage,
    ) -> None:
        self.runtime_config = runtime_config
        self.model_registry = model_registry
        self.session_store = session_store
        self.send_message = send_message

    async def handle(self, *, chat_id: int, command_text: str) -> bool:
        if _is_help_command(command_text):
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                _render_help_text(self.runtime_config),
            )
            return True
        if await self._handle_model_command(chat_id=chat_id, command_text=command_text):
            return True
        return await self._handle_session_command(chat_id=chat_id, command_text=command_text)

    async def _handle_model_command(self, *, chat_id: int, command_text: str) -> bool:
        parsed = _parse_model_command(command_text)
        if parsed is None:
            return False
        action, target, value = parsed
        if action == "status":
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                self.render_model_status(),
            )
            return True
        try:
            bot_names = _resolve_control_targets(self.runtime_config, target)
        except ValueError:
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                _render_model_help(),
            )
            return True
        if action == "set" and value:
            for bot_name in bot_names:
                self.model_registry.set_model(bot_name, value)
            await self.send_message(
                _control_reply_bot_name(self.runtime_config, target),
                chat_id,
                _render_model_set_reply(bot_names, value),
            )
            return True
        if action == "reset":
            for bot_name in bot_names:
                self.model_registry.reset_model(bot_name)
            await self.send_message(
                _control_reply_bot_name(self.runtime_config, target),
                chat_id,
                _render_model_reset_reply(bot_names),
            )
            return True
        await self.send_message(
            _control_reply_bot_name(self.runtime_config),
            chat_id,
            _render_model_help(),
        )
        return True

    async def _handle_session_command(self, *, chat_id: int, command_text: str) -> bool:
        parsed = _parse_session_command(command_text)
        if parsed is None:
            return False
        action, target = parsed
        if action == "status":
            lines = self.session_store.status_lines(
                chat_id,
                tuple(bot.name for bot in self.runtime_config.bot_configs),
                stateless_bot_names=frozenset(
                    bot.name
                    for bot in self.runtime_config.bot_configs
                    if bot.session_mode.strip().lower() != "resume"
                ),
            )
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                "\n".join(lines),
            )
            return True
        try:
            bot_names = _resolve_control_targets(self.runtime_config, target)
        except ValueError:
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                _render_session_help(),
            )
            return True
        cleared = self.session_store.clear_all(chat_id, bot_names)
        await self.send_message(
            _control_reply_bot_name(self.runtime_config, target),
            chat_id,
            _render_session_reset_reply(bot_names, cleared),
        )
        return True

    def render_model_status(self) -> str:
        snapshot = self.model_registry.snapshot()
        lines = ["현재 모델 설정:"]
        for bot in self.runtime_config.bot_configs:
            lines.append(f"- {bot.name}: {snapshot.get(bot.name) or '(default)'}")
        return "\n".join(lines)


def _parse_model_command(text: str) -> tuple[str, str | None, str | None] | None:
    stripped = text.strip()
    if not stripped.lower().startswith("/model"):
        return None
    parts = stripped.split()
    parts[0] = parts[0].split("@", 1)[0]
    if len(parts) == 1:
        return ("status", None, None)
    if len(parts) == 2 and parts[1].lower() == "status":
        return ("status", None, None)
    if len(parts) >= 3 and parts[1].lower() == "reset":
        return ("reset", parts[2].lower(), None)
    if len(parts) >= 3:
        return ("set", parts[1].lower(), " ".join(parts[2:]).strip())
    return ("help", None, None)


def _parse_session_command(text: str) -> tuple[str, str | None] | None:
    stripped = text.strip()
    if not stripped.lower().startswith("/session"):
        return None
    parts = stripped.split()
    parts[0] = parts[0].split("@", 1)[0]
    if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == "status"):
        return ("status", None)
    if len(parts) >= 3 and parts[1].lower() == "reset":
        return ("reset", parts[2].lower())
    return ("help", None)


def _is_help_command(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered == "/help" or lowered.startswith("/help@")


def _resolve_control_targets(runtime_config: RuntimeConfig, target: str | None) -> tuple[str, ...]:
    claude_name = runtime_config.bot_configs[0].name
    codex_name = runtime_config.bot_configs[1].name
    if target == "claude":
        return (claude_name,)
    if target == "codex":
        return (codex_name,)
    if target == "all":
        return (claude_name, codex_name)
    raise ValueError(f"Unsupported control target: {target}")


def _control_reply_bot_name(runtime_config: RuntimeConfig, target: str | None = None) -> str:
    if target == "codex":
        return runtime_config.bot_configs[1].name
    return runtime_config.bot_configs[0].name


def _render_model_set_reply(bot_names: tuple[str, ...], model: str) -> str:
    if len(bot_names) == 1:
        return f"모델 변경 완료: {bot_names[0]} -> {model}"
    return f"모델 변경 완료: {', '.join(bot_names)} -> {model}"


def _render_model_reset_reply(bot_names: tuple[str, ...]) -> str:
    if len(bot_names) == 1:
        return f"모델 설정 초기화 완료: {bot_names[0]}"
    return f"모델 설정 초기화 완료: {', '.join(bot_names)}"


def _render_model_help() -> str:
    return (
        "사용법:\n"
        "/model status\n"
        "/model claude <model>\n"
        "/model codex <model>\n"
        "/model all <model>\n"
        "/model reset claude|codex|all"
    )


def _render_session_reset_reply(bot_names: tuple[str, ...], cleared: int) -> str:
    target = ", ".join(bot_names)
    return f"세션 초기화 완료: {target} (cleared={cleared})"


def _render_session_help() -> str:
    return (
        "사용법:\n"
        "/session status\n"
        "/session reset claude\n"
        "/session reset codex\n"
        "/session reset all"
    )


def _render_help_text(runtime_config: RuntimeConfig) -> str:
    claude = runtime_config.bot_configs[0].canonical_mention
    codex = runtime_config.bot_configs[1].canonical_mention
    return (
        "Telegram Pair 도움말\n\n"
        "1) 단일 호출\n"
        f"- {claude} 이 함수 리팩터링해줘\n"
        f"- {codex} 이 테스트 실패 원인 찾아줘\n\n"
        "2) 두 봇 함께 호출\n"
        "- 병렬 비교: ; 이 구현 대안을 비교해줘\n"
        f"- 두 봇 동시 멘션도 동일: {claude} {codex} 이 구현 대안을 비교해줘\n"
        "- 순차 검토: ; seq 이 설계를 먼저 제안하고 그다음 보완해줘\n"
        "- 팀 협업: ; team 비트코인 전망을 각각 분석하고 마지막에 결론 내줘\n\n"
        "3) 모델 제어\n"
        "- /model status\n"
        "- /model claude <model>\n"
        "- /model codex <model>\n"
        "- /model all <model>\n"
        "- /model reset claude|codex|all\n\n"
        "4) 세션 제어\n"
        "- /session status\n"
        "- /session reset claude\n"
        "- /session reset codex\n"
        "- /session reset all\n\n"
        "팁: 일반 Telegram 명령(/start 등)은 무시되고, /help 와 /model만 앱 명령으로 처리되며 "
        "/session도 동일한 제어 명령으로 처리됩니다."
    )
