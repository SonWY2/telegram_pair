from __future__ import annotations

import asyncio
from pathlib import Path

from telegram_pair.config import BotConfig, RuntimeConfig
from telegram_pair.context_manager import ContextManager
from telegram_pair.models import CliResult, RouteDecision, RouteMode
from telegram_pair.orchestrator import PairOrchestrator


def _runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workspace_dir=tmp_path,
        context_md_path=tmp_path / "context.md",
        timeout_seconds=1,
        max_context_turns=6,
        dedup_ttl_seconds=60,
        target_chat_id=None,
        log_level="INFO",
        bot_configs=(
            BotConfig(
                name="ClaudeCodeBot",
                telegram_token="token-a",
                cli_executable="python",
                cli_args=("-V",),
                priority=1,
                mention_aliases=("@ClaudeCodeBot",),
            ),
            BotConfig(
                name="CodexPairBot",
                telegram_token="token-b",
                cli_executable="python",
                cli_args=("-V",),
                priority=2,
                mention_aliases=("@CodexPairBot",),
            ),
        ),
    )


async def test_single_route_calls_one_cli_and_send(tmp_path: Path) -> None:
    requests = []
    sends = []

    async def fake_cli_runner(request):
        requests.append(request)
        return CliResult(bot_name=request.bot_name, ok=True, output="done", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    results = await orchestrator.handle_route(
        chat_id=123,
        message_id=10,
        user_text="hello",
        route=RouteDecision(
            mode=RouteMode.SINGLE,
            normalized_text="hello",
            target_bot_names=("ClaudeCodeBot",),
        ),
    )

    assert len(results) == 1
    assert len(requests) == 1
    assert requests[0].bot_name == "ClaudeCodeBot"
    assert sends == [("ClaudeCodeBot", 123, "done")]


async def test_broadcast_route_injects_first_output_into_second_prompt(tmp_path: Path) -> None:
    requests = []
    sends = []

    async def fake_cli_runner(request):
        requests.append(request)
        if request.bot_name == "ClaudeCodeBot":
            return CliResult(bot_name=request.bot_name, ok=True, output="first output", duration_seconds=0.01)
        return CliResult(bot_name=request.bot_name, ok=True, output="second output", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    await orchestrator.handle_route(
        chat_id=123,
        message_id=11,
        user_text="compare solutions",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="compare solutions",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        ),
    )

    assert [request.bot_name for request in requests] == ["ClaudeCodeBot", "CodexPairBot"]
    assert "first output" in requests[1].prompt
    assert "compare solutions" in requests[1].prompt
    assert sends == [("ClaudeCodeBot", "first output"), ("CodexPairBot", "second output")]


async def test_broadcast_continues_after_first_failure(tmp_path: Path) -> None:
    requests = []
    sends = []

    async def fake_cli_runner(request):
        requests.append(request)
        if request.bot_name == "ClaudeCodeBot":
            return CliResult(
                bot_name=request.bot_name,
                ok=False,
                output="",
                duration_seconds=0.01,
                error_type="timeout",
                error_message="Timed out after 1 seconds",
            )
        return CliResult(bot_name=request.bot_name, ok=True, output="codex recovered", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    results = await orchestrator.handle_route(
        chat_id=456,
        message_id=22,
        user_text="help me recover",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="help me recover",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        ),
    )

    assert len(results) == 2
    assert requests[1].bot_name == "CodexPairBot"
    assert "Failure note:" in requests[1].prompt
    assert "timeout" in requests[1].prompt
    assert sends[0][0] == "ClaudeCodeBot"
    assert "CLI error" in sends[0][1]
    assert sends[1] == ("CodexPairBot", "codex recovered")


async def test_orchestrator_serializes_same_chat(tmp_path: Path) -> None:
    active = 0
    max_active = 0

    async def fake_cli_runner(request):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return CliResult(bot_name=request.bot_name, ok=True, output=request.prompt, duration_seconds=0.05)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        return None

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    route = RouteDecision(
        mode=RouteMode.SINGLE,
        normalized_text="hello",
        target_bot_names=("ClaudeCodeBot",),
    )
    await asyncio.gather(
        orchestrator.handle_route(chat_id=999, message_id=1, user_text="one", route=route),
        orchestrator.handle_route(chat_id=999, message_id=2, user_text="two", route=route),
    )

    assert max_active == 1
