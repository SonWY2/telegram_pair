from __future__ import annotations

import re
from typing import Mapping, Sequence

from .config import BotConfig
from .models import RouteDecision, RouteMode


MENTION_PATTERN_TEMPLATE = r"(?<!\w){alias}(?!\w)"


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
    - `; message` broadcasts to all bots in priority order
    - a single bot mention targets only that bot
    - mentions for both bots trigger broadcast in priority order
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

    if text.startswith(";"):
        prompt_text = _normalize_prompt_text(text[1:], bot_aliases)
        if not prompt_text:
            return RouteDecision(mode=RouteMode.IGNORE, reason="empty-broadcast")
        return RouteDecision(
            mode=RouteMode.BROADCAST,
            target_bot_names=tuple(bot_order),
            normalized_text=prompt_text,
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


def _normalize_prompt_text(text: str, bot_aliases: Mapping[str, Sequence[str]]) -> str:
    normalized = text
    for aliases in bot_aliases.values():
        for alias in aliases:
            normalized = re.sub(_mention_pattern(alias), " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip(" \n\t;")
    return normalized.strip()


def _mention_pattern(alias: str) -> str:
    return MENTION_PATTERN_TEMPLATE.format(alias=re.escape(alias))
