from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from telegram_pair.config import BotConfig, RuntimeConfig
from telegram_pair.telegram_app import (
    DedupCache,
    InboundTelegramMessage,
    RoutedTelegramMessageProcessor,
    TelegramBotRegistry,
    TelegramRuntime,
    poll_bots,
)


@dataclass
class FakeUser:
    is_bot: bool = False


@dataclass
class FakeChat:
    id: int


@dataclass
class FakeMessage:
    chat: FakeChat
    message_id: int
    text: str | None = None
    caption: str | None = None
    from_user: FakeUser = field(default_factory=FakeUser)


@dataclass
class FakeUpdate:
    message: FakeMessage | None = None


class RecordingProcessor:
    def __init__(self) -> None:
        self.messages = []

    async def process_telegram_message(self, inbound) -> None:
        self.messages.append(inbound)


class FakeBot:
    def __init__(self, name: str) -> None:
        self.name = name
        self.sent_messages: list[dict] = []
        self.session = FakeSession()

    async def send_message(self, chat_id: int, text: str, *, reply_to_message_id: int | None = None):
        payload = {
            "bot": self.name,
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
        }
        self.sent_messages.append(payload)
        return payload


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def build_runtime(ttl_seconds: float = 60.0):
    processor = RecordingProcessor()
    bots = {
        "claude": FakeBot("claude"),
        "codex": FakeBot("codex"),
    }
    runtime = TelegramRuntime(
        processor,
        TelegramBotRegistry(bots),
        dedup_cache=DedupCache(ttl_seconds=ttl_seconds),
    )
    return runtime, processor, bots


def build_runtime_config(tmp_path: Path, *, target_chat_id: int | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        workspace_dir=tmp_path,
        context_md_path=tmp_path / "context.md",
        timeout_seconds=5,
        max_context_turns=6,
        dedup_ttl_seconds=90,
        progress_notice_delay_seconds=10.0,
        target_chat_id=target_chat_id,
        log_level="INFO",
        bot_configs=(
            BotConfig(
                name="ClaudeCodeBot",
                telegram_token="token-a",
                cli_executable="/bin/echo",
                cli_args=(),
                priority=1,
                mention_aliases=("@ClaudeCodeBot", "ClaudeCodeBot"),
            ),
            BotConfig(
                name="CodexPairBot",
                telegram_token="token-b",
                cli_executable="/bin/echo",
                cli_args=(),
                priority=2,
                mention_aliases=("@CodexPairBot", "CodexPairBot"),
            ),
        ),
    )


async def test_duplicate_updates_are_processed_once():
    runtime, processor, _ = build_runtime()
    update = FakeUpdate(FakeMessage(chat=FakeChat(1), message_id=99, text="; compare"))

    first = await runtime.handle_update("claude", update)
    second = await runtime.handle_update("codex", update)

    assert first is True
    assert second is False
    assert [message.text for message in processor.messages] == ["; compare"]


async def test_different_messages_in_same_chat_are_both_processed():
    runtime, processor, _ = build_runtime()

    first = await runtime.handle_update("claude", FakeMessage(chat=FakeChat(7), message_id=1, text="@Claude hi"))
    second = await runtime.handle_update("codex", FakeMessage(chat=FakeChat(7), message_id=2, text="@Codex hi"))

    assert first is True
    assert second is True
    assert [message.message_id for message in processor.messages] == [1, 2]


async def test_bot_authored_updates_are_ignored():
    runtime, processor, _ = build_runtime()
    message = FakeMessage(chat=FakeChat(2), message_id=3, text="@Claude hi", from_user=FakeUser(is_bot=True))

    handled = await runtime.handle_update("claude", message)

    assert handled is False
    assert processor.messages == []


async def test_caption_messages_are_processed_when_text_is_missing():
    runtime, processor, _ = build_runtime()
    message = FakeMessage(chat=FakeChat(3), message_id=4, text=None, caption="; from caption")

    handled = await runtime.handle_update("codex", message)

    assert handled is True
    assert [entry.text for entry in processor.messages] == ["; from caption"]


async def test_send_reply_uses_correct_bot_and_chunks_long_messages():
    runtime, _, bots = build_runtime()
    long_text = "line\n" * 1200

    await runtime.send_reply("codex", 5, long_text, reply_to_message_id=123)

    assert bots["claude"].sent_messages == []
    assert len(bots["codex"].sent_messages) >= 2
    assert bots["codex"].sent_messages[0]["reply_to_message_id"] == 123
    assert all(message["chat_id"] == 5 for message in bots["codex"].sent_messages)


async def test_routed_processor_calls_orchestrator_with_normalized_text(tmp_path: Path):
    calls = []

    class FakeOrchestrator:
        async def handle_model_command(self, **kwargs):
            return False

        async def handle_route(self, **kwargs):
            calls.append(kwargs)
            return []

    processor = RoutedTelegramMessageProcessor(
        build_runtime_config(tmp_path),
        FakeOrchestrator(),  # type: ignore[arg-type]
    )

    await processor.process_telegram_message(
        InboundTelegramMessage(
            receiver_bot="ClaudeCodeBot",
            chat_id=321,
            message_id=88,
            text="@ClaudeCodeBot refine this",
        )
    )

    assert len(calls) == 1
    assert calls[0]["chat_id"] == 321
    assert calls[0]["message_id"] == 88
    assert calls[0]["user_text"] == "refine this"
    assert calls[0]["route"].target_bot_names == ("ClaudeCodeBot",)


async def test_routed_processor_skips_non_target_chat(tmp_path: Path):
    calls = []

    class FakeOrchestrator:
        async def handle_model_command(self, **kwargs):
            return False

        async def handle_route(self, **kwargs):
            calls.append(kwargs)
            return []

    processor = RoutedTelegramMessageProcessor(
        build_runtime_config(tmp_path, target_chat_id=999),
        FakeOrchestrator(),  # type: ignore[arg-type]
    )

    await processor.process_telegram_message(
        InboundTelegramMessage(
            receiver_bot="ClaudeCodeBot",
            chat_id=111,
            message_id=7,
            text="; compare this",
        )
    )

    assert calls == []


async def test_routed_processor_ignores_telegram_slash_commands(tmp_path: Path):
    calls = []

    class FakeOrchestrator:
        async def handle_model_command(self, **kwargs):
            return False

        async def handle_route(self, **kwargs):
            calls.append(kwargs)
            return []

    processor = RoutedTelegramMessageProcessor(
        build_runtime_config(tmp_path),
        FakeOrchestrator(),  # type: ignore[arg-type]
    )

    await processor.process_telegram_message(
        InboundTelegramMessage(
            receiver_bot="ClaudeCodeBot",
            chat_id=111,
            message_id=12,
            text="/start@wy_codex_bot",
        )
    )

    assert calls == []


async def test_routed_processor_handles_model_command_before_router(tmp_path: Path):
    route_calls = []
    model_calls = []

    class FakeOrchestrator:
        async def handle_model_command(self, **kwargs):
            model_calls.append(kwargs)
            return True

        async def handle_route(self, **kwargs):
            route_calls.append(kwargs)
            return []

    processor = RoutedTelegramMessageProcessor(
        build_runtime_config(tmp_path),
        FakeOrchestrator(),  # type: ignore[arg-type]
    )

    await processor.process_telegram_message(
        InboundTelegramMessage(
            receiver_bot="ClaudeCodeBot",
            chat_id=111,
            message_id=13,
            text="/model status",
        )
    )

    assert len(model_calls) == 1
    assert route_calls == []


async def test_poll_bots_closes_sessions_on_cancellation(monkeypatch):
    runtime, _, bots = build_runtime()

    class FakeDispatcher:
        async def start_polling(self, bot):
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

    monkeypatch.setattr(
        "telegram_pair.telegram_app.build_dispatcher",
        lambda runtime, receiver_bot: FakeDispatcher(),
    )

    task = asyncio.create_task(poll_bots(runtime, bots))
    await asyncio.sleep(0)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert bots["claude"].session.closed is True
    assert bots["codex"].session.closed is True
