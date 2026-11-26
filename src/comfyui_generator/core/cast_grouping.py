"""Structural check: each visible character's appearance/clothing should be
grouped in parentheses right after its cast tag. Purely pattern-based; the
actual regrouping is done by the AI during auto-heal.
"""

from __future__ import annotations

import re
from typing import Any

_CAST_RE = re.compile(r"\b(1girl|1boy|2girls|2boys|girl|boy|female|male)\b", re.I)
_GROUP_RE = re.compile(r"\([^)]*\)")


def detect_cast_grouping(shots: list[dict[str, Any]]) -> dict[int, list[dict[str, str]]]:
    findings: dict[int, list[dict[str, str]]] = {}
    for index, shot in enumerate(shots):
        prompt = str(shot.get("prompt") or "")
        if not _CAST_RE.search(prompt):
            continue
        if _GROUP_RE.search(prompt):
            continue
        findings[index] = [{
            "kind": "cast_grouping_missing",
            "severity": "P2",
            "scope": "shot",
            "shot_index": index,
            "shot_id": str(shot.get("id") or ""),
            "message": (
                "该镜有角色但没有把外貌/服装用圆括号包成一组跟在角色名后；"
                "若确需修正，请 AI 重新生成该镜提示词。"),
            "evidence": prompt[:80],
        }]
    return findings
