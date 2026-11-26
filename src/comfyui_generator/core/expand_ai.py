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
    "你是二次元 Danbooru 提示词扩展器。根据当前 prompt、脚本、前后镜头约束和用户规则，"
    "为每一镜生成连续的细节变化增量。只输出 JSON，不解释。\n"
    "增量格式：remove 是从当前标签删除的状态/细节；add 是新增的状态/细节；"
    "不要输出完整 prompt，也不要输出质量词。\n"
    "连续性：保持 cast、角色身份、场景、机位、景别、构图与当前镜头的主要状态一致；"
    "下一镜只作为上限，不要把下一镜才发生的状态提前。具体改多少个标签、改哪些维度、"
    "递进幅度多大，由你按剧情和【用户规则】自行判断。\n"
    "不引入需要第二个可见人物才能完成的标签，除非当前镜头确有第二人。\n"
)

USER_HEADER = (
    "为每镜生成指定数量的增量步骤。输出格式："
    "{\"expansions\":[{\"id\":\"01\",\"steps\":[{\"remove\":[\"...\"],\"add\":[\"...\"]}]}]}。"
    "每个 id 的 steps 数量必须等于 state_count；步骤之间形成连贯递进但不逐字重复；"
    "保持机位、景别、构图、场景和当前镜头的主要状态；下一镜未发生的状态不要提前出现。\n"
)


def _shot_payload(shot: dict[str, Any], next_shot: dict[str, Any] | None,
                  prev_shot: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "id": str(shot.get("id") or ""),
        "prompt": str(shot.get("prompt") or ""),
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
