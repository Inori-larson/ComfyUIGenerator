"""Persistent English -> Chinese tag cache for display."""

from __future__ import annotations

import json
import threading
from pathlib import Path

_LOCK = threading.Lock()


def load_tag_cache(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items() if key and value}


def update_tag_cache(path: str | Path | None, pairs: dict[str, str]) -> dict[str, str]:
    if not path or not pairs:
        return {}
    target = Path(path)
    with _LOCK:
        current = load_tag_cache(target)
        current.update(pairs)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return current
