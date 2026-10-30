"""Configurable LoRA directory scanning for the character / style pages."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

LORA_EXTENSIONS = (".safetensors", ".pt", ".ckpt", ".bin")

_LORA_NOISE = {
    "lora", "lycoris", "lokr", "safetensors", "illustrious", "illustriousxl",
    "sdxl", "sd15", "pony", "noob", "nochekaiser", "il", "ill", "xl", "xxl",
    "final", "fp16", "bf16", "epoch", "char", "character", "model",
    "checkpoint", "concept", "style", "styles", "v1", "v2", "v3",
    "v10", "v20", "v30", "1a", "1b",
}
_VERSION_RE = re.compile(r"^v\d+(?:[._-]?\d+)*$", re.I)
_NUMBER_RE = re.compile(r"^\d{1,6}$")
_HASH_RE = re.compile(r"^[a-f0-9]{8,}$", re.I)
_ILLUS_RE = re.compile(r"^illus\d*$", re.I)


def lora_display_label(name: str | Path) -> str:
    """Return the readable part of a LoRA filename for display/translation."""
    base = Path(str(name).replace("\\", "/")).name
    stem = Path(base).stem.strip()
    if not stem:
        return base
    if re.search(r"[\u4e00-\u9fff]", stem):
        return re.sub(r"[_\-\.]+", " ", stem).strip()
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", stem) if token]
    kept = [
        token for token in tokens
        if token.lower() not in _LORA_NOISE
        and not _VERSION_RE.match(token)
        and not _NUMBER_RE.match(token)
        and not _HASH_RE.match(token)
        and not _ILLUS_RE.match(token)
    ]
    label = " ".join(kept).strip()
    return label or re.sub(r"[_\-\.]+", " ", stem).strip() or base


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
