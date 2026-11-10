from __future__ import annotations

import json
from typing import Any, Callable

from comfyui_generator.core.expand import apply_expansion_delta

EXPANSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "expansions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "remove": {"type": "array", "items": {"type": "string"}},
                                "add": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["remove", "add"],
                        },
                    },
                },
                "required": ["id", "steps"],
            },
        }
    },
    "required": ["expansions"],
}

SYSTEM = (
    "0. 如果 mode=sequence：输出 N+1 个状态，第 1 个是起始状态，后续按时间推进到输入 prompt 的最终状态；每步仍然是增量。\n"
    "0b. 如果输入里 prev 已经含 cum/体液、penetration 或 pullout，sequence 第一步不能清除这些状态，必须从 prev 的状态继续推进。\n"
    "你是二次元 Danbooru 提示词扩展器。根据每一镜的当前 prompt、脚本和下一镜约束，"
    "生成连续的单镜细节变化。只输出 JSON，不解释。\n"
    "每步输出一个增量，不是完整 prompt：\n"
    "- remove：从当前标签里删掉的状态/细节标签；\n"
    "- add：新增的状态/细节标签。\n"
    "硬规则：\n"
    "1. 必须保留 cast、角色身份、发色瞳色、场景、家具、光线、机位、景别、构图、"
    "画面内人数和主要姿势大类（躺/坐/站/跪/趴）；"
    "在这些大框架内，允许并必须改变四肢位置、身体朝向、臀胯角度、腿部开合、"
    "手部支撑、身体弓起程度、插入角度和深度。\n"
    "2. 每步至少改动 6 个标签（remove + add 总数），并形成明显递进；"
    "第一步偏前段，最后一步偏后段或余韵。\n"
    "3. 每步至少覆盖两个不同维度，不要只改表情：表情/视线、动作幅度/深度、"
    "手和身体位置、环境互动、衣物半脱/破损、体液/余韵。"
    "每一步至少加入 2 个动作/四肢/身体标签（手、手臂、腿、大腿、臀、脚、"
    "插入深度、姿势），并且至少改变 1 个姿势/身体朝向（前倾、后仰、侧身、"
    "抬臀、跨坐、跪趴、抱腿、腿缠腰等），不能只换眼神、嘴或微小手指动作。\n"
    "4. 当前 prompt 已有后段状态（深插、高潮、体液、余韵）时，前几步应先移除这些状态，"
    "后几步再恢复或继续推进；不要每一步都保留同一个深度和同一个表情。\n"
    "5. 下一镜只作为上限约束，且对所有题材通用（性爱、战斗、日常、运动、奇幻、"
    "料理、洗浴等）：下一镜还穿着的衣服不能提前脱；下一镜没有的裸露、性行为、"
    "深插、拔出、射精、体液、伤害、血迹、武器/道具使用、场景破坏、变身/技能、"
    "死亡、新体位，都不能提前出现；下一镜已经允许的才可以出现。不要把下一镜"
    "没发生的动作、事件或状态提前塞进当前镜。下一镜为 null 时没有该限制。\n"
    "6. 不要换场景、不要换人、不要换机位/景别/构图，也不要改变主要姿势大类。"
    "原镜头是躺姿就保持躺姿，只改变腿抬起/张开/缠腰、侧身角度、抬臀、手部支撑、"
    "身体弓起和插入深度/角度；不要变成站立、走动、换房间或切镜头。"
    "仍要大胆改变四肢和身体细节，禁止五步都保持完全相同的姿势。\n"
    "6b. 如果当前镜头是 solo/单人，禁止添加需要第二个可见人物才能完成的标签："
    "拥抱、接吻、腿缠腰、手臂缠脖、手扶对方、1boy/2girls/2boys 等；"
    "否则模型容易画出第二个头或第二个人。单人动作只改变自己的四肢、重心、"
    "身体朝向、手撑位置和表情。\n"
    "7. 一旦当前 prompt 已有 cum/semen/体液或 torn/ripped 破损衣物，后续步骤不能删除，"
    "只能增加、累积或加重。\n"
    "8. 每步必须替换旧的手/手臂动作和表情：add 新手势时同时 remove 冲突的旧手势，"
    "add 新表情/视线时同时 remove 旧表情/视线，禁止只追加导致新旧标签打架。\n"
    "9. 透深度/拔出/射精程度/阴道状态必须逐步变化：用 remove 替换旧的 penetration/pullout/vagina 状态，"
    "不要把 deep penetration 和 shallow penetration 同时保留；最后一步应能出现拔出、事后或射精后的状态。\n"
    "10. 不要输出质量词或解释，只输出 JSON，不要 markdown。\n"
)

USER_HEADER = (
    "为每镜生成指定数量的增量步骤。输出格式："
    "{\"expansions\":[{\"id\":\"01\",\"steps\":[{\"remove\":[\"...\"],\"add\":[\"...\"]}]}]}。"
    "每个 id 的 steps 数量必须等于 state_count；"
    "每个 step 的 remove+add 至少 6 个标签，其中至少 2 个动作/四肢/姿势变化，"
    "并且至少 1 个姿势或身体朝向变化；步骤之间不能重复；"
    "动作变化不能超出原镜头的机位、景别、构图、场景和主要姿势大类；"
    "所有题材都要遵守下一镜上限：下一镜没有发生的动作、事件、伤害、道具、"
    "性行为、脱衣、场景变化和新体位不要提前出现；"
    "solo/单人镜头禁止添加拥抱、接吻、腿缠腰、手扶对方或第二个人的标签；"
    "不要只替换表情，动作、四肢大幅度变化、深度、体液和衣物状态也要形成递进；"
    "体液和破损衣物只能增加，不能删除。\n"
)


def _shot_payload(shot: dict[str, Any], next_shot: dict[str, Any] | None,
                  prev_shot: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "id": str(shot.get("id") or ""),
        "prompt": str(shot.get("prompt") or ""),
        "description": str(shot.get("description") or ""),
        "prev": None,
        "next": None,
    }
    if prev_shot:
        payload["prev"] = {
            "prompt": str(prev_shot.get("prompt") or ""),
        }
    if next_shot:
        payload["next"] = {
            "prompt": str(next_shot.get("prompt") or ""),
        }
    return payload


def build_expansion_messages(shots: list[dict[str, Any]], count: int,
                             start: int = 0,
                             sequence: bool = False,
                             previous_shot: dict[str, Any] | None = None) -> list[dict[str, str]]:
    items = []
    for index, shot in enumerate(shots):
        nxt = shots[index + 1] if index + 1 < len(shots) else None
        prev = shots[index - 1] if index > 0 else previous_shot
        items.append(_shot_payload(shot, nxt, prev))
    user = USER_HEADER + json.dumps({
        "mode": "sequence" if sequence else "continuation",
        "state_count": max(1, int(count)),
        "shots": items,
    }, ensure_ascii=False)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user}]


def _split_shots(data: Any) -> list[Any]:
    if isinstance(data, dict):
        items = data.get("expansions")
        if isinstance(items, list):
            return items
        items = data.get("shots")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    return []


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _cleaned_batch(raw: Any, batch: list[dict[str, Any]],
                   count: int, sequence: bool = False,
                   previous_shot: dict[str, Any] | None = None) -> dict[str, list[str]]:
    items = _split_shots(raw)
    by_id = {str(item.get("id") or ""): item for item in items
             if isinstance(item, dict)}
    result: dict[str, list[str]] = {}
    for index, shot in enumerate(batch):
        shot_id = str(shot.get("id") or "")
        item = by_id.get(shot_id)
        if item is None and index < len(items) and isinstance(items[index], dict):
            item = items[index]
        steps = item.get("steps") if isinstance(item, dict) else None
        if not isinstance(steps, list):
            continue
        next_shot = batch[index + 1] if index + 1 < len(batch) else None
        current = str(shot.get("prompt") or "")
        cleaned = []
        for step in steps[:count]:
            if not isinstance(step, dict):
                continue
            current = apply_expansion_delta(
                current, _as_list(step.get("remove")),
                _as_list(step.get("add")), shot, next_shot)
            cleaned.append(current)
        if cleaned:
            result[shot_id] = cleaned
    return result


def _needs_retry(cleaned: dict[str, list[str]], batch: list[dict[str, Any]],
                 count: int) -> bool:
    for shot in batch:
        prompts = cleaned.get(str(shot.get("id") or "")) or []
        if len(prompts) != count:
            return True
        if any(not str(prompt or "").strip() for prompt in prompts):
            return True
        if len({prompt.lower() for prompt in prompts}) != len(prompts):
            return True
    return False


def generate_expansions(client: Any, model: str, shots: list[dict[str, Any]],
                        count: int, *, chunk: int = 6,
                        sequence: bool = False,
                        log: Callable[[str], None] | None = None,
                        **kwargs: Any) -> dict[str, list[str]]:
    count = max(1, int(count))
    steps_needed = count + 1 if sequence else count
    result: dict[str, list[str]] = {}
    chunk = max(1, int(chunk))
    for offset in range(0, len(shots), chunk):
        batch = shots[offset:offset + chunk]
        previous_shot = shots[offset - 1] if offset > 0 else None
        messages = build_expansion_messages(
            batch, steps_needed, start=offset, sequence=sequence,
            previous_shot=previous_shot)
        if log:
            log("AI 扩展：%d/%d" % (offset + 1, len(shots)))
        convo = messages
        cleaned: dict[str, list[str]] = {}
        for attempt in range(3):
            raw = client.chat_json(
                model, convo, schema=EXPANSION_SCHEMA,
                temperature=0.75 if attempt == 0 else 0.95,
                num_predict=8192, num_ctx=32768,
                timeout=300.0, retries=2 if attempt == 0 else 1, **kwargs)
            cleaned = _cleaned_batch(
                raw, batch, steps_needed, sequence, previous_shot)
            if not _needs_retry(cleaned, batch, steps_needed):
                break
            if attempt >= 2:
                if log:
                    log("AI expansion still incomplete after retries")
                break
            if log:
                log("AI expansion incomplete or repeated; retrying")
            convo = messages + [
                {"role": "assistant", "content": json.dumps(
                    raw, ensure_ascii=False)},
                {"role": "user", "content": (
                    "The previous JSON was incomplete or repeated. "
                    "Rewrite the whole JSON following the original request "
                    "and the full shot context. You decide how much should "
                    "change; do not force a fixed number of tags or actions. "
                    "Keep continuity, keep the same shot context, and make "
                    "the sequence natural. Return JSON only.")},
            ]
        result.update(cleaned)
    return result
