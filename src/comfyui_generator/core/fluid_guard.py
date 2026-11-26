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
    *,
    min_static_run: int = 6,
) -> dict[int, list[dict[str, str]]]:
    vocab = layers or load_layers()
    fluid_tokens = [t for t in vocab.get("fluid_tags", []) if t]
    cleanup_tokens = [t for t in vocab.get("fluid_cleanup_markers", []) if t]
    findings: dict[int, list[dict[str, str]]] = {}
    active: set[str] = set()
    static_key: set[str] | None = None
    static_run = 0
    for index, shot in enumerate(shots):
        text = str(shot.get("prompt") or "").lower()
        if any(_contains(text, token) for token in cleanup_tokens):
            active = set()
            static_key = None
            static_run = 0
            continue
        present = {token for token in fluid_tokens if _contains(text, token)}
        if present:
            active |= present
            if present == static_key:
                static_run += 1
            else:
                static_key = present
                static_run = 1
            if static_run == max(2, min_static_run):
                findings.setdefault(index, []).append({
                    "kind": "fluid_state_static",
                    "severity": "P2",
                    "message": (
                        "连续多镜体液状态完全不变（仅提示）；若剧本就是这样设计则"
                        "完全允许、无需修改，否则应由 AI 在时间线里体现变化或清理。"),
                    "evidence": ", ".join(sorted(present)[:6])
                                 + " (run=%d)" % static_run,
                })
            continue
        static_key = None
        static_run = 0
        if active:
            findings[index] = [{
                "kind": "fluid_discontinuity",
                "severity": "P2",
                "message": (
                    "上一镜出现的体液在后续镜头消失且未写出清理过程（仅提示）；"
                    "若剧本就是这样设计则完全允许、无需修改。"),
                "evidence": ", ".join(sorted(active)[:6]),
            }]
    return findings
