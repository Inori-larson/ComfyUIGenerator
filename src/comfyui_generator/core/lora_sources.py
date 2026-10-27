"""Configurable LoRA directory scanning for the character / style pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

LORA_EXTENSIONS = (".safetensors", ".pt", ".ckpt", ".bin")


def scan_lora_dir(folder: str | Path | None) -> list[Path]:
    if not folder:
        return []
    root = Path(folder)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in LORA_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


def match_comfy_name(path: str | Path, comfy_names: list[str]) -> str | None:
    """Match a local file to a ComfyUI LoRA name by basename (unique first)."""
    basename = Path(path).name.lower()
    matches = [name for name in comfy_names if Path(str(name).replace("/", "\\")).name.lower() == basename]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches[0]
    return None


def lora_entries(folder: str | Path | None, comfy_names: list[str]) -> list[dict[str, Any]]:
    """Return entries with the workflow name and a human readable display path."""
    root = Path(folder) if folder else None
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in scan_lora_dir(folder):
        name = match_comfy_name(path, comfy_names)
        display = str(path)
        if root is not None:
            try:
                display = str(path.relative_to(root))
            except ValueError:
                display = path.name
        if name is None:
            name = path.name
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "name": name,
            "path": str(path),
            "display": display,
            "resolved": name in comfy_names,
        })
    return entries
