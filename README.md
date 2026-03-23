# Telegram Pair

Local-first Telegram orchestration layer that wraps two local coding CLIs as Telegram bots in a single group chat.

## Current scaffold

This lane establishes the project skeleton plus typed runtime/config primitives so routing, orchestration, and Telegram runtime work can land on stable interfaces.

## Runtime baseline

- Python 3.10+
- aiogram 3.x
- Local `claude` and `codex` CLIs installed and authenticated

## Architecture summary

- One Python process owns both Telegram bot tokens.
- One shared orchestrator decides whether a message is ignored, routed to one bot, or broadcast to both bots.
- One shared `context.md` file stores conversation history on the local filesystem.
- Broadcast mode runs priority 1 first, then injects bot 1 output into bot 2 input.

## Quick start

1. Create and activate a virtualenv.
2. Install the package in editable mode:
   - `pip install -e .[dev]`
3. Copy `.env.example` to `.env` in the `telegram_pair/` directory (it is auto-loaded at runtime), or export the variables in your shell.
4. Point `CLAUDE_CLI_EXECUTABLE` / `CODEX_CLI_EXECUTABLE` at the actual local wrappers if they differ.
5. Leave `CODEX_CLI_ARGS` empty unless you explicitly need extra `codex exec` flags; the wrapper adds `exec` automatically.
6. Ensure both Telegram bots have privacy mode disabled if you want plain `; message` broadcasts in a group.

## Trigger examples

- `@ClaudeCodeBot hello`
- `@CodexPairBot hello`
- `; compare two approaches`
- `@ClaudeCodeBot @CodexPairBot propose then refine`

## Operator notes

- Bot-authored messages must never retrigger orchestration.
- Broadcast replies are best-effort: if bot 1 fails, bot 2 should still run with an injected failure note.
- `context.md` is shared and append-only in normal operation.
- Disable Telegram privacy mode on both bots if semicolon broadcast should work on ordinary group messages.

## Failure behavior

- Missing executables, timeouts, and non-zero CLI exits should surface clear bot-scoped failures.
- Telegram send failures must be logged without crashing the whole process.
- Duplicate inbound group updates must be deduplicated by `(chat_id, message_id)`.

## Environment variables

See `.env.example` for the full set. The important ones are:

- `TELEGRAM_TOKEN_CLAUDE`
- `TELEGRAM_TOKEN_CODEX`
- `CLAUDE_CLI_EXECUTABLE`
- `CODEX_CLI_EXECUTABLE`
- `TELEGRAM_PAIR_WORKSPACE_DIR`
- `TELEGRAM_PAIR_CONTEXT_PATH` (optional)
- `TELEGRAM_PAIR_TIMEOUT_SECONDS`
- `TELEGRAM_PAIR_MAX_CONTEXT_TURNS`
- `TELEGRAM_PAIR_DEDUP_TTL_SECONDS`

## Planned layout

```text
telegram_pair/
├── pyproject.toml
├── README.md
├── .env.example
├── telegram_pair/
│   ├── __init__.py
│   ├── config.py
│   └── models.py
└── tests/
```
