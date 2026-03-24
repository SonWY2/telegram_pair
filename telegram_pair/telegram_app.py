from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

try:  # pragma: no cover - exercised indirectly when aiogram is installed
    from aiogram import Bot, Dispatcher
except ImportError:  # pragma: no cover - local tests run without aiogram installed
    Bot = None  # type: ignore[assignment]
    Dispatcher = None  # type: ignore[assignment]

from .config import RuntimeConfig
from .context_manager import ContextManager
from .models import CliRequest
from .orchestrator import PairOrchestrator
from .router import route_message_from_bot_configs
from .cli_wrapper import run_cli

LOGGER = logging.getLogger(__name__)
TELEGRAM_TEXT_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class InboundTelegramMessage:
    receiver_bot: str
    chat_id: int
    message_id: int
    text: str


class TelegramMessageProcessor(Protocol):
    async def process_telegram_message(self, inbound: InboundTelegramMessage) -> None:
        ...


class CliRunner(Protocol):
    async def __call__(self, request: CliRequest) -> Any:
        ...


class TelegramBotClient(Protocol):
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> Any:
        ...


class DedupCache:
    def __init__(
        self,
        ttl_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 2048,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._max_entries = max_entries
        self._expires_at: dict[tuple[int, int], float] = {}

    def should_process(self, chat_id: int, message_id: int) -> bool:
        now = self._clock()
        self._purge(now)
        key = (chat_id, message_id)
        if key in self._expires_at:
            return False
        self._expires_at[key] = now + self._ttl_seconds
        if len(self._expires_at) > self._max_entries:
            oldest_key = min(self._expires_at, key=self._expires_at.__getitem__)
            self._expires_at.pop(oldest_key, None)
        return True

    def _purge(self, now: float) -> None:
        expired = [key for key, expires_at in self._expires_at.items() if expires_at <= now]
        for key in expired:
            self._expires_at.pop(key, None)


class TelegramBotRegistry:
    def __init__(self, bots: Mapping[str, TelegramBotClient]) -> None:
        self._bots = dict(bots)

    async def send_text(
        self,
        bot_name: str,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> list[Any]:
        bot = self._bots.get(bot_name)
        if bot is None:
            raise KeyError(f"Unknown bot '{bot_name}'")

        chunks = chunk_message(text)
        sent_messages = []
        for index, chunk in enumerate(chunks):
            sent_messages.append(
                await bot.send_message(
                    chat_id,
                    chunk,
                    reply_to_message_id=reply_to_message_id if index == 0 else None,
                )
            )
        return sent_messages

    async def close(self) -> None:
        for bot in self._bots.values():
            session = getattr(bot, "session", None)
            close = getattr(session, "close", None)
            if close is None:
                continue
            result = close()
            if asyncio.iscoroutine(result):
                await result


class TelegramRuntime:
    def __init__(
        self,
        processor: TelegramMessageProcessor,
        bot_registry: TelegramBotRegistry,
        *,
        dedup_cache: DedupCache | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._processor = processor
        self._bot_registry = bot_registry
        self._dedup_cache = dedup_cache or DedupCache()
        self._logger = logger or LOGGER

    async def handle_update(self, receiver_bot: str, update_or_message: Any) -> bool:
        inbound = self._to_inbound_message(receiver_bot, update_or_message)
        if inbound is None:
            return False
        if not self._dedup_cache.should_process(inbound.chat_id, inbound.message_id):
            self._logger.debug(
                "Skipping duplicate Telegram update chat_id=%s message_id=%s",
                inbound.chat_id,
                inbound.message_id,
            )
            return False
        await self._processor.process_telegram_message(inbound)
        return True

    async def send_reply(
        self,
        bot_name: str,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> list[Any]:
        return await self._bot_registry.send_text(
            bot_name,
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
        )

    async def close(self) -> None:
        await self._bot_registry.close()

    def _to_inbound_message(self, receiver_bot: str, update_or_message: Any) -> InboundTelegramMessage | None:
        message = extract_message(update_or_message)
        if message is None:
            return None
        author = getattr(message, "from_user", None)
        if getattr(author, "is_bot", False):
            return None
        raw_text = getattr(message, "text", None) or getattr(message, "caption", None)
        if raw_text is None:
            return None
        text = raw_text.strip()
        if not text:
            return None
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        message_id = getattr(message, "message_id", None)
        if chat_id is None or message_id is None:
            return None
        return InboundTelegramMessage(
            receiver_bot=receiver_bot,
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
        )


class RoutedTelegramMessageProcessor:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        orchestrator: PairOrchestrator,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._runtime_config = runtime_config
        self._orchestrator = orchestrator
        self._logger = logger or LOGGER

    async def process_telegram_message(self, inbound: InboundTelegramMessage) -> None:
        if (
            self._runtime_config.target_chat_id is not None
            and inbound.chat_id != self._runtime_config.target_chat_id
        ):
            self._logger.debug(
                "Skipping chat_id=%s because target_chat_id=%s",
                inbound.chat_id,
                self._runtime_config.target_chat_id,
            )
            return

        if await self._orchestrator.handle_app_command(
            chat_id=inbound.chat_id,
            command_text=inbound.text,
        ):
            self._logger.info(
                "Handled app command chat_id=%s message_id=%s text=%r",
                inbound.chat_id,
                inbound.message_id,
                inbound.text,
            )
            return

        route = route_message_from_bot_configs(
            inbound.text,
            bot_configs=self._runtime_config.bot_configs,
        )
        if not route.should_process:
            self._logger.debug(
                "Ignoring inbound message chat_id=%s message_id=%s reason=%s",
                inbound.chat_id,
                inbound.message_id,
                route.reason,
            )
            return

        self._logger.info(
            "Processing inbound route chat_id=%s message_id=%s mode=%s targets=%s",
            inbound.chat_id,
            inbound.message_id,
            route.mode.value,
            ",".join(route.target_bot_names),
        )
        await self._orchestrator.handle_route(
            chat_id=inbound.chat_id,
            message_id=inbound.message_id,
            user_text=route.normalized_text,
            route=route,
        )


def chunk_message(text: str, *, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return ["(empty response)"]
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    remaining = normalized
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def extract_message(update_or_message: Any) -> Any | None:
    if update_or_message is None:
        return None
    if hasattr(update_or_message, "message_id") and hasattr(update_or_message, "chat"):
        return update_or_message
    return getattr(update_or_message, "message", None)


def build_runtime(
    runtime_config: RuntimeConfig,
    bots: Mapping[str, TelegramBotClient],
    *,
    cli_runner: CliRunner | None = None,
    logger: logging.Logger | None = None,
) -> TelegramRuntime:
    registry = TelegramBotRegistry(bots)
    runtime_logger = logger or LOGGER

    async def send_message(bot_name: str, chat_id: int, text: str) -> None:
        await registry.send_text(bot_name, chat_id, text)

    orchestrator = PairOrchestrator(
        runtime_config=runtime_config,
        context_manager=ContextManager(
            runtime_config.context_md_path,
            chat_path_template=runtime_config.chat_context_path_template,
        ),
        send_message=send_message,
        cli_runner=cli_runner if cli_runner is not None else run_cli,
    )
    processor = RoutedTelegramMessageProcessor(runtime_config, orchestrator, logger=runtime_logger)
    return TelegramRuntime(
        processor,
        registry,
        dedup_cache=DedupCache(ttl_seconds=runtime_config.dedup_ttl_seconds),
        logger=runtime_logger,
    )


def create_aiogram_bots(runtime_config: RuntimeConfig) -> dict[str, Any]:
    if Bot is None:
        raise RuntimeError("aiogram must be installed to create Telegram bots")
    return {
        bot_config.name: Bot(token=bot_config.telegram_token)
        for bot_config in runtime_config.bot_configs
    }


def build_dispatcher(runtime: TelegramRuntime, receiver_bot: str) -> Any:
    if Dispatcher is None:
        raise RuntimeError("aiogram must be installed to build dispatchers")

    dispatcher = Dispatcher()

    @dispatcher.message()
    async def handle_message(message: Any) -> None:
        await runtime.handle_update(receiver_bot, message)

    return dispatcher


async def poll_bots(runtime: TelegramRuntime, bots: Mapping[str, Any]) -> None:
    dispatchers = {name: build_dispatcher(runtime, name) for name in bots}
    tasks = [
        asyncio.create_task(dispatchers[name].start_polling(bot), name=f"poll:{name}")
        for name, bot in bots.items()
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await runtime.close()
