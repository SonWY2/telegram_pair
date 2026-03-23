from telegram_pair.prompts import build_cli_prompt


def test_single_prompt_includes_context_without_prior_output() -> None:
    prompt = build_cli_prompt(
        "Refactor this function",
        recent_context=("Human: previous request", "Claude: previous answer"),
    )

    assert "Recent conversation context:" in prompt
    assert "- Human: previous request" in prompt
    assert "- Claude: previous answer" in prompt
    assert "Current user request:\nRefactor this function" in prompt
    assert "Prior bot output to consider:" not in prompt


def test_followup_prompt_includes_prior_bot_output() -> None:
    prompt = build_cli_prompt(
        "Compare and improve the first draft",
        recent_context=("Human: initial prompt",),
        prior_bot_name="ClaudeCodeBot",
        prior_bot_output="Here is my first draft.",
    )

    assert "Current user request:\nCompare and improve the first draft" in prompt
    assert "Prior bot output to consider:" in prompt
    assert "ClaudeCodeBot responded with:\nHere is my first draft." in prompt


def test_blank_context_entries_are_ignored() -> None:
    prompt = build_cli_prompt(
        "Ship it",
        recent_context=("", "   ", "Human: one useful line"),
    )

    assert prompt.count("- ") == 1
    assert "- Human: one useful line" in prompt
