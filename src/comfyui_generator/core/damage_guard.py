"""Data-driven cross-shot irreversibility checks for damaged garments."""

from __future__ import annotations

import re
from typing import Any

from comfyui_generator.core.mechanical import split_tags
from comfyui_generator.core.tagdb import load_layers


def _contains(text: str, token: str) -> bool:
    return bool(re.search(
        r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text))


def detect_damage_restored(
    shots: list[dict[str, Any]],
    layers: dict[str, list[str]] | None = None,
) -> dict[int, list[dict[str, str]]]:
    vocab = layers or load_layers()
    damage = [t for t in vocab.get("damage_markers", []) if t]
    replacement = [t for t in vocab.get("replacement_markers", []) if t]
    removed = [t for t in vocab.get("removed_markers", []) if t]
    garment_tokens: set[str] = set()
    for category in vocab.get("garment_categories", []):
        garment_tokens.update(vocab.get(category, []))
    damaged: set[str] = set()
    findings: dict[int, list[dict[str, str]]] = {}
    for index, shot in enumerate(shots):
        restored: set[str] = set()
        for segment in split_tags(shot.get("prompt") if isinstance(shot, dict) else ""):
            text = segment.strip().lower()
            present = {token for token in garment_tokens
                       if _contains(text, token)}
            if any(_contains(text, token) for token in replacement):
                damaged = {d for d in damaged
                           if not any(token in d or d in token
                                      for token in present)}
                continue
            if any(_contains(text, token) for token in removed):
                damaged = {d for d in damaged
                           if not any(token in d or d in token
                                      for token in present)}
                continue
            is_damaged = any(_contains(text, token) for token in damage)
            if is_damaged:
                damaged |= present
                continue
            restored |= present & damaged
        if restored:
            findings[index] = [{
                "kind": "damage_restored",
                "severity": "P2",
                "message": "之前已撕开/剪开的衣物在后续镜头恢复为完整状态",
                "evidence": ", ".join(sorted(restored)[:6]),
            }]
    return findings
