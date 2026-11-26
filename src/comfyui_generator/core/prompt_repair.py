"""Pre-render automatic prompt repair for storyboard shots.

After generation, shots with blocking (P1) structural findings are repaired by
the configured LLM with a strict minimal-change instruction, then re-validated.
A shot is marked ready only once it passes. This module works on prompt text
alone (no rendering, no tagger); it never writes semantics itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.mechanical import dedupe_tags, split_tags
from comfyui_generator.core.repair_shared import (
    MINIMAL_FIX_SYSTEM, constrain_to_findings,
)
from comfyui_generator.core.rewrite import rewrite_shot_prompt
from comfyui_generator.core.tag_validation import (
    ValidationOptions,
    annotate_shots,
    validate_prompt,
)
from comfyui_generator.core.tagdb import TagDatabase

BATCH_FIX_SYSTEM = (
    "You repair booru storyboard prompts that failed structural checks. "
    "Output only JSON {\"prompts\":[{\"id\":\"...\",\"prompt\":\"...\"}]}. "
    "Make the MINIMAL change to fix exactly the listed findings. Keep scene, "
    "action, characters, camera, fluids and every correct tag unchanged; do not "
    "invent new content. For panties/legwear conflicts, when panties are exposed "
    "or pulled aside, put the outer legwear in a visibly torn/ripped/cut/"
    "pulled-aside/down state; intact legwear hiding the panties is also valid. "
    "Once a garment is torn/ripped/cut, never restore it later unless new "
    "clothes are explicitly shown. If non-fetish outerwear or accessories are "
    "still worn after skin is exposed, remove them and their tags; footwear the "
    "user explicitly keeps is exempt. Preserve the original tag count closely."
)

BATCH_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["id", "prompt"],
            },
        }
    },
    "required": ["prompts"],
}

REPAIRABLE_KINDS = {
    "layer_panty_under_legwear",
    "layer_claim_conflict",
    "removable_garment_during_sex",
    "fluid_discontinuity",
    "damage_restored",
}


@dataclass
class RepairReport:
    repaired: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    attempts: int = 0


def constrain_minimal(rewritten: str, original: str,
                      findings: list[dict[str, Any]]) -> str:
    return constrain_to_findings(rewritten, original, findings)


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
                shot.pop("prompt_zh", None)
                if shot.get("continuity_state") or shot.get("continuity_scene"):
                    shot["continuity_stale"] = True
                current_findings = result.findings
                fixed = True
                break
            blocking = result.blocking
        shot["findings"] = current_findings
        shot["ready"] = fixed
        (report.repaired if fixed else report.unresolved).append(
            str(shot.get("id") or ""))
    return report


def batch_repair_advisory(
    shots: list[dict[str, Any]],
    db: TagDatabase,
    client: Any,
    model: str,
    *,
    options: ValidationOptions | None = None,
    log: Callable[[str], None] | None = None,
) -> RepairReport:
    options = options or ValidationOptions(
        report_unknown=False, report_aliases=False)
    targets: list[dict[str, Any]] = []
    for shot in shots:
        findings = [f for f in (shot.get("findings") or [])
                    if f.get("kind") in REPAIRABLE_KINDS]
        if not findings:
            continue
        targets.append({
            "id": str(shot.get("id") or ""),
            "prompt": str(shot.get("prompt") or ""),
            "findings": findings,
        })
    report = RepairReport()
    if not targets:
        return report
    messages = [
        {"role": "system", "content": BATCH_FIX_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"shots": targets}, ensure_ascii=False)},
    ]
    try:
        raw = client.chat_json(
            model, messages,
            schema=BATCH_REPAIR_SCHEMA,
            temperature=0.3,
            num_predict=32768,
            num_ctx=32768,
            keep_alive="5m",
        )
        items = raw.get("prompts") if isinstance(raw, dict) else None
    except Exception as exc:
        if log:
            log("批量修复失败：%s" % str(exc)[:160])
        report.unresolved = [target["id"] for target in targets]
        return report
    by_id: dict[str, str] = {}
    for item in items or []:
        if isinstance(item, dict):
            shot_id = str(item.get("id") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if shot_id and prompt:
                by_id[shot_id] = prompt
    for target in targets:
        shot_id = target["id"]
        candidate = by_id.get(shot_id, "")
        original = target["prompt"]
        if not candidate or candidate == original:
            report.unresolved.append(shot_id)
            continue
        result = validate_prompt(candidate, db, options)
        structural = {f.get("kind") for f in result.findings}
        target_kinds = {f.get("kind") for f in target["findings"]}
        prompt_checks = (target_kinds & set(REPAIRABLE_KINDS)) - {
            "fluid_discontinuity", "damage_restored",
        }
        if prompt_checks & structural:
            report.unresolved.append(shot_id)
            continue
        shot = next((s for s in shots
                     if str(s.get("id") or "") == shot_id), None)
        if shot is None:
            continue
        preserved = [
            f for f in (shot.get("findings") or [])
            if f.get("kind") not in REPAIRABLE_KINDS
        ]
        additional = [
            f for f in result.findings
            if f.get("kind") not in target_kinds
        ]
        shot["prompt"] = candidate
        shot.pop("prompt_zh", None)
        if shot.get("continuity_state") or shot.get("continuity_scene"):
            shot["continuity_stale"] = True
        shot["findings"] = preserved + additional
        shot["ready"] = not any(f.get("severity") == "P1"
                                for f in shot["findings"])
        report.repaired.append(shot_id)
    return report
