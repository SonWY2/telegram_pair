from __future__ import annotations

import json
from collections.abc import Iterable

from .base import BackendError, BackendSupport, CliBackend
from ..models import CliRequest, CliResult


class CodexBackend(CliBackend):
    def build_argv(self, request: CliRequest) -> tuple[str, ...]:
        args = self._normalize_args(request.args)
        if request.resume:
            if not request.session_id:
                raise BackendError("resume requests require session_id")
            args = self._insert_resume_session_id(args, request.session_id)
        elif not args or args[0] not in {"exec", "review", "login", "logout", "mcp", "help"}:
            args = ["exec", "--skip-git-repo-check", *args]
        if request.model_override:
            args.extend(["--model", request.model_override])
        return (request.executable, *args, request.prompt)

    def build_stdin_payload(self, request: CliRequest) -> bytes | None:
        return None

    def parse_result(
        self,
        request: CliRequest,
        *,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        duration_seconds: float,
    ) -> CliResult:
        parsed_output = stdout
        session_id = None
        if request.supports_structured_output:
            parsed_output, session_id = _parse_codex_output(stdout)
        raw_payload = stdout
        if exit_code != 0:
            session_broken = request.resume and BackendSupport.looks_like_broken_session(stderr, stdout)
            error_type = "session_broken" if session_broken else "non_zero_exit"
            error_message = (
                "Stored session could not be resumed"
                if session_broken
                else BackendSupport.summarize_non_zero_exit(exit_code, stderr)
            )
            return BackendSupport.error_result(
                request,
                duration_seconds=duration_seconds,
                error_type=error_type,
                error_message=error_message,
                exit_code=exit_code,
                stderr=stderr,
                output=parsed_output or stdout,
                session_id=session_id,
                session_reused=request.resume,
                session_broken=session_broken,
                raw_payload=raw_payload,
            )
        final_output = parsed_output if request.supports_structured_output else (parsed_output or stdout)
        if not final_output:
            return BackendSupport.error_result(
                request,
                duration_seconds=duration_seconds,
                error_type="empty_output",
                error_message="CLI produced no output",
                exit_code=exit_code,
                stderr=stderr,
                session_id=session_id,
                session_reused=request.resume,
                raw_payload=raw_payload,
            )
        return BackendSupport.success_result(
            request,
            output=final_output,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
            stderr=stderr,
            session_id=session_id,
            session_reused=request.resume,
            raw_payload=raw_payload,
        )

    def _normalize_args(self, args: tuple[str, ...]) -> list[str]:
        normalized = list(args)
        if normalized == ["-p"] or normalized == ["--print"]:
            return []
        if normalized and normalized[-1] in {"-p", "--profile"}:
            return normalized[:-1]
        return normalized

    def _insert_resume_session_id(self, args: list[str], session_id: str) -> list[str]:
        if "resume" not in args:
            raise BackendError("resume args must include 'resume'")
        index = args.index("resume")
        return [*args[: index + 1], session_id, *args[index + 1 :]]


def _parse_codex_output(stdout: str) -> tuple[str, str | None]:
    payload = stdout.strip()
    if not payload:
        return "", None
    parsed = _parse_json_payload(payload)
    if parsed is None:
        return payload, None
    session_id = _find_session_id(parsed)
    texts = [text for text in _collect_output_text(parsed) if text.strip()]
    if texts:
        return "\n\n".join(texts), session_id
    return "", session_id


def _parse_json_payload(payload: str) -> object | None:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass
    rows = []
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            return None
    return rows or None


def _find_session_id(node: object) -> str | None:
    if isinstance(node, dict):
        for key in ("session_id", "sessionId", "thread_id", "threadId"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in node.values():
            session_id = _find_session_id(value)
            if session_id:
                return session_id
    elif isinstance(node, list):
        for item in node:
            session_id = _find_session_id(item)
            if session_id:
                return session_id
    return None


def _collect_output_text(node: object) -> Iterable[str]:
    if isinstance(node, str):
        return ()
    if isinstance(node, dict):
        collected: list[str] = []
        output_text = node.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            collected.append(output_text.strip())
        text = node.get("text")
        if isinstance(text, str) and _looks_like_text_node(node):
            collected.append(text.strip())
        content = node.get("content")
        if isinstance(content, str) and _looks_like_message_content(node):
            collected.append(content.strip())
        elif isinstance(content, list):
            for item in content:
                collected.extend(_collect_output_text(item))
        message = node.get("message")
        if message is not None:
            collected.extend(_collect_output_text(message))
        response = node.get("response")
        if response is not None:
            collected.extend(_collect_output_text(response))
        for key, value in node.items():
            if key in {"output_text", "text", "content", "message", "response", "session_id", "sessionId"}:
                continue
            collected.extend(_collect_output_text(value))
        return tuple(_dedupe_preserve_order(collected))
    if isinstance(node, list):
        collected: list[str] = []
        for item in node:
            collected.extend(_collect_output_text(item))
        return tuple(_dedupe_preserve_order(collected))
    return ()


def _looks_like_text_node(node: dict[str, object]) -> bool:
    kind = str(node.get("type", "")).lower()
    role = str(node.get("role", "")).lower()
    return kind in {"output_text", "text", "message", "assistant_message", "agent_message"} or role == "assistant"


def _looks_like_message_content(node: dict[str, object]) -> bool:
    role = str(node.get("role", "")).lower()
    kind = str(node.get("type", "")).lower()
    return role == "assistant" or kind in {"message", "assistant_message", "agent_message", "response"}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
