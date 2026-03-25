from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .config import BotConfig, RuntimeConfig
from .model_registry import ModelRegistry
from .models import BroadcastContext, CliRequest, CliResult, TeamContext
from .session_store import SessionRecord, SessionStore

LOGGER = logging.getLogger(__name__)


class PromptBuilder(Protocol):
    def __call__(
        self,
        *,
        user_text: str,
        context_excerpt: str,
        broadcast_context: BroadcastContext | None = None,
        team_context: TeamContext | None = None,
    ) -> str: ...


class SessionAwareRunner:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        cli_runner: Callable[[CliRequest], Awaitable[CliResult]],
        model_registry: ModelRegistry,
        prompt_builder: PromptBuilder,
        session_store: SessionStore | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.cli_runner = cli_runner
        self.model_registry = model_registry
        self.prompt_builder = prompt_builder
        self.session_store = session_store or SessionStore(runtime_config.workspace_dir)

    async def execute(
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
    ) -> CliResult:
        active_model = self.model_registry.get_model(bot.name)
        if not self._supports_native_session(bot):
            return await self._run_attempt(
                bot=bot,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt,
                broadcast_context=broadcast_context,
                team_context=team_context,
                mode_label=mode_label,
                model_override=active_model,
            )

        stored = self.session_store.load(chat_id, bot.name)
        reusable = self._resume_candidate(
            bot=bot,
            chat_id=chat_id,
            stored=stored,
            active_model=active_model,
        )
        if reusable is not None:
            resumed = await self._run_attempt(
                bot=bot,
                chat_id=chat_id,
                user_text=user_text,
                context_excerpt=context_excerpt if self.runtime_config.force_context_restack else "",
                broadcast_context=broadcast_context,
                team_context=team_context,
                mode_label=mode_label,
                model_override=active_model,
                session_id=reusable.session_id,
                resume=True,
            )
            if resumed.ok:
                self.session_store.touch_success(
                    chat_id,
                    bot.name,
                    session_id=resumed.session_id or reusable.session_id,
                    transport_kind="resume",
                    last_message_id=message_id,
                    last_model=active_model,
                )
                return resumed
            if not resumed.session_broken:
                return resumed
            self.session_store.mark_broken(
                chat_id,
                bot.name,
                reason=resumed.error_message,
                last_message_id=message_id,
            )

        fresh = await self._run_attempt(
            bot=bot,
            chat_id=chat_id,
            user_text=user_text,
            context_excerpt=context_excerpt,
            broadcast_context=broadcast_context,
            team_context=team_context,
            mode_label=mode_label,
            model_override=active_model,
        )
        if fresh.ok:
            if fresh.session_id:
                self.session_store.touch_success(
                    chat_id,
                    bot.name,
                    session_id=fresh.session_id,
                    transport_kind="resume",
                    last_message_id=message_id,
                    last_model=active_model,
                )
            elif stored is not None:
                self.session_store.clear(chat_id, bot.name)
        return fresh

    async def _run_attempt(
        self,
        *,
        bot: BotConfig,
        chat_id: int,
        user_text: str,
        context_excerpt: str,
        broadcast_context: BroadcastContext | None,
        team_context: TeamContext | None,
        mode_label: str,
        model_override: str | None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> CliResult:
        prompt = self.prompt_builder(
            user_text=user_text,
            context_excerpt=context_excerpt,
            broadcast_context=broadcast_context,
            team_context=team_context,
        )
        request = CliRequest(
            bot_name=bot.name,
            executable=bot.cli_executable,
            args=self._request_args(bot, resume=resume),
            prompt=prompt,
            cwd=self.runtime_config.workspace_dir,
            timeout_seconds=self.runtime_config.timeout_seconds,
            context_excerpt=context_excerpt,
            session_id=session_id,
            resume=resume,
            capture_session_id=self._supports_native_session(bot),
            supports_structured_output=bot.session_output_format.lower() == "json",
            metadata={
                "chat_id": chat_id,
                "mode": mode_label,
                "session_attempt": "resume" if resume else "fresh",
            },
            model_override=model_override,
        )
        LOGGER.info(
            "cli_start bot=%s chat_id=%s mode=%s session_attempt=%s model=%s",
            bot.name,
            chat_id,
            mode_label,
            request.metadata["session_attempt"],
            model_override or "(default)",
        )
        result = await self.cli_runner(request)
        LOGGER.info(
            "cli_finish bot=%s chat_id=%s ok=%s duration=%.2fs error_type=%s session_reused=%s session_id=%s",
            bot.name,
            chat_id,
            result.ok,
            result.duration_seconds,
            result.error_type or "",
            result.session_reused,
            result.session_id or session_id or "",
        )
        return result

    def _resume_candidate(
        self,
        *,
        bot: BotConfig,
        chat_id: int,
        stored: SessionRecord | None,
        active_model: str | None,
    ) -> SessionRecord | None:
        if stored is None or stored.broken or not stored.session_id:
            return None
        if stored.last_model != active_model:
            self.session_store.clear(chat_id, bot.name)
            return None
        return stored

    def _request_args(self, bot: BotConfig, *, resume: bool) -> tuple[str, ...]:
        if not self._supports_native_session(bot):
            return bot.cli_args
        if resume:
            return bot.session_resume_args or bot.cli_args
        return bot.session_start_args or bot.cli_args

    def _supports_native_session(self, bot: BotConfig) -> bool:
        return bot.session_mode.strip().lower() == "resume"
