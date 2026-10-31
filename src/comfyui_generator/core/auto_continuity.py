"""LLM extraction of a continuity bible and per-shot ledgers."""

from __future__ import annotations

import json
from typing import Any, Callable

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "character": {"type": "string"},
        "scene": {"type": "string"},
        "negative": {"type": "string"},
        "ledger": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "scene": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["id", "scene", "state"],
            },
        },
    },
    "required": ["character", "scene", "negative", "ledger"],
}

SYSTEM = (
    "你是连续剧情连贯性编辑。根据剧情和分镜提取“角色锚点 / 场景锚点 / "
    "连续性台账”，只输出 JSON，不要解释。\n"
    "规则：\n"
    "1. 所有字段使用英文 Booru 标签，英文逗号分隔，不要整句英文，不要中文。\n"
    "2. character 只写全片不变的外貌和身体标记：发色、发型、瞳色、体型、"
    "纹身、疤痕、固定饰品；不要写动作、表情、服装或临时状态。\n"
    "3. scene 写整体主场景；如果剧情换场景，在 ledger 的每镜 scene 里写该镜场景。\n"
    "4. ledger 必须覆盖输入中的每一个镜头，id 必须与输入一致，不能增删镜头。\n"
    "5. ledger.state 写该镜结束时的累积状态：当前服装/裸露、破洞、伤势、"
    "体液、汗水、情绪、NSFW 进度。只能使用输入里已经出现或明确暗示的标签，"
    "禁止凭空增加内衣、伤口、体液或角色。\n"
    "6. 状态不可逆：已经脱掉的衣服、破洞、伤势、体液不能在后一镜恢复或消失；"
    "后续镜头只能增加或保持。\n"
    "7. negative 写最需要防止的跨镜变化，例如 different hairstyle, "
    "different location, extra characters，不要重复普通画质负面词。\n"
    "8. 没有把握时保持简短，不要编造。\n"
    "只输出：{\"character\":\"...\",\"scene\":\"...\",\"negative\":\"...\","
    "\"ledger\":[{\"id\":\"01\",\"scene\":\"...\",\"state\":\"...\"}]}"
)


def _shot_payload(shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(shot.get("id") or ""),
        "prompt": str(shot.get("prompt") or ""),
        "script": str(shot.get("script") or shot.get("outline") or ""),
        "cast": str(shot.get("cast") or ""),
        "scene": str(shot.get("scene") or ""),
        "clothing": str(shot.get("clothing") or ""),
        "phase": str(shot.get("phase") or ""),
        "character_states": shot.get("character_states") or {},
        "clothing_details": shot.get("clothing_details") or {},
    }


def build_continuity_messages(premise: str, shots: list[dict[str, Any]],
                              character_tags: str = "") -> list[dict[str, str]]:
    payload = {
        "premise": str(premise or ""),
        "character_tags": str(character_tags or ""),
        "shots": [_shot_payload(shot) for shot in shots],
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _clean(data: Any, shots: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("连贯性模型没有返回 JSON 对象")
    ledger_raw = data.get("ledger")
    if not isinstance(ledger_raw, list):
        ledger_raw = []
    by_id = {
        str(item.get("id") or "").strip(): item
        for item in ledger_raw if isinstance(item, dict)
    }
    result = []
    for index, shot in enumerate(shots):
        shot_id = str(shot.get("id") or "%02d" % (index + 1))
        item = by_id.get(shot_id)
        if item is None and index < len(ledger_raw):
            candidate = ledger_raw[index]
            if (isinstance(candidate, dict)
                    and not str(candidate.get("id") or "").strip()):
                item = candidate
        item = item if isinstance(item, dict) else {}
        result.append({
            "id": shot_id,
            "scene": str(item.get("scene") or "").strip(),
            "state": str(item.get("state") or "").strip(),
        })
    return {
        "character": str(data.get("character") or "").strip(),
        "scene": str(data.get("scene") or "").strip(),
        "negative": str(data.get("negative") or "").strip(),
        "ledger": result,
    }


def extract_continuity(client: Any, model: str, premise: str,
                       shots: list[dict[str, Any]],
                       character_tags: str = "",
                       log: Callable[[str], None] | None = None,
                       timeout: float = 300.0) -> dict[str, Any]:
    if log:
        log("正在提取角色/场景锚点与每镜连续性台账...")
    raw = client.chat_json(
        model,
        build_continuity_messages(premise, shots, character_tags),
        schema=SCHEMA,
        temperature=0.25,
        num_predict=6144,
        num_ctx=32768,
        timeout=timeout,
        retries=1,
    )
    result = _clean(raw, shots)
    if (not result["character"] and not result["scene"]
            and not any(item["state"] for item in result["ledger"])):
        raise ValueError("模型返回的连贯性数据为空")
    if log:
        log("连贯性台账已生成：%d 镜" % len(result["ledger"]))
    return result
