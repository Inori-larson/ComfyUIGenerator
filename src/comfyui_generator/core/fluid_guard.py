"""Data-driven cross-shot fluid continuity checks."""

from __future__ import annotations

import re
from typing import Any

from comfyui_generator.core.tagdb import load_layers


def _contains(text: str, token: str) -> bool:
    return bool(re.search(
        r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text))


def detect_fluid_discontinuity(
    shots: list[dict[str, Any]],
    layers: dict[str, list[str]] | None = None,
) -> dict[int, list[dict[str, str]]]:
    vocab = layers or load_layers()
    fluid_tokens = [t for t in vocab.get("fluid_tags", []) if t]
    cleanup_tokens = [t for t in vocab.get("fluid_cleanup_markers", []) if t]
    findings: dict[int, list[dict[str, str]]] = {}
    active: set[str] = set()
    for index, shot in enumerate(shots):
        text = str(shot.get("prompt") or "").lower()
        if any(_contains(text, token) for token in cleanup_tokens):
            active = set()
            continue
        present = {token for token in fluid_tokens if _contains(text, token)}
        if present:
            active |= present
            continue
        if active:
            findings[index] = [{
                "kind": "fluid_discontinuity",
                "severity": "P2",
                "message": "上一镜出现的体液在后续镜头无故消失，未写出清理过程",
                "evidence": ", ".join(sorted(active)[:6]),
            }]
    return findings
