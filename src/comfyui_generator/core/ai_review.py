"""AI-driven story review and rewrite orchestration.

The software never decides or produces semantics. This module only:
1. assembles the stage context and instructions,
2. asks the AI to review and, when needed, rewrite,
3. parses the AI's structured verdict and adopts it verbatim,
4. loops until the AI reports every shot valid or the attempt budget is spent.

Three review stages run, each merging several review dimensions into one call:
- continuity: plot/action/scene/cast continuity, duplication, regression
- clothing: clothing and nudity state, layers, damage permanence
- pacing: long runs, phase backtracking, repetition, coverage and rhythm

The AI also produces each shot's English negative prompt.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .mechanical import (
    normalize_prompt_text,
    normalize_whitespace,
    split_tags,
)
from .trace import trace_event

LogFn = Callable[[str], None]

REVIEW_STAGE_LABELS = {
    "continuity": "剧情连续性",
    "clothing": "服装连续性",
    "pacing": "节奏与覆盖",
}

_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "valid": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "negative": {"type": "string"},
                    "cast": {"type": "string"},
                    "script": {"type": "string"},
                    "prompt": {"type": "string"},
                    "phase": {"type": "string"},
                    "beat": {"type": "string"},
                    "clothing": {"type": "string"},
                    "clothing_state": {"type": "string"},
                    "scene": {"type": "string"},
                    "camera": {"type": "string"},
                    "nsfw": {"type": "string"},
                },
                "required": ["id", "valid"],
            },
        },
    },
    "required": ["shots"],
}

_GLOBAL_RULES = (
    "你在为一条二次元 NSFW 连续剧情分镜工作。用户的原始需求是最高约束：\n"
    "{premise}\n\n"
    "通用要求：\n"
    "- 所有剧情、动作、姿势、表情、服装/裸露语义、构图与 positive/negative 内容都只能由你（AI）决定，"
    "软件不会替你编写或修正任何语义。\n"
    "- 男主只要出场，始终裸体、无脸（faceless male、nude male），优先近景/上半身/局部，"
    "只有动作确实需要时才使用全身；script 中若出现男装描述，视为错误并由你修正。\n"
    "- 服装按剧情单向推进：常规服装脱下后不复穿；任何破损（torn/ripped/hole）永久保留；"
    "隔着衣物、手伸入内层、直接接触等层次必须与剧情一致。\n"
    "- 动作只能向前推进，已经插入/性交后不得无过渡回到自慰、口交或初遇。\n"
)

_STAGE_BRIEFS = {
    "continuity": (
        "本阶段只审“剧情连续性”，把以下维度合并判断：\n"
        "- 是否重复已经发生的事件、前戏节拍、对话或动作；\n"
        "- 是否在推进后无理由回到更早阶段；\n"
        "- 是否连续多镜只换同义词而剧情没有前进；\n"
        "- 相邻镜头动作/姿势是否物理连贯；场景、时间、光线是否无过渡跳变；\n"
        "- cast 与实际在场人物是否一致；男性提前或缺失出场都算问题。\n"
    ),
    "clothing": (
        "本阶段只审“服装与裸露连续性”，把以下维度合并判断：\n"
        "- 上一镜仍穿着的衣物是否在本镜无理由消失；\n"
        "- 半脱/拨开/破损状态是否无依据恢复完整；已脱衣物是否无依据重现；\n"
        "- 是否出现无剧本依据的新衣物；破损单品是否又同时保留完整基础标签；\n"
        "- 全裸/半裸标签与服装标签是否矛盾；同一服装类别是否只有一个有效状态；\n"
        "- 裤袜不是第二件内裤；外衣、胸罩、裤袜、内裤的层级与遮挡是否正确。\n"
    ),
    "pacing": (
        "本阶段只审“节奏与覆盖”，把以下维度合并判断：\n"
        "- 是否存在超过 15-20 镜的同一阶段长段；\n"
        "- 是否有 phase 回退、原地打转或结尾拖长度；\n"
        "- 用户明确要求的关键节拍是否全部覆盖且顺序正确；\n"
        "- 镜头数多于剧情节点时，是否把动作合理拆成更细微节拍而不是循环。\n"
    ),
}

_OUTPUT_RULES = (
    "对 shots 中每一镜返回判定：\n"
    "- 若该镜在本阶段没有问题：valid=true，issues 留空，不要返回 prompt 或 script。\n"
    "- 若有问题：valid=false，在 issues 中逐条写清问题，并由你直接重写该镜；"
    "重写时保留角色、场景、动作风格与 NSFW 强度，只修正本阶段相关语义。"
    "重写时请同时给出需要的字段：prompt（英文 Booru 正向）以及适用的 "
    "cast/script/phase/beat/clothing/scene/camera/nsfw。\n"
    "- 每一镜都必须返回 negative：用英文 Booru 标签写当前这一镜专属的负向提示词，"
    "逗号分隔；negative 必须与该镜 positive 一致，不得压制 positive 明确要求的内容。\n"
    "只输出 JSON：{shots:[{id,valid,issues,negative,prompt,cast,script,phase,beat,"
    "clothing,scene,camera,nsfw}]}，不要解释。"
)

_SHOT_FIELDS = (
    ("cast", "cast"),
    ("phase", "phase"),
    ("beat", "beat"),
    ("script", "script"),
    ("prompt", "prompt"),
    ("clothing", "clothing"),
    ("scene", "scene"),
    ("camera", "camera"),
    ("nsfw", "nsfw"),
)


def _shot_payload(shot: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": str(shot.get("id") or "")}
    for field, key in _SHOT_FIELDS:
        value = shot.get(field)
        if value not in (None, ""):
            payload[key] = str(value)
    negative = shot.get("negative")
    if negative not in (None, ""):
        payload["negative"] = str(negative)
    return payload


def _build_messages(stage: str, premise: str,
                    batch: list[dict[str, Any]],
                    history: list[dict[str, Any]]) -> list[dict[str, str]]:
    system_parts = [
        _GLOBAL_RULES.format(premise=normalize_whitespace(premise)),
        _STAGE_BRIEFS[stage],
        _OUTPUT_RULES,
    ]
    user_payload = {
        "review_stage": REVIEW_STAGE_LABELS[stage],
        "history": [_shot_payload(shot) for shot in history],
        "shots": [_shot_payload(shot) for shot in batch],
    }
    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": json.dumps(
            user_payload, ensure_ascii=False)},
    ]


def _coerce_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        value = raw.get("shots")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _history_before(shots: list[dict[str, Any]], end: int) -> list[dict[str, Any]]:
    return shots[:max(0, end)]


def _apply_clothing_details(shot: dict[str, Any],
                            profiles: list[Any]) -> None:
    girl = next((p for p in profiles if getattr(p, "gender", "") == "girl"),
                None)
    if girl is None:
        return
    details = shot.setdefault("clothing_details", {})
    if not isinstance(details, dict):
        return
    state = str(shot.get("clothing_state") or "").strip().lower()
    if state in ("", "none", "无", "没有"):
        details[girl.key] = ""
        return
    tags = split_tags(state)
    if tags:
        details[girl.key] = ", ".join(sorted(tags))


def _apply_item(shot: dict[str, Any], item: dict[str, Any],
                stage: str, log: LogFn | None,
                profiles: list[Any]) -> bool:
    changed = False
    negative = str(item.get("negative") or "").strip()
    if negative:
        shot["negative"] = normalize_prompt_text(negative)
        changed = True
    if "clothing_state" in item:
        shot["clothing_state"] = str(item.get("clothing_state") or "").strip()
        _apply_clothing_details(shot, profiles)
        changed = True
    if item.get("valid") is False:
        issues = [str(value) for value in (item.get("issues") or []) if str(value).strip()]
        rewritten = False
        for field, _key in _SHOT_FIELDS:
            value = item.get(field)
            if value not in (None, ""):
                shot[field] = str(value).strip()
                rewritten = True
        if rewritten:
            changed = True
        if log and issues:
            log("%s重写 shot %s：%s" % (
                REVIEW_STAGE_LABELS[stage], shot.get("id", ""),
                issues[0][:100]))
    return changed


def review_stage_ai(client: Any, model: str, stage: str,
                    shots: list[dict[str, Any]], premise: str,
                    *, batch_size: int = 10,
                    max_passes: int = 2,
                    temperature: float = 0.3,
                    num_predict: int = 16384,
                    timeout: float = 600.0,
                    log: LogFn | None = None,
                    profiles: list[Any] | None = None) -> int:
    if stage not in _STAGE_BRIEFS or not shots:
        return 0
    profiles = profiles or []
    total_changes = 0
    for _pass in range(max(1, int(max_passes))):
        pass_changes = 0
        invalid_remaining = False
        for offset in range(0, len(shots), max(1, int(batch_size))):
            batch = shots[offset:offset + max(1, int(batch_size))]
            history = _history_before(shots, offset)
            try:
                raw = client.chat_json(
                    model,
                    _build_messages(stage, premise, batch, history),
                    schema=_REVIEW_SCHEMA,
                    temperature=temperature,
                    num_predict=num_predict,
                    num_ctx=32768,
                    timeout=timeout,
                    retries=1,
                )
            except Exception as exc:
                if log:
                    log("AI %s审查失败，保留原内容: %s" % (
                        REVIEW_STAGE_LABELS[stage], exc))
                trace_event("review.ai_error", {
                    "stage": stage, "error": repr(exc)})
                invalid_remaining = True
                continue
            items = _coerce_items(raw)
            by_id = {
                str(item.get("id") or ""): item for item in items
            }
            for index, shot in enumerate(batch):
                item = by_id.get(str(shot.get("id") or ""))
                if item is None and index < len(items):
                    item = items[index]
                if not isinstance(item, dict):
                    invalid_remaining = True
                    continue
                before = dict(shot)
                if _apply_item(shot, item, stage, log, profiles):
                    pass_changes += 1
                if item.get("valid") is False:
                    invalid_remaining = True
                trace_event("review.ai", {
                    "stage": stage,
                    "id": str(shot.get("id") or ""),
                    "before": before,
                    "after": dict(shot),
                    "item": item,
                })
        total_changes += pass_changes
        trace_event("review.pass_summary", {
            "stage": stage,
            "pass": _pass + 1,
            "changes": pass_changes,
            "invalid_remaining": invalid_remaining,
        })
        if not invalid_remaining:
            break
    return total_changes


def run_all_reviews(client: Any, model: str,
                    shots: list[dict[str, Any]], premise: str,
                    *, batch_size: int = 10,
                    max_passes: int = 2,
                    timeout: float = 600.0,
                    log: LogFn | None = None,
                    profiles: list[Any] | None = None,
                    stages: tuple[str, ...] = ("continuity", "clothing", "pacing")
                    ) -> None:
    for stage in stages:
        if log:
            log("AI 审查：%s" % REVIEW_STAGE_LABELS[stage])
        review_stage_ai(
            client, model, stage, shots, premise,
            batch_size=batch_size, max_passes=max_passes,
            timeout=timeout, log=log, profiles=profiles)
