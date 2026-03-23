from __future__ import annotations

from pathlib import Path

import pytest

from telegram_pair.config import load_config


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
