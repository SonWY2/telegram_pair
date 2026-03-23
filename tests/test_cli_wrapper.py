from __future__ import annotations

import sys
from pathlib import Path

from telegram_pair.cli_wrapper import run_cli
from telegram_pair.models import CliRequest


async def test_run_cli_success_normalizes_stdout(tmp_path: Path) -> None:
    script = tmp_path / "echo_cli.py"
    script.write_text(
        "import sys\n"
        "data = sys.stdin.read()\n"
        "sys.stdout.write(data.upper() + '\\n')\n",
        encoding="utf-8",
    )
    request = CliRequest(
        bot_name="ClaudeCodeBot",
        executable=sys.executable,
        args=(str(script),),
        prompt="hello world",
        cwd=tmp_path,
        timeout_seconds=2,
    )

    result = await run_cli(request)

    assert result.ok is True
    assert result.output == "HELLO WORLD"
    assert result.error_type is None


async def test_run_cli_handles_non_zero_exit(tmp_path: Path) -> None:
    script = tmp_path / "error_cli.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.write('bad things happened\\n')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    request = CliRequest(
        bot_name="CodexPairBot",
        executable=sys.executable,
        args=(str(script),),
        prompt="ignored",
        cwd=tmp_path,
        timeout_seconds=2,
    )

    result = await run_cli(request)

    assert result.ok is False
    assert result.exit_code == 7
    assert result.error_type == "non_zero_exit"
    assert "bad things happened" in result.error_message
    assert result.stderr == "bad things happened"


async def test_run_cli_handles_missing_executable(tmp_path: Path) -> None:
    request = CliRequest(
        bot_name="ClaudeCodeBot",
        executable="/definitely/missing/binary",
        args=(),
        prompt="ignored",
        cwd=tmp_path,
        timeout_seconds=1,
    )

    result = await run_cli(request)

    assert result.ok is False
    assert result.error_type == "missing_executable"
    assert "Executable not found" in result.error_message


async def test_run_cli_times_out(tmp_path: Path) -> None:
    script = tmp_path / "sleep_cli.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdin.read()\n"
        "time.sleep(0.3)\n"
        "print('late output')\n",
        encoding="utf-8",
    )
    request = CliRequest(
        bot_name="CodexPairBot",
        executable=sys.executable,
        args=(str(script),),
        prompt="hello",
        cwd=tmp_path,
        timeout_seconds=0.05,
    )

    result = await run_cli(request)

    assert result.ok is False
    assert result.error_type == "timeout"
    assert "Timed out" in result.error_message


async def test_run_cli_uses_codex_exec_and_prompt_argument(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    request = CliRequest(
        bot_name="CodexPairBot",
        executable=str(codex),
        args=(),
        prompt="hello from telegram",
        cwd=tmp_path,
        timeout_seconds=2,
    )

    result = await run_cli(request)

    assert result.ok is True
    assert '"exec"' in result.output
    assert '"--skip-git-repo-check"' in result.output
    assert '"hello from telegram"' in result.output
    assert '"stdin": ""' in result.output


async def test_run_cli_strips_legacy_lone_codex_dash_p(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    request = CliRequest(
        bot_name="CodexPairBot",
        executable=str(codex),
        args=('-p',),
        prompt="hi",
        cwd=tmp_path,
        timeout_seconds=2,
    )

    result = await run_cli(request)

    assert result.ok is True
    assert result.output == '["exec", "--skip-git-repo-check", "hi"]'
