from __future__ import annotations

import asyncio
import logging

from .config import RuntimeConfig, load_config
from .telegram_app import build_runtime, create_aiogram_bots, poll_bots


def configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def run(runtime_config: RuntimeConfig | None = None) -> None:
    config = runtime_config or load_config()
    config.prepare_workspace()
    configure_logging(config.log_level)
    bots = create_aiogram_bots(config)
    runtime = build_runtime(config, bots)
    await poll_bots(runtime, bots)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - signal-driven path
        logging.getLogger(__name__).info("Shutdown requested by user")


if __name__ == "__main__":  # pragma: no cover
    main()
