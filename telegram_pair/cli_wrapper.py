from __future__ import annotations

import asyncio
import time

from .cli_backends import select_backend
from .cli_backends.base import BackendError, BackendSupport
from .models import CliRequest, CliResult


async def run_cli(request: CliRequest) -> CliResult:
    """Run a configured CLI request and normalize its result."""
    start = time.perf_counter()
    backend = select_backend(request)
    try:
        argv = backend.build_argv(request)
    except BackendError as exc:
        return BackendSupport.error_result(
            request,
            duration_seconds=time.perf_counter() - start,
            error_type="invalid_request",
            error_message=str(exc),
        )
    stdin_payload = backend.build_stdin_payload(request)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_payload is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(BackendSupport.resolve_cwd(request.cwd)),
        )
    except FileNotFoundError:
        return BackendSupport.error_result(
            request,
            duration_seconds=time.perf_counter() - start,
            error_type="missing_executable",
            error_message=f"Executable not found: {request.executable}",
        )
    except OSError as exc:
        return BackendSupport.error_result(
            request,
            duration_seconds=time.perf_counter() - start,
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
        return BackendSupport.error_result(
            request,
            duration_seconds=time.perf_counter() - start,
            error_type="timeout",
            error_message=f"Timed out after {request.timeout_seconds} seconds",
            exit_code=process.returncode,
            stderr=BackendSupport.normalize_output(stderr),
            output=BackendSupport.normalize_output(stdout),
        )

    return backend.parse_result(
        request,
        stdout=BackendSupport.normalize_output(stdout),
        stderr=BackendSupport.normalize_output(stderr),
        exit_code=process.returncode,
        duration_seconds=time.perf_counter() - start,
    )
