"""Three-stage waterfall generation with in-stage closure.

Quality is locked at the stage that creates it; later stages never rewrite the
whole film. Every AI request carries the deterministic spec of what a correct
answer is, and every returned item is verified immediately and in isolation.

Stages:
  1. outline  : blueprint (ordered milestones, terminal locked to last shot)
                -> numbered outline; only the offending entries are returned,
                each with the exact shot range and previous error.
  2. script   : one Chinese script per outline entry; locked before tags.
  3. tags     : each locked script converted to English Booru tags; deterministic
                checks for male nudity/faceless, clothing state, and adjacent
                duplicates; the AI is told the exact correct rewrite.

The software never writes semantics. It only parses, persists, verifies, and
rejects. A shot that cannot be made correct is marked ready=false and keeps the
last AI candidate; rendering remains available and the shot can be repaired
individually. The pipeline never re-sends the full film.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .action_state import (
    male_is_present,
    performed_action_categories,
)
from .clothing_state import clothing_repair_plan
from .mechanical import normalize_prompt_text
from .story_blueprint import (
    blueprint_text,
    blueprint_violations,
    normalize_blueprint,
)
from .project import shot_is_ready
from .trace import trace_event

LogFn = Callable[[str], None]

MAX_ATTEMPTS = 3


class StageError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# generic helpers
# --------------------------------------------------------------------------- #

def _emit(event: str, data: Any) -> None:
    trace_event(event, data)


def _extract_shots(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        value = raw.get("shots")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _find_item(items: list[dict[str, Any]], shot_id: str,
               index: int) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("id") or "") == str(shot_id):
            return item
    if index < len(items):
        return items[index]
    return None


def _ask_blueprint(client: Any, model: str,
                   premise: str, total: int,
                   *, timeout: float, log: LogFn) -> list[dict[str, Any]]:
    """Stage 1a: get a blueprint and require it to pass structural validation."""
    from .story_blueprint import build_blueprint_messages, BLUEPRINT_SCHEMA

    best: list[dict[str, Any]] = []
    for attempt in range(MAX_ATTEMPTS):
        raw = client.chat_json(
            model,
            build_blueprint_messages(premise, total),
            schema=BLUEPRINT_SCHEMA,
            temperature=0.3,
            num_predict=4096,
            num_ctx=32768,
            timeout=timeout,
            retries=1,
        )
        milestones = normalize_blueprint(raw, total)
        violations = blueprint_violations(milestones, total)
        best = milestones
        if not violations:
            log("蓝图已通过：里程碑保序，终局锁定第%d镜。" % total)
            return milestones
        log("蓝图第%d次未通过，告知正确结构后重规划：%s" % (
            attempt + 1, "；".join(violations)))
        _emit("stage.blueprint_rejected", {
            "attempt": attempt + 1, "violations": violations})
    raise StageError("蓝图始终无法通过结构校验：%s" %
                     "；".join(blueprint_violations(best, total)))


def _milestone_for_shot(milestones: list[dict[str, Any]],
                        shot_number: int) -> dict[str, Any]:
    for entry in milestones:
        if int(entry["start"]) <= shot_number <= int(entry["end"]):
            return entry
    return milestones[-1]


def _outline_spec(milestones: list[dict[str, Any]],
                  shot_number: int) -> dict[str, Any]:
    entry = _milestone_for_shot(milestones, shot_number)
    return {
        "shot": shot_number,
        "milestone_index": int(entry["index"]),
        "milestone_title": str(entry.get("title") or ""),
        "terminal": bool(entry.get("terminal")),
        "correct_rule": (
            "第%d镜必须属于里程碑%d（%s），%s" % (
                shot_number, int(entry["index"]),
                entry.get("title") or "",
                "且这是全片最后一镜的终局，终局只能出现在这里。"
                if entry.get("terminal") else
                "不得提前或延后到其它里程碑。")),
    }


def _verify_outline_entry(milestones: list[dict[str, Any]],
                          shot_number: int,
                          item: dict[str, Any]) -> list[str]:
    """Deterministic checks for one outline entry."""
    errors: list[str] = []
    expected = _milestone_for_shot(milestones, shot_number)
    outline = str(item.get("outline") or item.get("script") or "").strip()
    if not outline:
        errors.append("第%d镜缺少 outline 正文" % shot_number)
    milestone_raw = item.get("milestone_index")
    if milestone_raw not in (None, ""):
        try:
            milestone_index = int(milestone_raw)
        except (TypeError, ValueError):
            errors.append("第%d镜 milestone_index 必须是整数" % shot_number)
        else:
            if milestone_index != int(expected["index"]):
                errors.append(
                    "第%d镜应属于里程碑%d，但返回了里程碑%d" % (
                        shot_number, int(expected["index"]), milestone_index))
    future = _shot_blueprint_findings(
        milestones, int(expected["index"]),
        text=outline,
        cast=str(item.get("cast") or ""),
        present_characters=item.get("present_characters"))
    for finding in future:
        errors.append(
            "第%d镜%s（%s）" % (
                shot_number, finding["message"], finding["correct"]))
    return errors


def _milestone_action_intro(
        milestones: list[dict[str, Any]]) -> dict[str, int]:
    """First milestone index that introduces each high-salience action.

    Actions are classified from milestone titles only, so the mapping is a
    structural property of the blueprint, not authored by the software.
    """
    intro: dict[str, int] = {}
    for entry in milestones:
        index = int(entry["index"])
        for category in performed_action_categories(
                str(entry.get("title") or "")):
            if category not in intro:
                intro[category] = index
    return intro


_ACTION_LABELS = {
    "blowjob": "口交",
    "cum_shot": "体外射精",
    "creampie": "阴道内射",
    "cunnilingus": "舔阴",
    "vaginal_sex": "阴道性交",
}


def _milestone_specs(
        milestones: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Canonical per-milestone state, derived structurally from the blueprint.

    Each spec records the actors allowed and the high-salience actions
    introduced. Presence of the male is derived from the milestone title, so
    it works for any story without hard-coded names.
    """
    action_intro = _milestone_action_intro(milestones)
    specs: dict[int, dict[str, Any]] = {}
    male_intro: int | None = None
    for entry in milestones:
        index = int(entry["index"])
        title = str(entry.get("title") or "")
        male_here = male_is_present(text=title)
        if male_here and male_intro is None:
            male_intro = index
        actions = {category for category, at in action_intro.items()
                   if at == index}
        specs[index] = {
            "index": index,
            "title": title,
            "male_present": bool(male_intro is not None),
            "male_introduced": bool(male_here and male_intro == index),
            "actions": actions,
        }
    return specs


def _future_action_findings(milestones: list[dict[str, Any]],
                            allowed_index: int,
                            text: str) -> list[dict[str, str]]:
    """High-salience actions in text introduced only by later milestones."""
    intro = _milestone_action_intro(milestones)
    titles = {int(entry["index"]): str(entry.get("title") or "")
              for entry in milestones}
    findings: list[dict[str, str]] = []
    for category in performed_action_categories(text):
        introduced = intro.get(category)
        if introduced is None or introduced <= allowed_index:
            continue
        label = _ACTION_LABELS.get(category, category)
        findings.append({
            "kind": "future_action",
            "category": category,
            "message": "提前出现了里程碑%d才发生的%s" % (introduced, label),
            "correct": "该动作只允许在里程碑%d（%s）发生，本镜不得写出它已发生" % (
                introduced, titles.get(introduced, "")),
        })
    return findings


def _shot_blueprint_findings(
        milestones: list[dict[str, Any]],
        allowed_index: int,
        *,
        text: str,
        cast: str = "",
        present_characters: Any = None) -> list[dict[str, str]]:
    """Unified pre-tag validation: actor presence + action ownership.

    This is the single source of truth used by both the outline and script
    stages. It rejects (1) a character appearing before the milestone that
    introduces them and (2) actions introduced only by later milestones.
    """
    specs = _milestone_specs(milestones)
    spec = specs.get(int(allowed_index))
    findings: list[dict[str, str]] = []
    if spec is not None and not spec["male_present"]:
        male_intro = next((i for i, s in specs.items()
                           if s["male_introduced"]), None)
        if male_intro is not None and male_is_present(
                cast=cast, present_characters=present_characters, text=text):
            findings.append({
                "kind": "future_character",
                "category": "male",
                "message": "提前出现了里程碑%d才登场的男主" % male_intro,
                "correct": (
                    "男主只允许在里程碑%d（%s）登场，本镜不得出现男主；"
                    "请把 cast 改为只含女主（如 1girl），"
                    "present_characters 中只保留女主、删除 male/男主，"
                    "正文里也不得写男主的动作或在场" % (
                        male_intro, specs[male_intro]["title"])),
            })
    for finding in _future_action_findings(milestones, allowed_index, text):
        findings.append(finding)
    return findings


def _shot_guidance(milestones: list[dict[str, Any]],
                   allowed_index: int,
                   prev_outline: str = "") -> str:
    """Positive, per-shot instruction telling the model exactly what to write.

    Derived structurally from the owning milestone: which actors may be on
    screen and what the milestone is supposed to accomplish. This gives the
    model a concrete target instead of only a list of forbidden things.
    """
    specs = _milestone_specs(milestones)
    spec = specs.get(int(allowed_index))
    if spec is None:
        return ""
    title = str(spec.get("title") or "").strip()
    lines = ["本镜硬性要求（必须遵守）："]
    if not spec["male_present"]:
        male_intro = next((i for i, s in specs.items()
                           if s["male_introduced"]), None)
        lines.append(
            "- 本镜只有女主一个人，cast 只能写 1girl，present_characters 只保留女主；"
            + ("男主到里程碑%d才登场，本镜绝对不能出现男主、门不能开、不能有任何人。"
               % male_intro if male_intro is not None else
               "本镜不得出现男主或任何人。"))
        lines.append(
            "- 请只推进女主独处时的剧情（对应里程碑：%s），"
            "例如延续/加强她自身的动作、表情、呼吸、临近高潮或情绪变化；"
            "不要写插入、性交、口交等需要男主的动作。" % title)
    else:
        lines.append(
            "- 本镜属于里程碑（%s）：cast 按该里程碑写，只表现该里程碑的动作，"
            "不要提前写更晚里程碑才发生的动作（如后续性交、射精）。" % title)
    if prev_outline:
        lines.append(
            "- 要在上一镜基础上继续推进，不得复制上一镜：%s"
            % prev_outline[:80])
    return "\n".join(lines)



def _plan_outline(client: Any, model: str,
                  premise: str, total: int, *,
                  setting: str, strip_appearance: bool,
                  milestones: list[dict[str, Any]],
                  timeout: float, log: LogFn) -> list[dict[str, Any]]:
    """Stage 1b: numbered outline, verified one entry at a time."""
    from .storyboard import (
        build_outline_messages,
        normalize_outline,
    )

    outline: list[dict[str, str]] = []
    used_names: list[str] = []
    for shot_number in range(1, total + 1):
        spec = _outline_spec(milestones, shot_number)
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            correct = spec["correct_rule"]
            if last_error:
                correct += "；上一轮错误：" + last_error
            raw = client.chat_json(
                model,
                build_outline_messages(
                    premise, 1, setting, outline, total, shot_number,
                    strip_appearance=strip_appearance,
                    story_state=_shot_guidance(
                        milestones, int(spec["milestone_index"]),
                        str(outline[-1].get("outline")) if outline else ""),
                    blueprint=blueprint_text(milestones)),
                schema={"type": "object", "properties": {
                    "shots": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "milestone_index": {"type": "integer"},
                            "outline": {"type": "string"},
                            "cast": {"type": "string"},
                        },
                        "required": ["id", "milestone_index", "outline"]}}},
                    "required": ["shots"]},
                temperature=0.6,
                num_predict=3072,
                num_ctx=32768,
                timeout=timeout,
                retries=1,
            )
            items = _extract_shots(raw)
            item = _find_item(items, "%02d" % shot_number, 0)
            if item is None:
                last_error = "没有返回第%d镜" % shot_number
                log("大纲第%d镜第%d次无结果，明确要求后重发。" % (
                    shot_number, attempt + 1))
                continue
            errors = _verify_outline_entry(milestones, shot_number, item)
            if errors:
                last_error = "；".join(errors)
                log("大纲第%d镜未通过：%s —— 告知正确后重发。" % (
                    shot_number, last_error))
                continue
            part = normalize_outline(
                {"shots": [item]}, 1,
                "story", start=shot_number, used_names=used_names)
            entry = part[0]
            entry["milestone_index"] = str(spec["milestone_index"])
            outline.append(entry)
            used_names.append(entry["name"])
            log("大纲第%d/%d镜定稿（里程碑%d）。" % (
                shot_number, total, spec["milestone_index"]))
            break
        else:
            raise StageError(
                "大纲第%d镜连续%d次无法通过：%s" % (
                    shot_number, MAX_ATTEMPTS, last_error))
    _emit("stage.outline_locked", outline)
    return outline


def _write_scripts(client: Any, model: str,
                   premise: str, total: int, *,
                   setting: str, strip_appearance: bool,
                   outline: list[dict[str, str]],
                   milestones: list[dict[str, Any]],
                   timeout: float, log: LogFn) -> list[dict[str, str]]:
    """Stage 2: one Chinese script per outline entry, locked before tags."""
    from .storyboard import build_script_messages, normalize_scripts

    locked: list[dict[str, str]] = []
    used_names: list[str] = []
    for index, outline_entry in enumerate(outline):
        shot_number = index + 1
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            messages = build_script_messages(
                premise, 1, setting, locked, total,
                [outline_entry["outline"]],
                strip_appearance=strip_appearance,
                phase=str(outline_entry.get("phase") or ""),
                cast_hint=str(outline_entry.get("cast") or ""))
            if last_error:
                messages = list(messages)
                messages[-1] = dict(messages[-1])
                messages[-1]["content"] += (
                    "\n上一轮脚本不合格：" + last_error +
                    "\n这是必须满足的硬性剧情条目：" + outline_entry["outline"] +
                    "\n请严格只写这一镜，从第%d镜开始编号。" % shot_number)
            raw = client.chat_json(
                model, messages,
                schema={"type": "object", "properties": {
                    "shots": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "cast": {"type": "string"},
                            "script": {"type": "string"},
                        },
                        "required": ["id", "cast", "script"]}}},
                    "required": ["shots"]},
                temperature=0.6,
                num_predict=3072,
                num_ctx=32768,
                timeout=timeout,
                retries=1,
            )
            items = _extract_shots(raw)
            item = _find_item(items, "%02d" % shot_number, 0)
            if item is None or not str(item.get("script") or "").strip():
                last_error = "缺少第%d镜 script 正文" % shot_number
                log("脚本第%d镜第%d次无正文，明确要求后重发。" % (
                    shot_number, attempt + 1))
                continue
            part = normalize_scripts(
                {"shots": [item]}, 1, "story",
                start=shot_number, used_names=used_names)
            entry = part[0]
            entry["cast"] = str(outline_entry.get("cast") or entry.get("cast") or "")
            entry["outline"] = outline_entry["outline"]
            if outline_entry.get("phase"):
                entry["phase"] = outline_entry["phase"]
            locked.append(entry)
            used_names.append(entry["name"])
            log("脚本第%d/%d镜定稿。" % (shot_number, total))
            break
        else:
            raise StageError(
                "脚本第%d镜连续%d次无法通过：%s" % (
                    shot_number, MAX_ATTEMPTS, last_error))
    _emit("stage.scripts_locked", locked)
    return locked


# --------------------------------------------------------------------------- #
# stage 3 deterministic tag verification
# --------------------------------------------------------------------------- #

def _shot_findings(accepted: list[dict[str, str]],
                   candidate: dict[str, str],
                   premise: str,
                   is_last: bool = False) -> list[dict[str, str]]:
    """Deterministic tag findings for one candidate shot.

    ``accepted`` are earlier shots that already carry their English prompt.
    Covers clothing state, male nudity/faceless, and adjacent duplication.
    Non-weighted clothing only has to be off on the final shot.
    Returns [{kind, message, correct}] where correct states the exact fix.
    """
    sequence = accepted + [candidate]
    findings: list[dict[str, str]] = []

    plan = clothing_repair_plan(sequence, premise)
    for fix in plan["fixes"]:
        if str(fix["shot"]) != str(candidate.get("id")):
            continue
        if fix["kind"] == "must_be_off" and not is_last:
            continue
        if fix["kind"] == "undergarment_visible_missing":
            findings.append({
                "kind": "clothing:" + fix["kind"],
                "message": "%s：按服装层级当前应可见但缺少标签（%s）" % (
                    fix["category"], ", ".join(fix["keep"])),
                "correct": fix["expected"],
                "tags": "",
                "keep": ", ".join(fix["keep"]),
            })
            continue
        findings.append({
            "kind": "clothing:" + fix["kind"],
            "message": "%s：冲突标签 %s" % (
                fix["category"], ", ".join(fix["tags"])),
            "correct": fix["expected"],
            "tags": ", ".join(fix["tags"]),
            "keep": ", ".join(fix["keep"]),
        })

    cast = str(candidate.get("cast") or "").lower()
    male_present = ("boy" in cast or "男" in cast
                    or "1boy" in str(candidate.get("prompt") or ""))
    if male_present:
        prompt = str(candidate.get("prompt") or "").lower()
        if "nude male" not in prompt and "male nude" not in prompt:
            findings.append({
                "kind": "male_nude",
                "message": "男主在场但缺少 nude male",
                "correct": "在该镜 positive 中加入 nude male，并删除一切男装标签",
                "tags": "", "keep": "",
            })
        if "faceless male" not in prompt and "male faceless" not in prompt:
            findings.append({
                "kind": "male_faceless",
                "message": "男主在场但缺少 faceless male",
                "correct": "在该镜 positive 中加入 faceless male，并删除露脸标签",
                "tags": "", "keep": "",
            })

    if accepted:
        prev_tags = {t.strip() for t in str(
            accepted[-1].get("prompt") or "").split(",") if t.strip()}
        cur_tags = {t.strip() for t in str(
            candidate.get("prompt") or "").split(",") if t.strip()}
        if prev_tags and cur_tags:
            overlap = len(prev_tags & cur_tags) / max(1, len(prev_tags | cur_tags))
            if overlap >= 0.98:
                findings.append({
                    "kind": "adjacent_duplicate",
                    "message": "与上一镜 positive 几乎完全相同（%.0f%%）" % (
                        overlap * 100),
                    "correct": "推进动作/姿势/构图，使本镜与上一镜明确区分，不要复制",
                    "tags": "", "keep": "",
                })

    for message in _action_stall_findings(sequence):
        findings.append({
            "kind": "action_stall",
            "message": message,
            "correct": "本镜必须改变至少一个维度：体位、施动者、身体部位、"
                       "场景位置或镜头机位；给出明确的新动作，不得换词复述同一动作",
            "tags": "", "keep": "",
        })
    return findings


STALL_MIN_RUN = 4

_ACTION_SIGNATURE_RE = re.compile(
    r"\b(?:penis in (?:pussy|mouth)|penis between buttocks|"
    r"(?:vaginal|standing|standing )?(?:sex)|fellatio|blowjob|"
    r"(?:deep )?throat(?:ing)?|cunnilingus|"
    r"(?:fast |slow |hard )?thrusting|hip thrusts?|"
    r"hand job|ahegao|orgasm|cum(?:min)? shot|"
    r"cum (?:in|on|swallowing)|cum swallowing|creampie|"
    r"panties aside|rubbing through panties|groping|"
    r"fingers? inside (?:panties|pussy)|masturbation|"
    r"fingering|sex from behind|penetration)\b")


def _action_signature(prompt: str) -> frozenset[str]:
    return frozenset(
        m.group(0) for m in _ACTION_SIGNATURE_RE.finditer(
            str(prompt or "").lower()))


def _action_stall_findings(sequence: list[dict[str, Any]]) -> list[str]:
    """Count a trailing run of shots sharing one explicit-action signature."""
    sigs = [_action_signature(s.get("prompt", "")) for s in sequence]
    if not sigs or not sigs[-1]:
        return []
    run = 1
    current = sigs[-1]
    for sig in reversed(sigs[:-1]):
        if sig and sig == current:
            run += 1
        else:
            break
    if run < STALL_MIN_RUN:
        return []
    return ["连续 %d 镜动作标签完全相同（%s）" % (
        run, ", ".join(sorted(current)))]


def _constraint_key(finding: dict[str, Any]) -> str:
    kind = str(finding.get("kind") or "")
    category = str(finding.get("category") or "")
    if not category and kind.startswith("clothing:"):
        category = str(finding.get("message") or "").split("：", 1)[0]
    return kind + "|" + category


def _finding_category(finding: dict[str, Any]) -> str:
    kind = str(finding.get("kind") or "")
    category = str(finding.get("category") or "")
    if not category and kind.startswith("clothing:"):
        match = re.match(r"\s*([^：:]+)[：:]", str(finding.get("message") or ""))
        category = match.group(1) if match else ""
    return category


def _finding_entry(finding: dict[str, Any], status: str) -> dict[str, Any]:
    entry = dict(finding)
    entry["status"] = status
    entry["constraint"] = _constraint_key(entry)
    return entry


def _base_kind(kind: str) -> str:
    return kind.split(":", 1)[-1]


def _finding_matches(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _constraint_key(a) == _constraint_key(b):
        return True
    kind_a = str(a.get("kind") or "")
    kind_b = str(b.get("kind") or "")
    base_a = _base_kind(kind_a)
    base_b = _base_kind(kind_b)
    if base_a != base_b or not base_a:
        return False
    cat_a = _finding_category(a)
    cat_b = _finding_category(b)
    if cat_a or cat_b:
        return cat_a == cat_b
    tags_a = {x.strip().lower() for x in str(a.get("tags") or "").split(",") if x.strip()}
    tags_b = {x.strip().lower() for x in str(b.get("tags") or "").split(",") if x.strip()}
    return bool(tags_a & tags_b)


def _sync_constraints(constraints: dict[str, dict[str, Any]],
                      findings: list[dict[str, Any]]) -> None:
    for finding in findings:
        match = next((entry for entry in constraints.values()
                      if _finding_matches(entry, finding)), None)
        if match is None:
            constraints[_constraint_key(finding)] = _finding_entry(finding, "open")
        else:
            update = _finding_entry(finding, "open")
            update["constraint"] = match.get("constraint") or _constraint_key(finding)
            constraints[str(update["constraint"])] = update
    for entry in list(constraints.values()):
        if not any(_finding_matches(entry, finding) for finding in findings):
            key = str(entry.get("constraint") or _constraint_key(entry))
            constraints[key] = dict(entry)
            constraints[key]["status"] = "resolved"


def _instruction_findings(constraints: dict[str, dict[str, Any]]
                          ) -> list[dict[str, Any]]:
    return [dict(entry) for entry in constraints.values()
            if entry.get("status") in ("open", "resolved")]


def _merge_shot(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in update.items():
        if key != "id":
            merged[key] = value
    return merged


def _tag_conversion_messages(script: dict[str, str],
                             accepted: list[dict[str, str]],
                             premise: str,
                             setting: str,
                             strip_appearance: bool,
                         style_positive: str,
                         constraints: list[dict[str, Any]]):
    from .storyboard import build_tag_messages

    messages = build_tag_messages(
        [script], style_positive, setting,
        strip_appearance=strip_appearance,
        phase=str(script.get("phase") or ""),
        cast_hint=str(script.get("cast") or ""))
    messages = list(messages)
    messages[-1] = dict(messages[-1])
    context_lines = []
    if accepted:
        context_lines.append(
            "上一镜已通过的英文 prompt（本镜服装必须从该状态连续推进，"
            "不得无理由复穿、跳变或新增衣物）：")
        context_lines.append(accepted[-1].get("prompt") or "")
    ledger = clothing_repair_plan(accepted, premise).get("ledger", {})
    if ledger:
        context_lines.append("截至目前的服装台账：" + json.dumps(
            ledger, ensure_ascii=False))
    if context_lines:
        messages[-1]["content"] = (
            messages[-1]["content"] + "\n" + "\n".join(context_lines))
    if constraints:
        lines = ["\n该镜标签必须同时满足以下确定性约束："]
        for finding in constraints:
            label = {
                "open": "必须修正",
                "resolved": "已解决，不得回退",
            }.get(str(finding.get("status") or ""), "必须满足")
            message = str(finding.get("message") or finding.get("kind") or "")
            correct = str(finding.get("correct") or finding.get("kind") or "")
            lines.append("- 状态：%s；问题：%s；正确写法：%s" % (
                label, message, correct))
            if finding.get("tags"):
                lines.append("  必须删除：%s" % finding["tags"])
            if finding.get("keep"):
                lines.append("  必须保留：%s" % finding["keep"])
        lines.append("请一次同时满足全部约束，只返回这一镜修正后的完整英文 prompt。")
        messages[-1]["content"] += "\n".join(lines)
    return messages


def _convert_one_shot(client: Any, model: str, *,
                      script: dict[str, str],
                      accepted: list[dict[str, str]],
                      premise: str,
                      setting: str,
                      strip_appearance: bool,
                      style_positive: str,
                      shot_number: int,
                      total: int,
                      timeout: float,
                      log: LogFn,
                      seed_findings: list[dict[str, Any]] | None = None
) -> tuple[dict[str, Any], list[dict[str, str]], bool]:
    active_constraints: dict[str, dict[str, Any]] = {}
    if seed_findings:
        _sync_constraints(active_constraints, seed_findings)
    current = dict(script)
    for attempt in range(MAX_ATTEMPTS):
        messages = _tag_conversion_messages(
            script, accepted, premise, setting, strip_appearance,
            style_positive, _instruction_findings(active_constraints))
        raw = client.chat_json(
            model, messages,
            schema={"type": "object", "properties": {
                "shots": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "prompt": {"type": "string"},
                        "negative": {"type": "string"},
                    },
                    "required": ["id", "prompt", "negative"]}}},
                "required": ["shots"]},
            temperature=0.5,
            num_predict=3072,
            num_ctx=32768,
            timeout=timeout,
            retries=1,
        )
        items = _extract_shots(raw)
        item = _find_item(items, "%02d" % shot_number, 0)
        if item is None:
            empty_finding = {
                "kind": "empty",
                "message": "没有返回第%d镜" % shot_number,
                "correct": "返回第%d镜完整 prompt" % shot_number,
                "tags": "", "keep": ""}
            _sync_constraints(active_constraints, [empty_finding])
            continue
        from .storyboard import normalize_tagged

        candidate = normalize_tagged({"shots": [item]}, [script])[0]
        current = _merge_shot(current, candidate)
        findings = _shot_findings(
            accepted, candidate, premise,
            is_last=(shot_number >= total))
        _sync_constraints(active_constraints, findings)
        _emit("stage.tag_verify", {
            "id": candidate.get("id"),
            "attempt": attempt + 1,
            "findings": findings,
            "constraints": _instruction_findings(active_constraints),
            "shot": candidate,
        })
        if not findings:
            current["ready"] = True
            current["findings"] = []
            current["repair_constraints"] = list(active_constraints.values())
            return current, [], True
        log("提示词第%d镜第%d次未通过，告知正确写法：%s" % (
            shot_number, attempt + 1,
            "；".join(f["kind"] for f in findings)))
    final_findings = [dict(entry) for entry in active_constraints.values()
                      if entry.get("status") == "open"]
    current["ready"] = False
    current["findings"] = final_findings
    current["repair_constraints"] = list(active_constraints.values())
    return current, final_findings, False


def _convert_tags(client: Any, model: str,
                  premise: str, total: int, *,
                  setting: str, strip_appearance: bool,
                  scripts: list[dict[str, str]],
                  style_positive: str,
                  timeout: float, log: LogFn) -> list[dict[str, str]]:
    """Stage 3: convert each locked script to tags and verify immediately."""
    result: list[dict[str, str]] = []
    unresolved: list[str] = []
    for index, script in enumerate(scripts):
        shot_number = index + 1
        accepted, findings, passed = _convert_one_shot(
            client, model,
            script=script,
            accepted=result,
            premise=premise,
            setting=setting,
            strip_appearance=strip_appearance,
            style_positive=style_positive,
            shot_number=shot_number,
            total=total,
            timeout=timeout,
            log=log)
        if not passed:
            unresolved.append(
                "shot %02d: %s" % (
                    shot_number,
                    "；".join(f["message"] for f in findings)))
        result.append(accepted)
    _emit("stage.tags_done", {"shots": result, "unresolved": unresolved})
    if unresolved:
        log("警告：%d 镜未通过确定性校验，已标记未就绪；仍可渲染或单独修复。" %
            len(unresolved))
        for item in unresolved:
            log("  未就绪 · " + item)
    else:
        log("全部 %d 镜通过确定性校验，分镜就绪。" % total)
    return result


def revalidate_tagged_shots(shots: list[dict[str, Any]],
                            premise: str) -> list[dict[str, Any]]:
    result = [dict(shot) for shot in shots]
    for index, shot in enumerate(result):
        findings = _shot_findings(
            result[:index], shot, premise,
            is_last=(index >= len(result) - 1))
        result[index]["ready"] = not findings
        result[index]["findings"] = findings
    _emit("stage.tags_revalidated", result)
    return result


def repair_tagged_shots(client: Any, model: str,
                        shots: list[dict[str, Any]],
                        premise: str, *,
                        setting: str = "",
                        strip_appearance: bool = False,
                        style_positive: str = "",
                        timeout: float = 600.0,
                        log: LogFn | None = None) -> list[dict[str, Any]]:
    """Repair not-ready shots individually without resending accepted shots."""
    out = log or (lambda _msg: None)
    result = [dict(shot) for shot in shots]
    repaired = 0
    for index, shot in enumerate(result):
        if shot_is_ready(shot):
            continue
        shot_number = index + 1
        fixed, findings, passed = _convert_one_shot(
            client, model,
            script=shot,
            accepted=result[:index],
            premise=premise,
            setting=setting,
            strip_appearance=strip_appearance,
            style_positive=style_positive,
            shot_number=shot_number,
            total=len(result),
            timeout=timeout,
            log=out,
            seed_findings=shot.get("findings"))
        result[index] = _merge_shot(shot, fixed)
        if passed:
            repaired += 1
        else:
            result[index]["ready"] = False
            result[index]["findings"] = findings
    _emit("stage.tags_repaired", {"shots": result, "repaired": repaired})
    if repaired:
        out("已修复 %d 个未就绪镜头。" % repaired)
    remaining = [str(shot.get("id") or "") for shot in result if not shot_is_ready(shot)]
    if remaining:
        out("仍未通过：%s" % ", ".join(remaining))
    else:
        out("全部分镜已就绪。")
    return result


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

def run_waterfall(client: Any,
                  premise: str,
                  total: int,
                  *,
                  generation_model_name: str,
                  review_model_name: str,
                  tag_model_name: str,
                  setting: str = "",
                  strip_appearance: bool = False,
                  style_positive: str = "",
                  timeout: float = 600.0,
                  log: LogFn | None = None) -> list[dict[str, str]]:
    """Run the three-stage waterfall and return ready-tagged shots."""
    out = log or (lambda _msg: None)

    log_prefix = "阶段1/3 大纲"
    out("%s：规划镜头蓝图…" % log_prefix)
    milestones = _ask_blueprint(
        client, review_model_name, premise, total,
        timeout=timeout, log=out)

    out("阶段1/3 大纲：按蓝图逐镜写大纲…")
    outline = _plan_outline(
        client, generation_model_name, premise, total,
        setting=setting, strip_appearance=strip_appearance,
        milestones=milestones, timeout=timeout, log=out)

    out("阶段2/3 分镜脚本：逐镜写脚本并锁定…")
    scripts = _write_scripts(
        client, generation_model_name, premise, total,
        setting=setting, strip_appearance=strip_appearance,
        outline=outline, milestones=milestones,
        timeout=timeout, log=out)

    out("阶段3/3 提示词转换：逐镜转换并立即校验…")
    shots = _convert_tags(
        client, tag_model_name, premise, total,
        setting=setting, strip_appearance=strip_appearance,
        scripts=scripts, style_positive=style_positive,
        timeout=timeout, log=out)
    return shots
