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
import re
from typing import Any, Callable

from .clothing_state import clothing_gate_findings, clothing_repair_plan
from .mechanical import (
    normalize_prompt_text,
    normalize_whitespace,
    split_tags,
    strip_cjk_segments,
)
from .trace import trace_event

LogFn = Callable[[str], None]

REVIEW_STAGE_LABELS = {
    "continuity": "剧情连续性",
    "clothing": "服装连续性",
    "pacing": "节奏与覆盖",
}


def _tag_keys(value: str) -> set[str]:
    keys: set[str] = set()
    for tag in split_tags(strip_cjk_segments(value)):
        text = re.sub(r"^\(\s*(.*?)\s*:\s*[0-9.]+\s*\)$", r"\1", tag)
        keys.add(re.sub(r"[^a-z0-9]", "", text.lower()))
    return keys


def _male_present(shot: dict[str, Any]) -> bool:
    cast = str(shot.get("cast") or "").lower()
    if "boy" in cast or "男" in cast:
        return True
    return "1boy" in _tag_keys(str(shot.get("prompt") or ""))


def _shot_tagset(shot: dict[str, Any]) -> set[str]:
    provided = shot.get("_positive_tags")
    if isinstance(provided, list):
        return {re.sub(r"[^a-z0-9]", "", str(tag).lower())
                for tag in provided}
    return _tag_keys(str(shot.get("prompt") or ""))


def _pair_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def adjacent_duplicate_runs(shots: list[dict[str, Any]],
                            threshold: float = 0.98) -> list[list[str]]:
    """Consecutive shots that are (near) identical — true spinning-in-place."""
    sets = [_shot_tagset(shot) for shot in shots]
    runs: list[list[str]] = []
    i = 0
    while i < len(shots):
        j = i + 1
        while j < len(shots) and _pair_overlap(sets[j - 1], sets[j]) >= threshold:
            j += 1
        if j - i >= 2:
            runs.append([str(shots[k].get("id") or "") for k in range(i, j)])
        i = max(j, i + 1)
    return runs


def nonadjacent_similar_pairs(shots: list[dict[str, Any]],
                              threshold: float = 0.98
                              ) -> list[tuple[str, str, float]]:
    """Non-adjacent near-identical pairs. Advisory only, not a hard blocker.

    Two shots separated by other shots often legitimately share most tags
    (same outfit/scene), so these are surfaced for the AI to differentiate
    rather than treated as structural conflicts.
    """
    sets = [_shot_tagset(shot) for shot in shots]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(shots)):
        if not sets[i]:
            continue
        for j in range(i + 2, len(shots)):
            if not sets[j] or j == i + 1:
                continue
            overlap = _pair_overlap(sets[i], sets[j])
            if overlap >= threshold:
                pairs.append((str(shots[i].get("id") or ""),
                              str(shots[j].get("id") or ""), overlap))
    return pairs


def duplicate_shot_groups(shots: list[dict[str, Any]],
                          threshold: float = 0.98) -> list[list[str]]:
    """Hard duplicate groups: only consecutive identical runs."""
    return adjacent_duplicate_runs(shots, threshold)


def phase_stall_runs(shots: list[dict[str, Any]],
                     min_run: int = 10) -> list[tuple[str, list[str]]]:
    """Long consecutive runs that share one non-empty phase label."""
    runs: list[tuple[str, list[str]]] = []
    if not shots:
        return runs
    start = 0
    for i in range(1, len(shots) + 1):
        current = str(shots[start].get("phase") or "")
        changed = (i == len(shots)
                   or str(shots[i].get("phase") or "") != current)
        if not changed:
            continue
        if current and i - start >= min_run:
            runs.append((current,
                         [str(shots[k].get("id") or "")
                          for k in range(start, i)]))
        start = i
    return runs


# ordered intimacy milestones used for monotonic progression checks
RANK_ORDER = {
    "solo": 0, "masturbation": 1, "fellatio": 2, "cunnilingus": 3,
    "penetration": 4, "aftermath": 5,
}

_RANK_TAGS = (
    ("penetration", ("penisinpussy", "sex", "vaginal", "deepthrust",
                     "deep penetration")),
    ("cunnilingus", ("cunnilingus", "tongueonpussy", "tongueinpussy",
                     "oralonfemale")),
    ("fellatio", ("fellatio", "penisinmouth", "deepthroat", "blowjob",
                  "irrumatio")),
    ("masturbation", ("fingering", "masturbating", "rubbingthrough",
                      "handbetweenlegs", "sologirl")),
)


def intimacy_rank(keys: set[str]) -> int:
    rank = 0
    for label, terms in _RANK_TAGS:
        if any(term in keys for term in terms):
            rank = max(rank, RANK_ORDER[label])
    return rank


# tags are never, on their own, proof of a terminal/restart: ejaculation may
# happen during fellatio (cum in mouth/on body) mid-story and the story may
# continue. Only deviation from the user's script design is a real violation.


def story_structure_findings(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advisory progression notes relative to the user's script (NOT hard gates).

    A high-water-mark drop is only surfaced so the AI can confirm the scene
    transition is intended by the plot. Ejaculation never implies "the end".
    """
    findings: list[dict[str, Any]] = []
    high_water = 0
    for shot in shots:
        keys = _shot_tagset(shot)
        rank = intimacy_rank(keys)
        shot_id = str(shot.get("id") or "")

        if rank > high_water:
            high_water = rank
            continue
        if (high_water >= RANK_ORDER["penetration"]
                and 0 < rank < high_water):
            findings.append({
                "shot": shot_id,
                "kind": "progression_note",
                "rank": rank,
                "high_water": high_water,
                "message": (
                    "shot %s 的阶段低于此前镜头；这只是确认项——若当前场景/剧本"
                    "就是这样设计（例如口交内射、颜射、体位或场景转换），则完全允许，"
                    "无需修改；只有在它确实违背剧本顺序时才调整。射精本身不代表终章。"
                ) % shot_id,
            })
    return findings


def coverage_gate_findings(shots: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []

    # progression notes are advisory only: confirm scene intent, never a rewrite
    for finding in story_structure_findings(shots):
        issues.append(finding["message"])

    # consecutive identical shots are true duplicates the AI must differentiate
    for group in adjacent_duplicate_runs(shots):
        issues.append(
            "连续镜头 %s 的 positive 标签几乎完全相同；相邻镜头必须推进动作/姿势/构图，"
            "请逐镜区分或合并，不要复制" % ", ".join(group))

    return issues


def structural_gate_findings(shots: list[dict[str, Any]]) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    for shot in shots:
        if not _male_present(shot):
            continue
        keys = _tag_keys(str(shot.get("prompt") or ""))
        issues: list[str] = []
        if "nudemale" not in keys:
            issues.append(
                "男性在场但 positive 缺少 nude male；请补充裸体男主标签，不得保留任何男装")
        if "facelessmale" not in keys and "malefaceless" not in keys:
            issues.append(
                "男性在场但 positive 缺少 faceless male；请补充无脸男主标签")
        if issues:
            findings[str(shot.get("id") or "")] = issues
    return findings

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
    "- 初始服装中带权重强调（如 tag(1.2)）的单品全程保留、不允许完全脱下：裤袜/丝袜类可以撕裂破洞，"
    "胸罩类可以半脱/滑肩带，内裤类可以挪到一边（panties aside），以增加情趣；鞋与发饰等保持在身。\n"
    "- 初始服装中不带权重的常规外衣（外套、衬衣、披风、连体衣、裙子、手套、肩章等）必须在最后一镜前全部脱下，"
    "脱下后放在一个固定位置，不得在 desk/floor 之间跳变，也不得穿回。\n"
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
        "- 镜头数多于剧情节点时，在终局/射精之前把动作拆成更细微节拍；"
        "全片终局（射精/内射/最终依偎）只能出现在最后一镜，"
        "终局之后不得重新开始舔阴/性交/射精（否则是 story_restart）。\n"
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
                    history: list[dict[str, Any]],
                    gate: dict[str, list[str]] | None = None,
                    coverage: list[str] | None = None,
                    clothing_plan: dict[str, Any] | None = None) -> list[dict[str, str]]:
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
    if clothing_plan:
        batch_ids = {str(shot.get("id") or "") for shot in batch}
        relevant = [fix for fix in clothing_plan.get("fixes", [])
                    if fix.get("shot") in batch_ids]
        user_payload["clothing_ledger"] = clothing_plan.get("ledger", {})
        user_payload["required_fixes"] = relevant
        if clothing_plan.get("residual"):
            batch_ids = {str(shot.get("id") or "") for shot in batch}
            user_payload["residual_tags"] = [
                item for item in clothing_plan["residual"]
                if item.get("shot") in batch_ids]
            system_parts.append(
                "residual_tags 指出你上一轮没有删掉的标签；这些标签必须在本次 prompt 中删除，"
                "不得再次保留。")
        system_parts.append(
            "required_fixes 是只读服装状态机给出的可执行指令，每条含 shot/category/tags/expected/keep，"
            "必须严格照做：从该镜英文 prompt 中删除 tags 列出的冲突标签，按 expected 改写，"
            "保留 keep 中的标签；不得保留 tags 里任何一个标签。\n"
            "clothing_ledger 是全片每镜每类服装的状态（worn/displaced/off），"
            "你的改写必须与台账及服装单向推进规则一致；权重服装（weighted=true）只能保持 active，"
            "非权重服装到结局前必须 off。不得用文字说明代替实际改标签。")
    elif gate:
        user_payload["required_fixes"] = gate
        system_parts.append(
            "required_fixes 是软件只读结构闸门发现的硬性问题，必须逐条修复，"
            "并在对应 shot 的英文 prompt 中补齐标签；不得忽略，不得用文字说明代替。")
    if coverage:
        user_payload["coverage_fixes"] = coverage
        system_parts.append(
            "coverage_fixes 是软件只读覆盖闸门发现的硬性缺失，必须通过新增或重写镜头来补齐，"
            "让缺失事件真实发生在对应剧情阶段；不得只在镜头说明里事后追述。")
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


def _history_before(shots: list[dict[str, Any]], end: int,
                    window: int = 4) -> list[dict[str, Any]]:
    start = max(0, end - max(0, int(window)))
    return shots[start:max(0, end)]


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
    previous_residual: dict[tuple[str, str], list[str]] = {}
    for _pass in range(max(1, int(max_passes))):
        pass_changes = 0
        invalid_remaining = False
        current_residual: dict[tuple[str, str], list[str]] = {}
        for offset in range(0, len(shots), max(1, int(batch_size))):
            batch = shots[offset:offset + max(1, int(batch_size))]
            history = _history_before(shots, offset)
            batch_gate = {}
            batch_coverage: list[str] = []
            plan: dict[str, Any] = {}
            if stage == "clothing":
                plan = clothing_repair_plan(shots, premise)
                if previous_residual:
                    plan = dict(plan)
                    residual_notes = []
                    for (_shot, category), tags in previous_residual.items():
                        residual_notes.append(
                            {"shot": _shot, "category": category,
                             "message": "上一轮要求删除但仍残留在 prompt 中的标签，"
                                        "本次必须删除",
                             "residual_tags": tags})
                    plan["residual"] = residual_notes
            if stage == "pacing":
                batch_coverage = coverage_gate_findings(shots)
            try:
                raw = client.chat_json(
                    model,
                    _build_messages(stage, premise, batch, history,
                                    batch_gate, batch_coverage,
                                    clothing_plan=plan or None),
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
        gate: dict[str, list[str]] = {}
        if stage == "clothing":
            gate = structural_gate_findings(shots)
        coverage = coverage_gate_findings(shots) if stage == "pacing" else []
        plan_remaining = (
            clothing_repair_plan(shots, premise).get("fixes", [])
            if stage == "clothing" else [])
        if stage == "clothing":
            current_residual = {
                (fix["shot"], fix["category"]): fix["tags"]
                for fix in plan_remaining}
        if gate:
            invalid_remaining = True
        if plan_remaining:
            invalid_remaining = True
        if coverage:
            invalid_remaining = True
        trace_event("review.pass_summary", {
            "stage": stage,
            "pass": _pass + 1,
            "changes": pass_changes,
            "invalid_remaining": invalid_remaining,
            "structural_gate": gate,
            "coverage_gate": coverage,
        })
        if not invalid_remaining:
            break
        previous_residual = current_residual
    return total_changes


def final_gate_blockers(shots: list[dict[str, Any]],
                        premise: str = "") -> list[str]:
    """Hard blockers limited to true script violations.

    Only clothing-state violations and consecutive identical shots block.
    Ejaculation timing / phase backtrack / non-adjacent similarity are never
    hard blockers: the highest rule is conformance to the user's script.
    """
    blockers: list[str] = []
    plan = clothing_repair_plan(shots, premise)
    for fix in plan["fixes"]:
        blockers.append(
            "shot %s %s: %s（%s）" % (
                fix["shot"], fix["kind"], fix["category"],
                ", ".join(fix["tags"])))
    for group in adjacent_duplicate_runs(shots):
        blockers.append(
            "consecutive duplicate positive tags across shots %s"
            % ", ".join(group))
    return blockers


def ensure_final_gate(client: Any, model: str,
                      shots: list[dict[str, Any]], premise: str,
                      *, timeout: float = 600.0,
                      log: LogFn | None = None,
                      profiles: list[Any] | None = None,
                      max_cycles: int = 5
                      ) -> tuple[int, list[str]]:
    """Keep repairing clothing + pacing during generation until gate clears.

    The software never edits tags; the AI rewrites. Returns
    ``(cycles_performed, remaining_blockers)``. A non-empty remaining list
    means the story is NOT ready and the caller must not treat it as complete.
    """
    remaining = final_gate_blockers(shots, premise)
    if not shots or not remaining:
        return 0, []
    profiles = profiles or []
    performed = 0
    for cycle in range(max(1, int(max_cycles))):
        clothing_fixes = clothing_repair_plan(shots, premise).get("fixes", [])
        if clothing_fixes:
            if log:
                log("最终闸门修复：服装 第%d轮（%d项）" % (
                    cycle + 1, len(clothing_fixes)))
            review_stage_ai(
                client, model, "clothing", shots, premise,
                batch_size=10, max_passes=1,
                timeout=timeout, log=log, profiles=profiles)
        if final_gate_blockers(shots, premise):
            if log:
                log("最终闸门修复：节奏/重复/阶段 第%d轮" % (cycle + 1))
            review_stage_ai(
                client, model, "pacing", shots, premise,
                batch_size=10, max_passes=1,
                timeout=timeout, log=log, profiles=profiles)
        performed += 1
        remaining = final_gate_blockers(shots, premise)
        if not remaining:
            if log:
                log("最终闸门已通过。")
            break
        if log:
            log("最终闸门剩余 %d 项，继续。" % len(remaining))
    return performed, remaining


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
