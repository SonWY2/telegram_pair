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
from .orchestrator_commands import OrchestratorCommandHandler
from .session_runtime import SessionAwareRunner
from .session_store import SessionStore

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
        self.session_store = SessionStore(runtime_config.workspace_dir)
        self.session_runner = SessionAwareRunner(
            runtime_config,
            cli_runner,
            self.model_registry,
            build_cli_prompt,
            self.session_store,
        )
        self.command_handler = OrchestratorCommandHandler(
            runtime_config,
            self.model_registry,
            self.session_store,
            send_message,
        )

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
        async with self._chat_lock(chat_id):
            return await self._handle_route_locked(
                chat_id=chat_id,
                message_id=message_id,
                user_text=user_text,
                route=route,
            )

    async def handle_app_command(self, *, chat_id: int, command_text: str) -> bool:
        async with self._chat_lock(chat_id):
            return await self.command_handler.handle(chat_id=chat_id, command_text=command_text)

    async def _handle_route_locked(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        user_text: str,
        route: RouteDecision,
    ) -> list[CliResult]:
        context_excerpt = self.context_manager.load_recent_context_text(
            self.runtime_config.max_context_turns,
            chat_id=chat_id,
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
                message_id=message_id,
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
                message_id=message_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
        if strategy is BroadcastStrategy.SEQUENTIAL:
            return await self._handle_sequential_broadcast_route(
                bots=bots,
                chat_id=chat_id,
                message_id=message_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
        return await self._handle_parallel_broadcast_route(
            bots=bots,
            chat_id=chat_id,
            message_id=message_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
        )

    def _chat_lock(self, chat_id: int) -> asyncio.Lock:
        return self._chat_locks.setdefault(chat_id, asyncio.Lock())

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
        message_id: int | None,
        user_text: str,
        context_excerpt: str,
        broadcast_context: BroadcastContext | None = None,
        team_context: TeamContext | None = None,
        mode_label: str = "single",
        emit_response: bool = True,
    ) -> CliResult:
        result = await self.session_runner.execute(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
            broadcast_context=broadcast_context,
            team_context=team_context,
            mode_label=mode_label,
        )
        if emit_response:
            await self._emit_result(result, chat_id=chat_id)
        return result

    async def _run_bot_with_progress(
        self,
        *,
        bot: BotConfig,
        chat_id: int,
        message_id: int | None,
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
                message_id=message_id,
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

    async def _emit_result(self, result: CliResult, *, chat_id: int) -> None:
        visible_text = render_result_for_telegram(result)
        await self.send_message(result.bot_name, chat_id, visible_text)
        self.context_manager.append_turn(
            ConversationTurn(
                speaker_type="bot",
                speaker_name=result.bot_name,
                text=visible_text,
                chat_id=chat_id,
            )
        )

    def _failure_note(self, result: CliResult) -> str:
        return f"{result.bot_name} failed: {result.error_type or 'runtime_error'} - {result.error_message or 'unknown error'}"

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

    async def _handle_parallel_broadcast_route(
        self,
        *,
        bots: tuple[BotConfig, ...],
        chat_id: int,
        message_id: int | None,
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
                    message_id=message_id,
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
        message_id: int | None,
        user_text: str,
        context_excerpt: str,
    ) -> list[CliResult]:
        results: list[CliResult] = []
        first_bot = bots[0]
        first_result = await self._run_bot_with_progress(
            bot=first_bot,
            chat_id=chat_id,
            message_id=message_id,
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
                message_id=message_id,
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
        message_id: int | None,
        user_text: str,
        context_excerpt: str,
    ) -> list[CliResult]:
        integration_bot = bots[-1]
        first_stage_results = await self._handle_parallel_broadcast_route(
            bots=bots,
            chat_id=chat_id,
            message_id=message_id,
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
            message_id=message_id,
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
