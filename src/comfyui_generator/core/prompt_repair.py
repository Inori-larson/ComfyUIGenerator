"""Pre-render automatic prompt repair for storyboard shots.

After generation, shots with blocking (P1) structural findings are repaired by
the configured LLM with a strict minimal-change instruction, then re-validated.
A shot is marked ready only once it passes. This module works on prompt text
alone (no rendering, no tagger); it never writes semantics itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.mechanical import dedupe_tags, split_tags
from comfyui_generator.core.rewrite import rewrite_shot_prompt
from comfyui_generator.core.tag_validation import (
    ValidationOptions,
    annotate_shots,
    validate_prompt,
)
from comfyui_generator.core.tagdb import TagDatabase

MINIMAL_FIX_SYSTEM = (
    "You repair one booru storyboard prompt that failed a structural check. "
    "Output only JSON {\"prompt\": \"...\"} of English comma-separated Danbooru tags. "
    "Make the MINIMAL change to fix exactly the listed findings (cast/count or clothing "
    "layering). Keep scene, action, characters, pose, camera, fluids and every correct tag "
    "unchanged; do not invent new content. "
    "If inner underwear (bra/panties) is written while outer clothing is still closed and not "
    "open/removed, either open/remove that outer garment according to the shot's beat OR, when "
    "the shot is still fully clothed, remove the inner-underwear tag. "
    "Resolve contradictory count tags (e.g. solo vs 1boy) to match who is actually present.")


@dataclass
class RepairReport:
    repaired: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    attempts: int = 0


def constrain_minimal(rewritten: str, original: str,
                      findings: list[dict[str, Any]]) -> str:
    """Drop tags the LLM added that the findings do not justify.

    No hardcoded label whitelist: a new tag is kept only when the finding
    explicitly mentions it as expected/evidence.
    """
    import re

    orig = {t.strip().lower() for t in split_tags(original)}
    justification = " ".join(
        " ".join(str(f.get(key) or "")
                 for key in ("expected", "actual", "evidence", "message"))
        for f in findings).lower()
    kept: list[str] = []
    for tag in dedupe_tags(split_tags(rewritten)):
        key = tag.strip().lower()
        if key in orig:
            kept.append(tag)
            continue
        if key and re.search(
                r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])",
                justification):
            kept.append(tag)
    return ", ".join(kept) or original


def repair_instruction(findings: list[dict[str, Any]]) -> str:
    lines = ["分镜结构校验发现以下 P1 问题，请只修改相关 booru 标签修正，保持剧情/动作/场景/镜头不变："]
    for f in findings:
        lines.append("- %s（证据：%s）" % (f.get("message", ""), f.get("evidence", "")))
    lines.append("只输出修正后的英文 Danbooru 标签。")
    return "\n".join(lines)


def auto_repair_shots(
    shots: list[dict[str, Any]],
    db: TagDatabase,
    client: Any,
    model: str,
    *,
    options: ValidationOptions | None = None,
    max_rounds: int = 2,
    character_tags: str = "",
    strip_appearance: bool = False,
    max_calls: int = 3,
    max_seconds: float = 120.0,
    log: Callable[[str], None] | None = None,
) -> RepairReport:
    options = options or ValidationOptions(
        report_unknown=False, report_aliases=False)
    report = RepairReport()
    started = time.monotonic()
    budget_exhausted = False
    for shot in shots:
        prompt = str(shot.get("prompt") or "")
        current_findings = validate_prompt(prompt, db, options).findings
        blocking = [f for f in current_findings if f.get("severity") == "P1"]
        if not blocking:
            shot["findings"] = current_findings
            shot["ready"] = True
            continue
        if budget_exhausted or report.attempts >= max(1, max_calls) \
                or (time.monotonic() - started) >= max_seconds:
            if not budget_exhausted and log:
                log("自动修复达到调用/时间预算，其余 P1 镜头保留标记待处理。")
            budget_exhausted = True
            shot["findings"] = current_findings
            shot["ready"] = False
            report.unresolved.append(str(shot.get("id") or ""))
            continue
        fixed = False
        for _round in range(max(1, max_rounds)):
            if report.attempts >= max(1, max_calls) \
                    or (time.monotonic() - started) >= max_seconds:
                if not budget_exhausted and log:
                    log("自动修复达到调用/时间预算，其余 P1 镜头保留标记待处理。")
                budget_exhausted = True
                break
            report.attempts += 1
            try:
                rewritten = rewrite_shot_prompt(
                    client, model, prompt,
                    repair_instruction(blocking),
                    character_tags=character_tags,
                    strip_appearance=strip_appearance,
                    system_override=MINIMAL_FIX_SYSTEM,
                    temperature=0.4)
            except Exception as exc:
                if log:
                    log("镜头 %s 自动修复失败：%s" % (shot.get("id"), str(exc)[:160]))
                break
            rewritten = constrain_minimal(rewritten, prompt, blocking)
            result = validate_prompt(rewritten, db, options)
            if not result.blocking:
                prompt = rewritten
                shot["prompt"] = rewritten
                current_findings = result.findings
                fixed = True
                break
            blocking = result.blocking
        shot["findings"] = current_findings
        shot["ready"] = fixed
        (report.repaired if fixed else report.unresolved).append(
            str(shot.get("id") or ""))
    return report
