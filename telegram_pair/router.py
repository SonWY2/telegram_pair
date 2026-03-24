from __future__ import annotations

import re
from typing import Mapping, Sequence

from .config import BotConfig
from .models import BroadcastStrategy, RouteDecision, RouteMode


MENTION_PATTERN_TEMPLATE = r"(?<!\w){alias}(?!\w)"
TELEGRAM_COMMAND_PATTERN = re.compile(r"^/[A-Za-z0-9_]+(?:@[A-Za-z0-9_]+)?(?:\s|$)")
TEAM_PREFIX_PATTERN = re.compile(r"^team(?::|\s+|$)(?P<body>.*)$", flags=re.IGNORECASE | re.DOTALL)
SEQUENTIAL_PREFIX_PATTERN = re.compile(r"^(?:seq|sequential)(?::|\s+|$)(?P<body>.*)$", flags=re.IGNORECASE | re.DOTALL)


def route_message(
    message_text: str | None,
    *,
    bot_aliases: Mapping[str, Sequence[str]],
    bot_order: Sequence[str],
    is_bot_author: bool = False,
) -> RouteDecision:
    """
    Route a Telegram message by content instead of by receiving bot token.

    Rules:
    - bot-authored messages are always ignored
    - `; message` broadcasts to all bots in parallel
    - `; seq ...` / `; seq: ...` run the sequential review workflow
    - `; team ...` and `; team: ...` run the team workflow
    - a single bot mention targets only that bot
    - mentions for both bots trigger the same broadcast mode as `;`
    - routed prompt text has trigger markers stripped
    """
    return _route_message_impl(
        message_text,
        bot_aliases=bot_aliases,
        bot_order=bot_order,
        is_bot_author=is_bot_author,
    )


def route_message_from_bot_configs(
    message_text: str | None,
    *,
    bot_configs: Sequence[BotConfig],
    is_bot_author: bool = False,
) -> RouteDecision:
    ordered = tuple(sorted(bot_configs, key=lambda bot: bot.priority))
    return _route_message_impl(
        message_text,
        bot_aliases={bot.name: bot.mention_aliases for bot in ordered},
        bot_order=tuple(bot.name for bot in ordered),
        is_bot_author=is_bot_author,
    )


def _route_message_impl(
    message_text: str | None,
    *,
    bot_aliases: Mapping[str, Sequence[str]],
    bot_order: Sequence[str],
    is_bot_author: bool,
) -> RouteDecision:
    text = (message_text or "").strip()
    if is_bot_author or not text:
        return RouteDecision(mode=RouteMode.IGNORE, reason="empty")
    if _is_telegram_command(text):
        return RouteDecision(mode=RouteMode.IGNORE, reason="telegram-command")

    if text.startswith(";"):
        strategy, prompt_text = _parse_semicolon_command(text[1:], bot_aliases)
        if not prompt_text:
            return RouteDecision(mode=RouteMode.IGNORE, reason="empty-broadcast")
        return RouteDecision(
            mode=RouteMode.BROADCAST,
            target_bot_names=tuple(bot_order),
            normalized_text=prompt_text,
            broadcast_strategy=strategy,
            reason="semicolon",
        )

    mentioned_bots = _find_mentioned_bots(text, bot_aliases, bot_order)
    prompt_text = _normalize_prompt_text(text, bot_aliases)
    if not prompt_text:
        return RouteDecision(mode=RouteMode.IGNORE, reason="empty-after-strip")

    if len(mentioned_bots) >= 2:
        return RouteDecision(
            mode=RouteMode.BROADCAST,
            target_bot_names=tuple(mentioned_bots),
            normalized_text=prompt_text,
            broadcast_strategy=BroadcastStrategy.PARALLEL,
            reason="dual-mention",
        )
    if len(mentioned_bots) == 1:
        return RouteDecision(
            mode=RouteMode.SINGLE,
            target_bot_names=(mentioned_bots[0],),
            normalized_text=prompt_text,
            reason="single-mention",
        )
    return RouteDecision(mode=RouteMode.IGNORE, reason="no-trigger")


def _find_mentioned_bots(
    text: str,
    bot_aliases: Mapping[str, Sequence[str]],
    bot_order: Sequence[str],
) -> list[str]:
    mentioned: list[str] = []
    for bot_name in bot_order:
        aliases = bot_aliases.get(bot_name, ())
        if any(_contains_alias(text, alias) for alias in aliases):
            mentioned.append(bot_name)
    return mentioned


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(_mention_pattern(alias), text, flags=re.IGNORECASE) is not None


def _parse_semicolon_command(
    text: str,
    bot_aliases: Mapping[str, Sequence[str]],
) -> tuple[BroadcastStrategy, str]:
    stripped = text.strip()
    match = TEAM_PREFIX_PATTERN.match(stripped)
    if match is not None:
        return (
            BroadcastStrategy.TEAM,
            _normalize_prompt_text(match.group("body") or "", bot_aliases),
        )
    match = SEQUENTIAL_PREFIX_PATTERN.match(stripped)
    if match is not None:
        return (
            BroadcastStrategy.SEQUENTIAL,
            _normalize_prompt_text(match.group("body") or "", bot_aliases),
        )
    return (BroadcastStrategy.PARALLEL, _normalize_prompt_text(stripped, bot_aliases))


def _normalize_prompt_text(text: str, bot_aliases: Mapping[str, Sequence[str]]) -> str:
    normalized = text
    for aliases in bot_aliases.values():
        for alias in aliases:
            normalized = re.sub(_mention_pattern(alias), " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip(" \n\t;")
    return normalized.strip()


def _mention_pattern(alias: str) -> str:
    return MENTION_PATTERN_TEMPLATE.format(alias=re.escape(alias))


def _is_telegram_command(text: str) -> bool:
    return TELEGRAM_COMMAND_PATTERN.match(text) is not None
