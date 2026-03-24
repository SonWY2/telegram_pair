from telegram_pair.config import BotConfig
from telegram_pair.models import BroadcastStrategy, RouteDecision, RouteMode
from telegram_pair.router import route_message, route_message_from_bot_configs


BOT_ALIASES = {
    "ClaudeCodeBot": ("@ClaudeCodeBot",),
    "CodexPairBot": ("@CodexPairBot",),
}
BOT_ORDER = ("ClaudeCodeBot", "CodexPairBot")


def test_single_claude_mention_routes_to_claude() -> None:
    decision = route_message(
        "@ClaudeCodeBot hello there",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.SINGLE,
        target_bot_names=("ClaudeCodeBot",),
        normalized_text="hello there",
        reason="single-mention",
    )


def test_single_codex_mention_routes_to_codex() -> None:
    decision = route_message(
        "@CodexPairBot hello there",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.SINGLE,
        target_bot_names=("CodexPairBot",),
        normalized_text="hello there",
        reason="single-mention",
    )


def test_semicolon_routes_to_parallel_broadcast() -> None:
    decision = route_message(
        "; compare two implementations",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="compare two implementations",
        broadcast_strategy=BroadcastStrategy.PARALLEL,
        reason="semicolon",
    )


def test_semicolon_team_routes_to_team_strategy() -> None:
    decision = route_message(
        "; team compare two implementations",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="compare two implementations",
        broadcast_strategy=BroadcastStrategy.TEAM,
        reason="semicolon",
    )


def test_semicolon_seq_routes_to_sequential_strategy() -> None:
    decision = route_message(
        "; seq compare two implementations",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="compare two implementations",
        broadcast_strategy=BroadcastStrategy.SEQUENTIAL,
        reason="semicolon",
    )


def test_semicolon_seq_colon_routes_to_sequential_strategy() -> None:
    decision = route_message(
        "; seq: compare two implementations",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="compare two implementations",
        broadcast_strategy=BroadcastStrategy.SEQUENTIAL,
        reason="semicolon",
    )


def test_semicolon_team_colon_routes_to_team_strategy() -> None:
    decision = route_message(
        "; team: compare two implementations",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="compare two implementations",
        broadcast_strategy=BroadcastStrategy.TEAM,
        reason="semicolon",
    )


def test_dual_mentions_route_to_parallel_broadcast() -> None:
    decision = route_message(
        "@CodexPairBot @ClaudeCodeBot propose then refine",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="propose then refine",
        broadcast_strategy=BroadcastStrategy.PARALLEL,
        reason="dual-mention",
    )


def test_bot_authored_message_is_ignored() -> None:
    decision = route_message(
        "@ClaudeCodeBot hello there",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
        is_bot_author=True,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.target_bot_names == ()


def test_empty_prompt_after_stripping_mentions_is_ignored() -> None:
    decision = route_message(
        "@ClaudeCodeBot   ",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.normalized_text == ""


def test_empty_team_prompt_is_ignored() -> None:
    decision = route_message(
        "; team:",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "empty-broadcast"


def test_empty_seq_prompt_is_ignored() -> None:
    decision = route_message(
        "; seq:",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "empty-broadcast"


def test_bare_team_prompt_is_ignored() -> None:
    decision = route_message(
        "; team",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "empty-broadcast"


def test_bare_seq_prompt_is_ignored() -> None:
    decision = route_message(
        "; seq",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "empty-broadcast"


def test_telegram_slash_command_is_ignored() -> None:
    decision = route_message(
        "/start",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "telegram-command"


def test_telegram_slash_command_with_bot_suffix_is_ignored() -> None:
    decision = route_message(
        "/start@wy_codex_bot",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.IGNORE
    assert decision.reason == "telegram-command"


def test_mentions_are_stripped_from_prompt_text() -> None:
    decision = route_message(
        "@ClaudeCodeBot can you pair with @CodexPairBot on this?",
        bot_aliases=BOT_ALIASES,
        bot_order=BOT_ORDER,
    )

    assert decision.mode is RouteMode.BROADCAST
    assert "@ClaudeCodeBot" not in decision.normalized_text
    assert "@CodexPairBot" not in decision.normalized_text
    assert decision.normalized_text == "can you pair with on this?"


def test_route_message_from_bot_configs_uses_priority_and_aliases() -> None:
    decision = route_message_from_bot_configs(
        "@CodexPairBot @ClaudeCodeBot refine this",
        bot_configs=(
            BotConfig(
                name="CodexPairBot",
                telegram_token="token-b",
                cli_executable="/bin/echo",
                cli_args=(),
                priority=2,
                mention_aliases=("@CodexPairBot", "CodexPairBot"),
            ),
            BotConfig(
                name="ClaudeCodeBot",
                telegram_token="token-a",
                cli_executable="/bin/echo",
                cli_args=(),
                priority=1,
                mention_aliases=("@ClaudeCodeBot", "ClaudeCodeBot"),
            ),
        ),
    )

    assert decision == RouteDecision(
        mode=RouteMode.BROADCAST,
        target_bot_names=("ClaudeCodeBot", "CodexPairBot"),
        normalized_text="refine this",
        broadcast_strategy=BroadcastStrategy.PARALLEL,
        reason="dual-mention",
    )
