from __future__ import annotations

import json
from pathlib import Path

from .config import RuntimeConfig


class ModelRegistry:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._runtime_config = runtime_config
        self._path = runtime_config.workspace_dir / "bot_models.json"
        self._overrides = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def get_model(self, bot_name: str) -> str | None:
        override = self._overrides.get(bot_name)
        if override:
            return override
        return self._runtime_config.get_bot(bot_name).default_model

    def snapshot(self) -> dict[str, str | None]:
        return {
            bot.name: self.get_model(bot.name)
            for bot in self._runtime_config.bot_configs
        }

    def set_model(self, bot_name: str, model: str) -> None:
        self._overrides[bot_name] = model.strip()
        self._save()

    def reset_model(self, bot_name: str) -> None:
        self._overrides.pop(bot_name, None)
        self._save()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        models = data.get("models", {})
        if not isinstance(models, dict):
            return {}
        return {
            str(key): str(value).strip()
            for key, value in models.items()
            if str(value).strip()
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f"{self._path.name}.tmp")
        tmp_path.write_text(
            json.dumps({"models": self._overrides}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)
