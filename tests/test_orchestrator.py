from __future__ import annotations

import asyncio
from pathlib import Path

from telegram_pair.config import BotConfig, RuntimeConfig
from telegram_pair.context_manager import ContextManager
from telegram_pair.models import BroadcastStrategy, CliResult, RouteDecision, RouteMode
from telegram_pair.orchestrator import PairOrchestrator, render_result_for_telegram


def _runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workspace_dir=tmp_path,
        context_md_path=tmp_path / "context.md",
        chat_context_path_template="{base_stem}/chat_{chat_id}.md",
        timeout_seconds=1,
        max_context_turns=6,
        dedup_ttl_seconds=60,
        progress_notice_delay_seconds=10.0,
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


async def test_parallel_broadcast_runs_bots_concurrently_without_cross_injection(tmp_path: Path) -> None:
    requests = []
    sends = []
    active = 0
    max_active = 0

    async def fake_cli_runner(request):
        nonlocal active, max_active
        requests.append(request)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return CliResult(bot_name=request.bot_name, ok=True, output=f"{request.bot_name} output", duration_seconds=0.03)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    results = await orchestrator.handle_route(
        chat_id=123,
        message_id=11,
        user_text="compare solutions",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="compare solutions",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
            broadcast_strategy=BroadcastStrategy.PARALLEL,
        ),
    )

    assert len(results) == 2
    assert max_active == 2
    assert [request.bot_name for request in requests] == ["ClaudeCodeBot", "CodexPairBot"]
    assert all("compare solutions" in request.prompt for request in requests)
    assert all("Independent bot outputs:" not in request.prompt for request in requests)
    assert {send[0] for send in sends} == {"ClaudeCodeBot", "CodexPairBot"}


async def test_sequential_broadcast_injects_first_output_into_second_prompt(tmp_path: Path) -> None:
    requests = []
    sends = []

    async def fake_cli_runner(request):
        requests.append(request)
        if request.bot_name == "ClaudeCodeBot":
            return CliResult(bot_name=request.bot_name, ok=True, output="first output", duration_seconds=0.01)
        return CliResult(bot_name=request.bot_name, ok=True, output="second output", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    results = await orchestrator.handle_route(
        chat_id=123,
        message_id=12,
        user_text="compare solutions",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="compare solutions",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
            broadcast_strategy=BroadcastStrategy.SEQUENTIAL,
        ),
    )

    assert len(results) == 2
    assert [request.metadata["mode"] for request in requests] == [
        "broadcast_sequential_first",
        "broadcast_sequential_followup",
    ]
    assert "Broadcast coordination:" in requests[1].prompt
    assert "ClaudeCodeBot output:" in requests[1].prompt
    assert "first output" in requests[1].prompt
    assert sends == [
        ("ClaudeCodeBot", 123, "first output"),
        ("CodexPairBot", 123, "second output"),
    ]


async def test_team_route_runs_parallel_then_resolution(tmp_path: Path) -> None:
    requests = []
    sends = []

    async def fake_cli_runner(request):
        requests.append(request)
        if request.metadata["mode"] == "team_resolution":
            return CliResult(bot_name=request.bot_name, ok=True, output="final synthesis", duration_seconds=0.01)
        return CliResult(bot_name=request.bot_name, ok=True, output=f"{request.bot_name} draft", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    results = await orchestrator.handle_route(
        chat_id=456,
        message_id=22,
        user_text="비트코인 전망을 비교하고 토론해줘",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="비트코인 전망을 비교하고 토론해줘",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
            broadcast_strategy=BroadcastStrategy.TEAM,
        ),
    )

    assert len(results) == 3
    assert [request.metadata["mode"] for request in requests] == [
        "broadcast_parallel",
        "broadcast_parallel",
        "team_resolution",
    ]
    assert requests[-1].bot_name == "CodexPairBot"
    assert "ClaudeCodeBot output:" in requests[-1].prompt
    assert "CodexPairBot output:" in requests[-1].prompt
    assert "final consolidated response" in requests[-1].prompt
    assert sends == [
        ("ClaudeCodeBot", 456, "ClaudeCodeBot draft"),
        ("CodexPairBot", 456, "final synthesis"),
    ]


async def test_team_route_carries_failure_notes_into_resolution(tmp_path: Path) -> None:
    requests = []

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
        return None

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    await orchestrator.handle_route(
        chat_id=456,
        message_id=22,
        user_text="help me recover",
        route=RouteDecision(
            mode=RouteMode.BROADCAST,
            normalized_text="help me recover",
            target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
            broadcast_strategy=BroadcastStrategy.TEAM,
        ),
    )

    assert requests[-1].metadata["mode"] == "team_resolution"
    assert "Failure notes:" in requests[-1].prompt
    assert "timeout" in requests[-1].prompt


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


async def test_orchestrator_loads_context_only_from_same_chat(tmp_path: Path) -> None:
    requests = []

    async def fake_cli_runner(request):
        requests.append(request)
        return CliResult(bot_name=request.bot_name, ok=True, output="done", duration_seconds=0.01)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        return None

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)
    route = RouteDecision(
        mode=RouteMode.SINGLE,
        normalized_text="hello",
        target_bot_names=("ClaudeCodeBot",),
    )

    await orchestrator.handle_route(chat_id=100, message_id=1, user_text="chat one only", route=route)
    await orchestrator.handle_route(chat_id=200, message_id=2, user_text="chat two only", route=route)
    await orchestrator.handle_route(chat_id=100, message_id=3, user_text="chat one again", route=route)

    assert requests[0].context_excerpt == ""
    assert requests[1].context_excerpt == ""
    assert "chat one only" in requests[2].context_excerpt
    assert "chat two only" not in requests[2].context_excerpt


def test_render_result_for_telegram_truncates_bkit_tail() -> None:
    result = CliResult(
        bot_name="ClaudeCodeBot",
        ok=True,
        output="안녕하세요\n\n좋습니다.\n────────────────\n📊 bkit Feature Usage\n뒤는 제거",
        duration_seconds=0.01,
    )

    rendered = render_result_for_telegram(result)

    assert "bkit Feature Usage" not in rendered
    assert "뒤는 제거" not in rendered
    assert rendered == "안녕하세요\n\n좋습니다.\n────────────────"


def test_render_result_for_telegram_keeps_error_text_untouched() -> None:
    result = CliResult(
        bot_name="ClaudeCodeBot",
        ok=False,
        output="",
        duration_seconds=0.01,
        error_type="non_zero_exit",
        error_message="bkit Feature Usage appeared in stderr",
    )

    rendered = render_result_for_telegram(result)

    assert "bkit Feature Usage appeared in stderr" in rendered


async def test_help_and_model_commands(tmp_path: Path) -> None:
    sends = []

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send)

    handled = await orchestrator.handle_app_command(chat_id=1, command_text="/help")
    assert handled is True
    assert "Telegram Pair 도움말" in sends[-1][2]
    assert "이 함수 리팩터링해줘" in sends[-1][2]
    assert "이 테스트 실패 원인 찾아줘" in sends[-1][2]
    assert "; team 비트코인 전망을 각각 분석" in sends[-1][2]
    assert "; seq 이 설계를 먼저 제안" in sends[-1][2]
    assert "/help 와 /model만 앱 명령으로 처리" in sends[-1][2]

    handled = await orchestrator.handle_app_command(chat_id=1, command_text="/model status")
    assert handled is True
    assert "현재 모델 설정:" in sends[-1][2]

    handled = await orchestrator.handle_app_command(
        chat_id=1,
        command_text="/model codex gpt-5.4",
    )
    assert handled is True
    assert sends[-1] == ("CodexPairBot", 1, "모델 변경 완료: CodexPairBot -> gpt-5.4")
    assert orchestrator.model_registry.get_model("CodexPairBot") == "gpt-5.4"


async def test_slow_single_route_emits_delayed_progress_notice(tmp_path: Path) -> None:
    sends = []

    async def fake_cli_runner(request):
        await asyncio.sleep(0.03)
        return CliResult(bot_name=request.bot_name, ok=True, output="done", duration_seconds=0.03)

    async def fake_send(bot_name: str, chat_id: int, text: str) -> None:
        sends.append((bot_name, chat_id, text))

    runtime = _runtime_config(tmp_path)
    runtime = RuntimeConfig(
        workspace_dir=runtime.workspace_dir,
        context_md_path=runtime.context_md_path,
        chat_context_path_template=runtime.chat_context_path_template,
        timeout_seconds=runtime.timeout_seconds,
        max_context_turns=runtime.max_context_turns,
        dedup_ttl_seconds=runtime.dedup_ttl_seconds,
        progress_notice_delay_seconds=0.01,
        target_chat_id=runtime.target_chat_id,
        log_level=runtime.log_level,
        bot_configs=runtime.bot_configs,
    )
    orchestrator = PairOrchestrator(runtime, ContextManager(runtime.context_md_path), fake_send, fake_cli_runner)

    await orchestrator.handle_route(
        chat_id=77,
        message_id=5,
        user_text="hello",
        route=RouteDecision(
            mode=RouteMode.SINGLE,
            normalized_text="hello",
            target_bot_names=("ClaudeCodeBot",),
        ),
    )

    assert sends == [
        ("ClaudeCodeBot", 77, "⏳ ClaudeCodeBot 작업을 시작합니다..."),
        ("ClaudeCodeBot", 77, "done"),
    ]
