from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .cli_wrapper import run_cli
from .config import BotConfig, RuntimeConfig
from .context_manager import ContextManager
from .model_registry import ModelRegistry
from .models import (
    BroadcastContext,
    BroadcastStrategy,
    CliRequest,
    CliResult,
    ConversationTurn,
    RouteDecision,
    RouteMode,
    TeamContext,
)

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
            result = await self._run_bot_with_progress(
                bot=bots[0],
                chat_id=chat_id,
                progress_text=f"⏳ {bots[0].name} 작업을 시작합니다...",
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
            return [result]

        strategy = route.broadcast_strategy or BroadcastStrategy.PARALLEL
        if strategy is BroadcastStrategy.TEAM:
            return await self._handle_team_route(
                bots=bots,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
        if strategy is BroadcastStrategy.SEQUENTIAL:
            return await self._handle_sequential_broadcast_route(
                bots=bots,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
        return await self._handle_parallel_broadcast_route(
            bots=bots,
            chat_id=chat_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
        )

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
        team_context: TeamContext | None = None,
        mode_label: str = "single",
        emit_response: bool = True,
    ) -> CliResult:
        prompt = build_cli_prompt(
            user_text=user_text,
            context_excerpt=context_excerpt,
            broadcast_context=broadcast_context,
            team_context=team_context,
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
                "mode": mode_label,
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
        if emit_response:
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

    async def _run_bot_with_progress(
        self,
        *,
        bot: BotConfig,
        chat_id: int,
        progress_text: str,
        user_text: str,
        context_excerpt: str,
        broadcast_context: BroadcastContext | None = None,
        team_context: TeamContext | None = None,
        mode_label: str = "single",
        emit_response: bool = True,
        emit_progress: bool = True,
    ) -> CliResult:
        notice_task = None
        if emit_progress:
            notice_task = asyncio.create_task(
                self._maybe_send_progress_notice_after_delay(bot, chat_id, progress_text),
                name=f"progress:{bot.name}:{chat_id}",
            )
        try:
            return await self._run_bot(
                bot=bot,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
                broadcast_context=broadcast_context,
                team_context=team_context,
                mode_label=mode_label,
                emit_response=emit_response,
            )
        finally:
            if notice_task is not None:
                notice_task.cancel()
                await asyncio.gather(notice_task, return_exceptions=True)

    def _failure_note(self, result: CliResult) -> str:
        return f"{result.bot_name} failed: {result.error_type or 'runtime_error'} - {result.error_message or 'unknown error'}"

    async def handle_app_command(self, *, chat_id: int, command_text: str) -> bool:
        if _is_help_command(command_text):
            await self.send_message(
                _control_reply_bot_name(self.runtime_config),
                chat_id,
                _render_help_text(self.runtime_config),
            )
            return True
        return await self.handle_model_command(chat_id=chat_id, command_text=command_text)

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

    async def _maybe_send_progress_notice_after_delay(
        self,
        bot: BotConfig,
        chat_id: int,
        text: str,
    ) -> None:
        delay = self.runtime_config.progress_notice_delay_seconds
        if delay <= 0:
            await self._send_progress_notice(bot, chat_id, text)
            return
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._send_progress_notice(bot, chat_id, text)

    def _render_model_status(self) -> str:
        snapshot = self.model_registry.snapshot()
        lines = ["현재 모델 설정:"]
        for bot in self.runtime_config.bot_configs:
            lines.append(f"- {bot.name}: {snapshot.get(bot.name) or '(default)'}")
        return "\n".join(lines)

    async def _handle_parallel_broadcast_route(
        self,
        *,
        bots: tuple[BotConfig, ...],
        chat_id: int,
        user_text: str,
        context_excerpt: str,
        hidden_bot_names: frozenset[str] | None = None,
    ) -> list[CliResult]:
        hidden_bot_names = hidden_bot_names or frozenset()
        tasks = [
            asyncio.create_task(
                self._run_bot_with_progress(
                    bot=bot,
                    chat_id=chat_id,
                    progress_text=f"⏳ {bot.name} 작업을 시작합니다...",
                    user_text=user_text,
                    context_excerpt=context_excerpt,
                    mode_label="broadcast_parallel",
                    emit_response=bot.name not in hidden_bot_names,
                    emit_progress=bot.name not in hidden_bot_names,
                ),
                name=f"broadcast:{bot.name}:{chat_id}",
            )
            for bot in bots
        ]
        return list(await asyncio.gather(*tasks))

    async def _handle_sequential_broadcast_route(
        self,
        *,
        bots: tuple[BotConfig, ...],
        chat_id: int,
        user_text: str,
        context_excerpt: str,
    ) -> list[CliResult]:
        results: list[CliResult] = []
        first_bot = bots[0]
        first_result = await self._run_bot_with_progress(
            bot=first_bot,
            chat_id=chat_id,
            progress_text=f"⏳ {first_bot.name} 작업을 시작합니다...",
            user_text=user_text,
            context_excerpt=context_excerpt,
            mode_label="broadcast_sequential_first",
        )
        results.append(first_result)

        broadcast_context = BroadcastContext(
            original_user_text=user_text,
            first_bot_name=first_bot.name,
            first_bot_output=first_result.output if first_result.ok else "",
            failure_note=None if first_result.ok else self._failure_note(first_result),
        )
        for bot in bots[1:]:
            result = await self._run_bot_with_progress(
                bot=bot,
                chat_id=chat_id,
                progress_text=f"⏳ {bot.name} 검토 응답을 준비합니다...",
                user_text=user_text,
                context_excerpt=context_excerpt,
                broadcast_context=broadcast_context,
                mode_label="broadcast_sequential_followup",
            )
            results.append(result)
        return results

    async def _handle_team_route(
        self,
        *,
        bots: tuple[BotConfig, ...],
        chat_id: int,
        user_text: str,
        context_excerpt: str,
    ) -> list[CliResult]:
        integration_bot = bots[-1]
        first_stage_results = await self._handle_parallel_broadcast_route(
            bots=bots,
            chat_id=chat_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
            hidden_bot_names=frozenset({integration_bot.name}),
        )
        team_context = TeamContext(
            original_user_text=user_text,
            bot_outputs=tuple(
                (result.bot_name, result.output if result.ok else "")
                for result in first_stage_results
            ),
            failure_notes=tuple(
                self._failure_note(result)
                for result in first_stage_results
                if not result.ok
            ),
        )
        team_result = await self._run_bot_with_progress(
            bot=integration_bot,
            chat_id=chat_id,
            progress_text=f"⏳ {integration_bot.name} 팀 통합 응답을 준비합니다...",
            user_text=user_text,
            context_excerpt=context_excerpt,
            team_context=team_context,
            mode_label="team_resolution",
        )
        return [*first_stage_results, team_result]


def build_cli_prompt(
    *,
    user_text: str,
    context_excerpt: str,
    broadcast_context: BroadcastContext | None = None,
    team_context: TeamContext | None = None,
) -> str:
    sections: list[str] = []
    if context_excerpt.strip():
        sections.extend(["Recent conversation context:", context_excerpt.strip()])
    if team_context is not None:
        sections.extend(["Team coordination:", team_context.render_for_team_resolution()])
    elif broadcast_context is not None:
        sections.extend(["Broadcast coordination:", broadcast_context.render_for_second_bot()])
    else:
        sections.extend(["User request:", user_text.strip()])
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


def _is_help_command(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered == "/help" or lowered.startswith("/help@")


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
        "팁: 일반 Telegram 명령(/start 등)은 무시되고, /help 와 /model만 앱 명령으로 처리됩니다."
    )
