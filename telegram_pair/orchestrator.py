from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .cli_wrapper import run_cli
from .config import BotConfig, RuntimeConfig
from .context_manager import ContextManager
from .model_registry import ModelRegistry
from .models import BroadcastContext, CliRequest, CliResult, ConversationTurn, RouteDecision, RouteMode

BKit_USAGE_MARKER = "bkit Feature Usage"
LOGGER = logging.getLogger(__name__)


class SendMessage(Protocol):
    async def __call__(self, bot_name: str, chat_id: int, text: str) -> None: ...


class PairOrchestrator:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        context_manager: ContextManager,
        send_message: SendMessage,
        cli_runner: Callable[[CliRequest], Awaitable[CliResult]] = run_cli,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.context_manager = context_manager
        self.send_message = send_message
        self.cli_runner = cli_runner
        self.model_registry = model_registry or ModelRegistry(runtime_config)
        self._chat_locks: dict[int, asyncio.Lock] = {}

    async def handle_route(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        user_text: str,
        route: RouteDecision,
    ) -> list[CliResult]:
        if not route.should_process:
            return []
        lock = self._chat_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            return await self._handle_route_locked(
                chat_id=chat_id,
                message_id=message_id,
                user_text=user_text,
                route=route,
            )

    async def _handle_route_locked(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        user_text: str,
        route: RouteDecision,
    ) -> list[CliResult]:
        context_excerpt = self.context_manager.load_recent_context_text(
            self.runtime_config.max_context_turns
        )
        self.context_manager.append_turn(
            ConversationTurn(
                speaker_type="human",
                speaker_name="user",
                text=user_text,
                chat_id=chat_id,
                message_id=message_id,
            )
        )

        bots = self._resolve_target_bots(route)
        if route.mode is RouteMode.SINGLE:
            await self._send_progress_notice(
                bots[0],
                chat_id,
                f"⏳ {bots[0].name} 작업을 시작합니다...",
            )
            result = await self._run_bot(
                bot=bots[0],
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
            return [result]

        results: list[CliResult] = []
        first_bot = bots[0]
        await self._send_progress_notice(
            first_bot,
            chat_id,
            f"⏳ {first_bot.name} 작업을 시작합니다...",
        )
        first_result = await self._run_bot(
            bot=first_bot,
            chat_id=chat_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
        )
        results.append(first_result)

        broadcast_context = BroadcastContext(
            original_user_text=user_text,
            first_bot_name=first_bot.name,
            first_bot_output=first_result.output if first_result.ok else "",
            failure_note=None if first_result.ok else self._failure_note(first_result),
        )

        for bot in bots[1:]:
            await self._send_progress_notice(
                bot,
                chat_id,
                f"⏳ {bot.name} 작업을 시작합니다... (이전 봇 응답 반영)",
            )
            result = await self._run_bot(
                bot=bot,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
                broadcast_context=broadcast_context,
            )
            results.append(result)
        return results

    def _resolve_target_bots(self, route: RouteDecision) -> tuple[BotConfig, ...]:
        if route.mode is RouteMode.BROADCAST:
            requested = set(route.target_bot_names)
            bots = [
                bot
                for bot in self.runtime_config.bots_by_priority
                if not requested or bot.name in requested
            ]
            return tuple(bots)
        if route.mode is RouteMode.SINGLE and route.target_bot_names:
            return (self.runtime_config.get_bot(route.target_bot_names[0]),)
        raise ValueError(f"Unsupported route decision: {route!r}")

    async def _run_bot(
        self,
        *,
        bot: BotConfig,
        chat_id: int,
        user_text: str,
        context_excerpt: str,
        broadcast_context: BroadcastContext | None = None,
    ) -> CliResult:
        prompt = build_cli_prompt(
            user_text=user_text,
            context_excerpt=context_excerpt,
            broadcast_context=broadcast_context,
        )
        request = CliRequest(
            bot_name=bot.name,
            executable=bot.cli_executable,
            args=bot.cli_args,
            prompt=prompt,
            cwd=self.runtime_config.workspace_dir,
            timeout_seconds=self.runtime_config.timeout_seconds,
            context_excerpt=context_excerpt,
            metadata={
                "chat_id": chat_id,
                "mode": "broadcast" if broadcast_context else "single",
            },
            model_override=self.model_registry.get_model(bot.name),
        )
        LOGGER.info(
            "cli_start bot=%s chat_id=%s mode=%s model=%s",
            bot.name,
            chat_id,
            request.metadata["mode"],
            request.model_override or "(default)",
        )
        result = await self.cli_runner(request)
        LOGGER.info(
            "cli_finish bot=%s chat_id=%s ok=%s duration=%.2fs error_type=%s",
            bot.name,
            chat_id,
            result.ok,
            result.duration_seconds,
            result.error_type or "",
        )
        visible_text = render_result_for_telegram(result)
        await self.send_message(bot.name, chat_id, visible_text)
        self.context_manager.append_turn(
            ConversationTurn(
                speaker_type="bot",
                speaker_name=bot.name,
                text=visible_text,
                chat_id=chat_id,
            )
        )
        return result

    def _failure_note(self, result: CliResult) -> str:
        return f"{result.bot_name} failed: {result.error_type or 'runtime_error'} - {result.error_message or 'unknown error'}"

    async def handle_model_command(self, *, chat_id: int, command_text: str) -> bool:
        parsed = _parse_model_command(command_text)
        if parsed is None:
            return False

        action, target, value = parsed
        if action == "status":
            await self.send_message(_control_reply_bot_name(self.runtime_config), chat_id, self._render_model_status())
            return True

        try:
            bot_names = _resolve_model_targets(self.runtime_config, target)
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

    async def _send_progress_notice(self, bot: BotConfig, chat_id: int, text: str) -> None:
        LOGGER.info("progress_notice bot=%s chat_id=%s text=%r", bot.name, chat_id, text)
        await self.send_message(bot.name, chat_id, text)

    def _render_model_status(self) -> str:
        snapshot = self.model_registry.snapshot()
        lines = ["현재 모델 설정:"]
        for bot in self.runtime_config.bot_configs:
            lines.append(f"- {bot.name}: {snapshot.get(bot.name) or '(default)'}")
        return "\n".join(lines)


def build_cli_prompt(
    *,
    user_text: str,
    context_excerpt: str,
    broadcast_context: BroadcastContext | None = None,
) -> str:
    sections: list[str] = []
    if context_excerpt.strip():
        sections.extend(["Recent conversation context:", context_excerpt.strip()])
    if broadcast_context is None:
        sections.extend(["User request:", user_text.strip()])
    else:
        sections.extend(["Broadcast coordination:", broadcast_context.render_for_second_bot()])
    return "\n\n".join(section for section in sections if section.strip())


def render_result_for_telegram(result: CliResult) -> str:
    if result.ok:
        return _truncate_bkit_usage_tail(result.output)
    detail = result.error_message or "unknown error"
    return f"[{result.bot_name}] CLI error ({result.error_type or 'runtime_error'}): {detail}"


def _truncate_bkit_usage_tail(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if BKit_USAGE_MARKER in line:
            trimmed = "\n".join(lines[:index]).rstrip()
            return trimmed or "(empty response)"
    return text


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


def _resolve_model_targets(runtime_config: RuntimeConfig, target: str | None) -> tuple[str, ...]:
    claude_name = runtime_config.bot_configs[0].name
    codex_name = runtime_config.bot_configs[1].name
    if target == "claude":
        return (claude_name,)
    if target == "codex":
        return (codex_name,)
    if target == "all":
        return (claude_name, codex_name)
    raise ValueError(f"Unsupported model target: {target}")


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
