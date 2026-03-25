from __future__ import annotations

from pathlib import Path

import pytest

from telegram_pair.config import ConfigError, load_config


def test_load_config_reads_dotenv_when_env_not_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "TELEGRAM_TOKEN_CLAUDE=dotenv-claude-token",
                "TELEGRAM_TOKEN_CODEX=dotenv-codex-token",
                "CLAUDE_CLI_EXECUTABLE=/bin/echo",
                "CODEX_CLI_EXECUTABLE=/bin/echo",
                "TELEGRAM_PAIR_WORKSPACE_DIR=./custom-runtime",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_TOKEN_CLAUDE", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN_CODEX", raising=False)
    monkeypatch.delenv("CLAUDE_CLI_EXECUTABLE", raising=False)
    monkeypatch.delenv("CODEX_CLI_EXECUTABLE", raising=False)
    monkeypatch.delenv("TELEGRAM_PAIR_WORKSPACE_DIR", raising=False)

    config = load_config()

    assert config.get_bot("ClaudeCodeBot").telegram_token == "dotenv-claude-token"
    assert config.get_bot("CodexPairBot").telegram_token == "dotenv-codex-token"
    assert config.workspace_dir == (tmp_path / "custom-runtime").resolve()


def test_load_config_prefers_real_environment_over_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TELEGRAM_TOKEN_CLAUDE=dotenv-claude-token",
                "TELEGRAM_TOKEN_CODEX=dotenv-codex-token",
                "CLAUDE_CLI_EXECUTABLE=/bin/echo",
                "CODEX_CLI_EXECUTABLE=/bin/echo",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_TOKEN_CLAUDE", "env-claude-token")
    monkeypatch.setenv("TELEGRAM_TOKEN_CODEX", "env-codex-token")
    monkeypatch.setenv("CLAUDE_CLI_EXECUTABLE", "/bin/echo")
    monkeypatch.setenv("CODEX_CLI_EXECUTABLE", "/bin/echo")

    config = load_config()

    assert config.get_bot("ClaudeCodeBot").telegram_token == "env-claude-token"
    assert config.get_bot("CodexPairBot").telegram_token == "env-codex-token"


def test_load_config_with_explicit_env_mapping_does_not_read_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TELEGRAM_TOKEN_CLAUDE=dotenv-claude-token",
                "TELEGRAM_TOKEN_CODEX=dotenv-codex-token",
                "CLAUDE_CLI_EXECUTABLE=/bin/echo",
                "CODEX_CLI_EXECUTABLE=/bin/echo",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    explicit = {
        "TELEGRAM_TOKEN_CLAUDE": "mapping-claude-token",
        "TELEGRAM_TOKEN_CODEX": "mapping-codex-token",
        "CLAUDE_CLI_EXECUTABLE": "/bin/echo",
        "CODEX_CLI_EXECUTABLE": "/bin/echo",
    }

    config = load_config(explicit)

    assert config.get_bot("ClaudeCodeBot").telegram_token == "mapping-claude-token"
    assert config.get_bot("CodexPairBot").telegram_token == "mapping-codex-token"


def test_load_config_reads_chat_context_path_template(tmp_path: Path) -> None:
    config = load_config(
        {
            "TELEGRAM_TOKEN_CLAUDE": "claude-token",
            "TELEGRAM_TOKEN_CODEX": "codex-token",
            "CLAUDE_CLI_EXECUTABLE": "/bin/echo",
            "CODEX_CLI_EXECUTABLE": "/bin/echo",
            "TELEGRAM_PAIR_WORKSPACE_DIR": str(tmp_path / "runtime"),
            "TELEGRAM_PAIR_CHAT_CONTEXT_PATH_TEMPLATE": "chat-history/{chat_id}.md",
        }
    )

    assert config.chat_context_path_template == "chat-history/{chat_id}.md"


def test_load_config_rejects_unknown_chat_context_template_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            {
                "TELEGRAM_TOKEN_CLAUDE": "claude-token",
                "TELEGRAM_TOKEN_CODEX": "codex-token",
                "CLAUDE_CLI_EXECUTABLE": "/bin/echo",
                "CODEX_CLI_EXECUTABLE": "/bin/echo",
                "TELEGRAM_PAIR_WORKSPACE_DIR": str(tmp_path / "runtime"),
                "TELEGRAM_PAIR_CHAT_CONTEXT_PATH_TEMPLATE": "chat-history/{unknown}.md",
            }
        )


def test_load_config_exposes_session_defaults_and_force_context_restack(tmp_path: Path) -> None:
    config = load_config(
        {
            "TELEGRAM_TOKEN_CLAUDE": "claude-token",
            "TELEGRAM_TOKEN_CODEX": "codex-token",
            "CLAUDE_CLI_EXECUTABLE": "/bin/echo",
            "CODEX_CLI_EXECUTABLE": "/bin/echo",
            "TELEGRAM_PAIR_WORKSPACE_DIR": str(tmp_path / "runtime"),
            "TELEGRAM_PAIR_FORCE_CONTEXT_RESTACK": "true",
        }
    )

    claude = config.get_bot("ClaudeCodeBot")
    codex = config.get_bot("CodexPairBot")

    assert config.force_context_restack is True
    assert claude.session_mode == "stateless"
    assert claude.session_start_args == ()
    assert claude.session_resume_args == ()
    assert claude.session_output_format == "text"
    assert codex.session_mode == "resume"
    assert codex.session_start_args == ("exec", "--skip-git-repo-check", "--json")
    assert codex.session_resume_args == ("exec", "resume", "--skip-git-repo-check", "--json")
    assert codex.session_output_format == "json"


def test_load_config_reads_session_override_env_keys(tmp_path: Path) -> None:
    config = load_config(
        {
            "TELEGRAM_TOKEN_CLAUDE": "claude-token",
            "TELEGRAM_TOKEN_CODEX": "codex-token",
            "CLAUDE_CLI_EXECUTABLE": "/bin/echo",
            "CODEX_CLI_EXECUTABLE": "/bin/echo",
            "CLAUDE_BOT_NAME_SESSION_MODE": "resume",
            "CLAUDE_BOT_NAME_SESSION_START_ARGS": "exec --json",
            "CLAUDE_BOT_NAME_SESSION_RESUME_ARGS": "exec resume --json",
            "CLAUDE_BOT_NAME_SESSION_OUTPUT_FORMAT": "json",
            "CODEX_BOT_NAME_SESSION_MODE": "stateless",
            "CODEX_BOT_NAME_SESSION_START_ARGS": "",
            "CODEX_BOT_NAME_SESSION_RESUME_ARGS": "",
            "CODEX_BOT_NAME_SESSION_OUTPUT_FORMAT": "text",
        }
    )

    claude = config.get_bot("ClaudeCodeBot")
    codex = config.get_bot("CodexPairBot")

    assert claude.session_mode == "resume"
    assert claude.session_start_args == ("exec", "--json")
    assert claude.session_resume_args == ("exec", "resume", "--json")
    assert claude.session_output_format == "json"
    assert codex.session_mode == "stateless"
    assert codex.session_start_args == ()
    assert codex.session_resume_args == ()
    assert codex.session_output_format == "text"
