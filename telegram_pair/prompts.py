from __future__ import annotations

from typing import Iterable


def build_cli_prompt(
    user_message: str,
    *,
    recent_context: Iterable[str] = (),
    prior_bot_name: str | None = None,
    prior_bot_output: str | None = None,
) -> str:
    sections: list[str] = []

    context_lines = [line.strip() for line in recent_context if line and line.strip()]
    if context_lines:
        sections.append(
            "Recent conversation context:\n" + "\n".join(f"- {line}" for line in context_lines)
        )

    sections.append(f"Current user request:\n{user_message.strip()}")

    if prior_bot_name and prior_bot_output:
        sections.append(
            "Prior bot output to consider:\n"
            f"{prior_bot_name} responded with:\n{prior_bot_output.strip()}"
        )

    sections.append(
        "Respond directly to the user request. "
        "If prior bot output is present, use it as context rather than treating it as a new user turn."
    )

    return "\n\n".join(sections)
