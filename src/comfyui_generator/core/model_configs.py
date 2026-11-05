"""Model-specific generation presets shipped with the application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from comfyui_generator.core.config import PRESET_DIR

MODEL_CONFIG_PATH = PRESET_DIR / "model_configs.json"


def load_model_configs(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path else MODEL_CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    configs: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        if not model:
            continue
        configs.append(dict(item))
    return configs


def normalize_model_name(value: str) -> str:
    return str(value or "").strip().replace("/", "\\").lower()


def find_model_config(configs: list[dict[str, Any]],
                      checkpoint: str) -> dict[str, Any] | None:
    target = normalize_model_name(checkpoint)
    if not target:
        return None
    for config in configs:
        model = normalize_model_name(str(config.get("model") or ""))
        if target == model or target.endswith("\\" + model):
            return config
    for config in configs:
        model = normalize_model_name(str(config.get("model") or ""))
        if model and (model in target or target in model):
            return config
    return None
