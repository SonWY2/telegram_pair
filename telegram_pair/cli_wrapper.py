from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .models import CliRequest, CliResult


async def run_cli(request: CliRequest) -> CliResult:
    """Run a configured CLI request and normalize its result."""
    start = time.perf_counter()
    argv = _build_argv(request)
    stdin_payload = _build_stdin_payload(request)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_payload is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_resolve_cwd(request.cwd)),
        )
    except FileNotFoundError:
        return _error_result(
            request,
            start,
            error_type="missing_executable",
            error_message=f"Executable not found: {request.executable}",
        )
    except OSError as exc:
        return _error_result(
            request,
            start,
            error_type="spawn_error",
            error_message=str(exc),
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_payload),
            timeout=request.timeout_seconds,
        )
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return _error_result(
            request,
            start,
            error_type="timeout",
            error_message=f"Timed out after {request.timeout_seconds} seconds",
            exit_code=process.returncode,
            stderr=_normalize_output(stderr),
            output=_normalize_output(stdout),
        )

    output = _normalize_output(stdout)
    stderr_text = _normalize_output(stderr)
    duration = time.perf_counter() - start

    if process.returncode != 0:
        return CliResult(
            bot_name=request.bot_name,
            ok=False,
            output=output,
            duration_seconds=duration,
            exit_code=process.returncode,
            error_type="non_zero_exit",
            error_message=_summarize_non_zero_exit(process.returncode, stderr_text),
            stderr=stderr_text,
        )

    if not output:
        return CliResult(
            bot_name=request.bot_name,
            ok=False,
            output="",
            duration_seconds=duration,
            exit_code=process.returncode,
            error_type="empty_output",
            error_message="CLI produced no output",
            stderr=stderr_text,
        )

    return CliResult(
        bot_name=request.bot_name,
        ok=True,
        output=output,
        duration_seconds=duration,
        exit_code=process.returncode,
        stderr=stderr_text,
    )


def _resolve_cwd(cwd: Path) -> Path:
    resolved = cwd.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _build_argv(request: CliRequest) -> tuple[str, ...]:
    executable = request.executable
    args = list(request.args)
    if _is_codex_executable(executable):
        args = _normalize_codex_args(args)
        if not args or args[0] not in {"exec", "review", "login", "logout", "mcp", "help"}:
            args = ["exec", "--skip-git-repo-check", *args]
        if request.model_override:
            args = [*args, "--model", request.model_override]
        return (executable, *args, request.prompt)
    if request.model_override:
        args = [*args, "--model", request.model_override]
    return (executable, *args)


def _build_stdin_payload(request: CliRequest) -> bytes | None:
    if _is_codex_executable(request.executable):
        return None
    return request.prompt.encode("utf-8")


def _is_codex_executable(executable: str) -> bool:
    name = Path(executable).name.lower()
    return name == "codex" or name.startswith("codex.")


def _normalize_codex_args(args: list[str]) -> list[str]:
    normalized = list(args)
    if normalized == ["-p"] or normalized == ["--print"]:
        return []
    if normalized and normalized[-1] in {"-p", "--profile"}:
        return normalized[:-1]
    return normalized


def _normalize_output(raw: bytes | None) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalized


def _summarize_non_zero_exit(exit_code: int | None, stderr_text: str) -> str:
    prefix = f"CLI exited with status {exit_code}"
    if stderr_text:
        return f"{prefix}: {stderr_text.splitlines()[0]}"
    return prefix


def _error_result(
    request: CliRequest,
    start: float,
    *,
    error_type: str,
    error_message: str,
    exit_code: int | None = None,
    stderr: str = "",
    output: str = "",
) -> CliResult:
    return CliResult(
        bot_name=request.bot_name,
        ok=False,
        output=output,
        duration_seconds=time.perf_counter() - start,
        exit_code=exit_code,
        error_type=error_type,
        error_message=error_message,
        stderr=stderr,
    )
