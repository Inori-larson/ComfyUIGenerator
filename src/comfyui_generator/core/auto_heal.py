"""Auto-heal orchestration for a storyboard that failed structural review.

The application only collects structured findings, asks the AI to regenerate
the complete storyboard, re-validates it and archives evidence. It never writes
story semantics itself.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

HEAL_INSTRUCTION = (
    "【自动修复要求】上一轮分镜经结构校验未通过。请依据上面的用户剧情，"
    "重新生成完整分镜 JSON：镜数、角色、风格、已正确的标签和 beat 结构保持不变，"
    "只修正下面列出的证据所指出的问题；全部剧情语义由你重新生成。"
)

_BLOCKING_PREFIXES = ("contract_", "outline_")
_BLOCKING_KINDS = {"cast_grouping_missing"}


def collect_blocking(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for shot in shots:
        for finding in (shot.get("findings") or []):
            if not isinstance(finding, dict):
                continue
            kind = str(finding.get("kind") or "")
            blocking = (finding.get("severity") == "P1"
                        or kind.startswith(_BLOCKING_PREFIXES)
                        or kind in _BLOCKING_KINDS)
            if not blocking:
                continue
            entry = dict(finding)
            entry.setdefault("shot_id", str(shot.get("id") or ""))
            key = (kind, str(entry.get("shot_id") or ""),
                   str(entry.get("message") or ""))
            if key in seen:
                continue
            seen.add(key)
            collected.append(entry)
    return collected


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(f.get("kind") or "") for f in findings
                        if f.get("kind")))


def build_heal_requirement(findings: list[dict[str, Any]],
                           shot_count: int) -> str:
    lines = [HEAL_INSTRUCTION,
             "目标镜数：%d，必须完整输出全部镜头。" % shot_count,
             "校验发现的问题："]
    for finding in findings[:50]:
        lines.append("- [%s] 镜 %s：%s（证据：%s）" % (
            finding.get("severity", ""), finding.get("shot_id", ""),
            finding.get("message", ""), finding.get("evidence", "")))
    return "\n".join(lines)


def premise_hash(premise: str) -> str:
    return hashlib.sha1(str(premise or "").encode("utf-8")).hexdigest()[:12]


def new_report(premise: str, shot_count: int, model: str) -> dict[str, Any]:
    return {
        "premise_id": premise_hash(premise),
        "shot_count": int(shot_count),
        "model": str(model or ""),
        "rounds": [],
        "final_blocking": [],
        "resolved": False,
    }


def record_round(report: dict[str, Any], *, round_index: int,
                 before: list[dict[str, Any]],
                 after: list[dict[str, Any]],
                 accepted: bool) -> None:
    report["rounds"].append({
        "round": round_index,
        "blocking_before": len(before),
        "blocking_after": len(after),
        "kinds_before": summarize_findings(before),
        "kinds_after": summarize_findings(after),
        "accepted": bool(accepted),
    })
    report["final_blocking"] = after
    report["resolved"] = not after


def archive_report(output_root: str | Path,
                   report: dict[str, Any]) -> str:
    review = Path(output_root) / "review"
    review.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    identity = str(report.get("premise_id") or "unknown")[:12]
    path = review / ("%s_auto_heal_%s.json" % (stamp, identity))
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return str(path)
