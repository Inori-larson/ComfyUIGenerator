"""Outline-level pacing findings from AI-declared structure only.

Reads beat_id and the per-shot script/outline/description the AI produced.
Emits findings about beat shot allocation and semantic progression; it never
edits prompts and never invents story content. Jaccard tag overlap stays in
stall_guard as evidence only, never as a pass condition.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*|[\u4e00-\u9fff]{2,}")


def _semantic_tokens(shot: dict[str, Any]) -> frozenset[str]:
    text = " ".join(
        str(shot.get(key) or "")
        for key in ("script", "outline", "description")
    )
    return frozenset(token.lower() for token in _TOKEN_RE.findall(text))


def detect_outline_pacing(
    shots: list[dict[str, Any]],
    *,
    min_shots: int = 6,
    max_beat_share: float = 0.4,
    min_static_run: int = 3,
) -> dict[int, list[dict[str, str]]]:
    findings: dict[int, list[dict[str, str]]] = {}
    total = len(shots)
    if total < min_shots:
        return findings

    counts = Counter(
        str(shot.get("beat_id") or "").strip() for shot in shots)
    for beat_id, count in counts.items():
        if not beat_id or count / total <= max_beat_share:
            continue
        index = next(
            i for i, shot in enumerate(shots)
            if str(shot.get("beat_id") or "").strip() == beat_id)
        findings.setdefault(index, []).append({
            "kind": "outline_beat_concentration",
            "severity": "P2",
            "scope": "outline",
            "shot_index": str(index),
            "shot_id": str(shots[index].get("id") or ""),
            "message": (
                "单个 beat 占用 %d/%d 镜；若剧本就是这样设计则完全允许、无需修改，"
                "否则应由 AI 在大纲阶段重新分配镜头。" % (count, total)),
            "evidence": "beat=%s, shots=%d/%d" % (beat_id, count, total),
        })

    previous_tokens: frozenset[str] | None = None
    previous_beat = ""
    run: list[int] = []
    for index, shot in enumerate(shots):
        beat = str(shot.get("beat_id") or "").strip()
        tokens = _semantic_tokens(shot)
        if not tokens:
            run = [index]
            previous_tokens = tokens
            previous_beat = beat
            continue
        new_tokens = len(tokens - previous_tokens) if previous_tokens else len(tokens)
        same_beat = bool(beat) and beat == previous_beat
        if previous_tokens is not None and same_beat and new_tokens == 0:
            run.append(index)
        else:
            run = [index]
        if len(run) >= min_static_run:
            item = run[-1]
            findings.setdefault(item, []).append({
                "kind": "outline_semantic_stall",
                "severity": "P1",
                "scope": "outline",
                "shot_index": str(item),
                "shot_id": str(shots[item].get("id") or ""),
                "message": (
                    "同一 beat 内连续镜头剧本描述没有任何新语义，剧情客观不推进；"
                    "若大纲确实设计为长停顿可确认豁免，否则需 AI 重出大纲。"),
                "evidence": "beat=%s, new_tokens=0, run=%d" % (beat, len(run)),
            })
        previous_tokens = tokens
        previous_beat = beat
    return findings
