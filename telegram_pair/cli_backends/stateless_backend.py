from __future__ import annotations

from .base import BackendSupport, CliBackend
from ..models import CliRequest, CliResult


class StatelessBackend(CliBackend):
    def build_argv(self, request: CliRequest) -> tuple[str, ...]:
        args = list(request.args)
        if request.model_override:
            args.extend(["--model", request.model_override])
        return (request.executable, *args)

    def build_stdin_payload(self, request: CliRequest) -> bytes | None:
        return request.prompt.encode("utf-8")

    def parse_result(
        self,
        request: CliRequest,
        *,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        duration_seconds: float,
    ) -> CliResult:
        if exit_code != 0:
            return BackendSupport.error_result(
                request,
                duration_seconds=duration_seconds,
                error_type="non_zero_exit",
                error_message=BackendSupport.summarize_non_zero_exit(exit_code, stderr),
                exit_code=exit_code,
                stderr=stderr,
                output=stdout,
            )
        if not stdout:
            return BackendSupport.error_result(
                request,
                duration_seconds=duration_seconds,
                error_type="empty_output",
                error_message="CLI produced no output",
                exit_code=exit_code,
                stderr=stderr,
            )
        return BackendSupport.success_result(
            request,
            output=stdout,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
            stderr=stderr,
        )
