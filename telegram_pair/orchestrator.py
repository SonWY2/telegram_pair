from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from .cli_wrapper import run_cli
from .config import BotConfig, RuntimeConfig
from .context_manager import ContextManager
from .models import BroadcastContext, CliRequest, CliResult, ConversationTurn, RouteDecision, RouteMode


class SendMessage(Protocol):
    async def __call__(self, bot_name: str, chat_id: int, text: str) -> None: ...


class PairOrchestrator:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        context_manager: ContextManager,
        send_message: SendMessage,
        cli_runner: Callable[[CliRequest], Awaitable[CliResult]] = run_cli,
    ) -> None:
        self.runtime_config = runtime_config
        self.context_manager = context_manager
        self.send_message = send_message
        self.cli_runner = cli_runner
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
            result = await self._run_bot(
                bot=bots[0],
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
            )
            return [result]

        results: list[CliResult] = []
        first_bot = bots[0]
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
        )
        result = await self.cli_runner(request)
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
        return result.output
    detail = result.error_message or "unknown error"
    return f"[{result.bot_name}] CLI error ({result.error_type or 'runtime_error'}): {detail}"
