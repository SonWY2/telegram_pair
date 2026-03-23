from __future__ import annotations

from tests.test_telegram_app import FakeBot, FakeChat, FakeMessage
from telegram_pair.telegram_app import DedupCache, TelegramBotRegistry, TelegramRuntime


class EchoProcessor:
    def __init__(self, runtime: TelegramRuntime) -> None:
        self.runtime = runtime
        self.seen = []

    async def process_telegram_message(self, inbound) -> None:
        self.seen.append(inbound)
        await self.runtime.send_reply(
            "codex",
            inbound.chat_id,
            f"echo:{inbound.text}",
            reply_to_message_id=inbound.message_id,
        )


async def test_runtime_handles_human_message_and_routes_reply_with_target_bot():
    bots = {
        "claude": FakeBot("claude"),
        "codex": FakeBot("codex"),
    }
    registry = TelegramBotRegistry(bots)
    runtime = TelegramRuntime(processor=None, bot_registry=registry, dedup_cache=DedupCache())  # type: ignore[arg-type]
    processor = EchoProcessor(runtime)
    runtime._processor = processor  # type: ignore[assignment]

    handled = await runtime.handle_update(
        "claude",
        FakeMessage(chat=FakeChat(42), message_id=11, text="; pair this"),
    )

    assert handled is True
    assert [entry.text for entry in processor.seen] == ["; pair this"]
    assert bots["claude"].sent_messages == []
    assert bots["codex"].sent_messages == [
        {
            "bot": "codex",
            "chat_id": 42,
            "text": "echo:; pair this",
            "reply_to_message_id": 11,
        }
    ]
