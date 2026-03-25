from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import CliRequest, CliResult


class CliBackend(Protocol):
    def build_argv(self, request: CliRequest) -> tuple[str, ...]: ...

    def build_stdin_payload(self, request: CliRequest) -> bytes | None: ...

    def parse_result(
        self,
        request: CliRequest,
        *,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        duration_seconds: float,
    ) -> CliResult: ...


@dataclass(slots=True, frozen=True)
class BackendParseContext:
    stdout: str
    stderr: str
    exit_code: int | None
    duration_seconds: float


BROKEN_SESSION_SIGNALS = (
    "session not found",
    "no session found",
    "could not find session",
    "invalid session",
    "expired session",
    "session expired",
    "conversation not found",
)


class BackendError(ValueError):
    """Raised when a backend cannot build a valid request."""


class BackendSupport:
    @staticmethod
    def is_codex_executable(executable: str) -> bool:
        name = Path(executable).name.lower()
        return name == "codex" or name.startswith("codex.")

    @staticmethod
    def resolve_cwd(cwd: Path) -> Path:
        resolved = cwd.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def normalize_output(raw: bytes | None) -> str:
        if not raw:
            return ""
        text = raw.decode("utf-8", errors="replace")
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def summarize_non_zero_exit(exit_code: int | None, stderr_text: str) -> str:
        prefix = f"CLI exited with status {exit_code}"
        if stderr_text:
            return f"{prefix}: {stderr_text.splitlines()[0]}"
        return prefix

    @staticmethod
    def error_result(
        request: CliRequest,
        *,
        duration_seconds: float,
        error_type: str,
        error_message: str,
        exit_code: int | None = None,
        stderr: str = "",
        output: str = "",
        session_id: str | None = None,
        session_reused: bool = False,
        session_broken: bool = False,
        raw_payload: str = "",
    ) -> CliResult:
        return CliResult(
            bot_name=request.bot_name,
            ok=False,
            output=output,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
            error_type=error_type,
            error_message=error_message,
            stderr=stderr,
            session_id=session_id,
            session_reused=session_reused,
            session_broken=session_broken,
            raw_payload=raw_payload,
        )

    @staticmethod
    def success_result(
        request: CliRequest,
        *,
        output: str,
        duration_seconds: float,
        exit_code: int | None,
        stderr: str,
        session_id: str | None = None,
        session_reused: bool = False,
        raw_payload: str = "",
    ) -> CliResult:
        return CliResult(
            bot_name=request.bot_name,
            ok=True,
            output=output,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
            stderr=stderr,
            session_id=session_id,
            session_reused=session_reused,
            raw_payload=raw_payload,
        )

    @staticmethod
    def looks_like_broken_session(*texts: str) -> bool:
        haystack = "\n".join(text.lower() for text in texts if text).strip()
        return any(signal in haystack for signal in BROKEN_SESSION_SIGNALS)


def select_backend(request: CliRequest) -> CliBackend:
    if BackendSupport.is_codex_executable(request.executable):
        from .codex_backend import CodexBackend

        return CodexBackend()
    from .stateless_backend import StatelessBackend

    return StatelessBackend()
