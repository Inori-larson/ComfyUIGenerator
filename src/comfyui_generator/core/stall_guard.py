"""Structural near-duplicate detection across consecutive shots."""

from __future__ import annotations

from typing import Any

from comfyui_generator.core.mechanical import normalize_weight_syntax, split_tags


def _tag_key(tag: str) -> str:
    return " ".join(normalize_weight_syntax(tag).strip().lower().split())


def _tags(shot: dict[str, Any]) -> frozenset[str]:
    return frozenset(key for key in (_tag_key(t) for t in split_tags(
        shot.get("prompt") if isinstance(shot, dict) else "")) if key)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_stalls(shots: list[dict[str, Any]], *, min_run: int = 3,
                  threshold: float = 0.9) -> dict[int, list[dict[str, str]]]:
    findings: dict[int, list[dict[str, str]]] = {}
    previous: frozenset[str] | None = None
    run: list[int] = []
    for index, shot in enumerate(shots):
        current = _tags(shot)
        score = _jaccard(previous, current) if previous is not None else 0.0
        if previous is not None and score >= threshold:
            run.append(index)
        else:
            run = [index]
        if len(run) >= min_run:
            for item in run[1:]:
                findings.setdefault(item, []).append({
                    "kind": "shot_stall",
                    "severity": "P2",
                    "message": "连续镜头标签几乎未变化，画面可能停滞不推进",
                    "evidence": "与上一镜标签重合 %.2f" % score,
                })
        previous = current
    return findings
