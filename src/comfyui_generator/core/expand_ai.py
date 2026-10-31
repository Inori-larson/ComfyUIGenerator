from __future__ import annotations

import json
from typing import Any, Callable

from comfyui_generator.core.expand import _is_pose_tag, apply_expansion_delta

_DEPTH_WORDS = ("deep penetration", "shallow penetration", "deeper penetration")
_FLUID_WORDS = ("cum", "semen", "creampie", "ejaculat", "pussy juice")
_ACTION_WORDS = (
    "penetrat", "thrust", "hips", "riding", "straddl", "grinding",
    "leg", "legs", "thigh", "thighs", "knee", "knees", "foot", "feet",
    "toe", "toes", "hand", "hands", "arm", "arms", "elbow", "wrist",
    "finger", "fingers", "grab", "gripping", "holding", "spread", "bend",
    "bending", "lean", "arching", "arching back", "lifting", "moving",
    "pose", "poses", "sitting", "standing", "lying", "kneeling",
    "walking", "running", "turning", "reaching", "pulling", "pushing",
    "pressing", "straddle",
)
_EXPRESSION_WORDS = (
    "eye", "eyes", "mouth", "lip", "lips", "tongue", "blush", "smile",
    "tear", "tears", "moan", "breath", "breathing", "sweat", "trembl",
)
_CLOTHING_WORDS = (
    "shirt", "blouse", "jacket", "coat", "sweater", "bra", "dress",
    "uniform", "hoodie", "vest", "robe", "kimono", "qipao", "camisole",
    "panties", "pantyhose", "stockings", "thighhighs", "skirt", "pants",
    "jeans", "shorts", "clothes", "clothing", "lingerie", "underwear",
)

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
    "你是二次元 Danbooru 提示词扩展器。根据每一镜的当前 prompt、脚本和下一镜约束，"
    "生成连续的单镜细节变化。只输出 JSON，不解释。\n"
    "每步输出一个增量，不是完整 prompt：\n"
    "- remove：从当前标签里删掉的状态/细节标签；\n"
    "- add：新增的状态/细节标签。\n"
    "硬规则：\n"
    "1. 不要删除 cast、角色身份、发色瞳色、场景、家具、光线、镜头、构图和主要动作/姿势。\n"
    "2. 每步至少改动 4 个标签（remove + add 总数），并形成明显递进；"
    "第一步偏前段，最后一步偏后段或余韵。\n"
    "3. 每步至少覆盖两个不同维度，不要只改表情：表情/视线、动作幅度/深度、"
    "手和身体位置、环境互动、衣物半脱/破损、体液/余韵。"
    "每一步都必须改动至少一个动作/四肢/身体标签（手、手臂、腿、大腿、臀、脚、"
    "插入深度、姿势），不能只换眼神和嘴。\n"
    "4. 当前 prompt 已有后段状态（深插、高潮、体液、余韵）时，前几步应先移除这些状态，"
    "后几步再恢复或继续推进；不要每一步都保留同一个深度和同一个表情。\n"
    "5. 下一镜只作为上限约束：下一镜还穿着的衣服不能提前脱；下一镜没有的裸露、插入、体液、"
    "撕衣不能提前出现；下一镜已经允许的才可以出现。下一镜为 null 时没有该限制。\n"
    "6. 不要换场景、不要换人、不要换主要动作。\n"
    "7. 一旦当前 prompt 已有 cum/semen/体液或 torn/ripped 破损衣物，后续步骤不能删除，"
    "只能增加、累积或加重。\n"
    "8. 不要输出质量词或解释，只输出 JSON，不要 markdown。\n"
)

USER_HEADER = (
    "为每镜生成指定数量的增量步骤。输出格式："
    "{\"expansions\":[{\"id\":\"01\",\"steps\":[{\"remove\":[\"...\"],\"add\":[\"...\"]}]}]}。"
    "每个 id 的 steps 数量必须等于 expansion_count；"
    "每个 step 的 remove+add 至少 4 个标签，步骤之间不能重复；"
    "不要只替换表情，动作、四肢小动作、深度、体液和衣物状态也要形成递进；"
    "体液和破损衣物只能增加，不能删除。\n"
)


def _shot_payload(shot: dict[str, Any], next_shot: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        "id": str(shot.get("id") or ""),
        "prompt": str(shot.get("prompt") or ""),
        "script": str(shot.get("script") or shot.get("outline") or ""),
        "cast": str(shot.get("cast") or ""),
        "scene": str(shot.get("scene") or ""),
        "clothing": str(shot.get("clothing") or ""),
        "clothing_details": shot.get("clothing_details") or {},
        "next": None,
    }
    if next_shot:
        payload["next"] = {
            "prompt": str(next_shot.get("prompt") or ""),
            "script": str(next_shot.get("script") or next_shot.get("outline") or ""),
            "cast": str(next_shot.get("cast") or ""),
            "scene": str(next_shot.get("scene") or ""),
            "clothing": str(next_shot.get("clothing") or ""),
            "clothing_details": next_shot.get("clothing_details") or {},
        }
    return payload


def build_expansion_messages(shots: list[dict[str, Any]], count: int,
                             start: int = 0) -> list[dict[str, str]]:
    items = []
    for index, shot in enumerate(shots):
        nxt = shots[index + 1] if index + 1 < len(shots) else None
        items.append(_shot_payload(shot, nxt))
    user = USER_HEADER + json.dumps({
        "expansion_count": max(1, int(count)),
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


def _pose_tags(keys: set[str]) -> set[str]:
    return {key for key in keys if _is_pose_tag(key)}


def _categories(keys: set[str]) -> set[str]:
    categories: set[str] = set()
    for key in keys:
        low = key.lower()
        if any(word in low for word in _ACTION_WORDS):
            categories.add("action")
        if any(word in low for word in _EXPRESSION_WORDS):
            categories.add("expression")
        if any(word in low for word in _FLUID_WORDS):
            categories.add("fluid")
        if any(word in low for word in _CLOTHING_WORDS):
            categories.add("clothing")
    return categories


def _cleaned_batch(raw: Any, batch: list[dict[str, Any]],
                   count: int) -> dict[str, list[str]]:
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
        shot_id = str(shot.get("id") or "")
        prompts = cleaned.get(shot_id) or []
        if len(prompts) != count:
            return True
        base = {tag.strip().lower() for tag in
                str(shot.get("prompt") or "").split(",") if tag.strip()}
        seen: set[str] = set()
        previous_pose = _pose_tags(base)
        for index, prompt in enumerate(prompts):
            keys = {tag.strip().lower() for tag in prompt.split(",") if tag.strip()}
            if len(keys ^ base) < 4 or prompt.lower() in seen:
                return True
            changed_categories = _categories(keys ^ base)
            base_categories = _categories(base)
            if "action" in base_categories and "action" not in changed_categories:
                return True
            if len(base_categories) >= 2 and len(changed_categories) < 2:
                return True
            pose = _pose_tags(keys)
            if pose == previous_pose:
                return True
            previous_pose = pose
            if index + 1 < len(prompts):
                if any(word in base and word in keys for word in _DEPTH_WORDS):
                    return True
                if any(word in base and word in keys for word in _FLUID_WORDS):
                    return True
            seen.add(prompt.lower())
    return False


def generate_expansions(client: Any, model: str, shots: list[dict[str, Any]],
                        count: int, *, chunk: int = 6,
                        log: Callable[[str], None] | None = None,
                        **kwargs: Any) -> dict[str, list[str]]:
    count = max(1, int(count))
    result: dict[str, list[str]] = {}
    chunk = max(1, int(chunk))
    for offset in range(0, len(shots), chunk):
        batch = shots[offset:offset + chunk]
        messages = build_expansion_messages(batch, count, start=offset)
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
            cleaned = _cleaned_batch(raw, batch, count)
            if not _needs_retry(cleaned, batch, count):
                break
            if attempt >= 2:
                if log:
                    log("AI expansion still similar after retries")
                break
            if log:
                log("AI expansion too similar; retrying strict pass")
            convo = messages + [
                {"role": "assistant", "content": json.dumps(
                    raw, ensure_ascii=False)},
                {"role": "user", "content": (
                    "The previous deltas were too small or repeated. Rewrite "
                    "the whole JSON. Each step must contain at least 4 total "
                    "remove+add tags, must not remove scene/character/main "
                    "action anchors, and must form a clear progression. "
                    "Every step must change at least one action/limb/body "
                    "tag, not only expression. Never remove cum/semen/fluid "
                    "or torn/ripped clothing once present. Return JSON only.")},
            ]
        result.update(cleaned)
    return result
