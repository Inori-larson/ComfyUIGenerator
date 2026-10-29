"""Use the local Ollama model to translate English tags for display only."""

from __future__ import annotations

from typing import Any

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.tag_cache import load_tag_cache, update_tag_cache
from comfyui_generator.core.tags import limit_tags

TRANSLATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["translations"],
}

TRANSLATE_SYSTEM = (
    "你是动漫图片提示词翻译器。把用户给出的每条英文 Danbooru 标签提示词翻译成简体中文，"
    "保留标签顺序和原意，用中文顿号或逗号分隔。不要增删标签，不要解释，不要改写内容。"
    "只输出 JSON：{\"translations\": [\"第1条中文翻译\", \"第2条中文翻译\"]}，"
    "数组长度和顺序必须与输入一致。"
)

TO_TAGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["prompts"],
}

TO_TAGS_SYSTEM = (
    "你是动漫图片提示词转换器。把用户给出的中文提示词转换成完整的英文 Danbooru 标签列表。"
    "保留原意，不要压缩成单个标签；至少输出人物数量、服装/裸露状态、可见身体部位、姿势、动作、表情、地点、镜头、构图、光线等所有关键信息。"
    "通常输出 20-50 个英文标签，复杂场景可到 70 个，用英文逗号分隔，最多 120 个标签。"
    "示例：一个女孩，单人，在公园长椅上微笑 -> 1girl, solo, sitting, park, bench, smile。"
    "不要解释。只输出 JSON：{\"prompts\": [\"第1条英文标签\", \"第2条英文标签\"]}，"
    "数组长度和顺序必须与输入一致。"
)


def build_messages(prompts: list[str]) -> list[dict[str, str]]:
    lines = ["请逐条翻译以下 %d 条提示词：" % len(prompts)]
    lines += ["%d. %s" % (index + 1, prompt) for index, prompt in enumerate(prompts)]
    return [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def translate_prompts(client: OllamaClient, model: str, prompts: list[str],
                      temperature: float = 0.2, keep_alive: str = "5m",
                      batch_size: int = 4) -> list[str]:
    result: list[str] = []
    for start in range(0, len(prompts), max(1, batch_size)):
        batch = prompts[start:start + max(1, batch_size)]
        raw = client.chat_json(
            model,
            build_messages(batch),
            schema=TRANSLATE_SCHEMA,
            temperature=temperature,
            num_predict=8192,
            num_ctx=32768,
            keep_alive=keep_alive,
        )
        items = raw.get("translations") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            items = [raw.get("translation", "")] if isinstance(raw, dict) else []
        for index in range(len(batch)):
            value = items[index] if index < len(items) else ""
            result.append(str(value or "").strip())
    return result


def build_to_tags_messages(prompts: list[str]) -> list[dict[str, str]]:
    lines = ["请逐条转换以下 %d 条中文提示词：" % len(prompts)]
    lines += ["%d. %s" % (index + 1, prompt) for index, prompt in enumerate(prompts)]
    return [
        {"role": "system", "content": TO_TAGS_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def translate_to_tags(client: OllamaClient, model: str, prompts: list[str],
                      temperature: float = 0.2, keep_alive: str = "5m",
                      batch_size: int = 4) -> list[str]:
    result: list[str] = []
    for start in range(0, len(prompts), max(1, batch_size)):
        batch = prompts[start:start + max(1, batch_size)]
        raw = client.chat_json(
            model,
            build_to_tags_messages(batch),
            schema=TO_TAGS_SCHEMA,
            temperature=temperature,
            num_predict=8192,
            num_ctx=32768,
            keep_alive=keep_alive,
        )
        items = raw.get("prompts") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            items = [raw.get("prompt", "")] if isinstance(raw, dict) else []
        for index in range(len(batch)):
            value = items[index] if index < len(items) else ""
            result.append(limit_tags(str(value or "").strip()))
    return result


def translate_tag_list(client: OllamaClient, model: str, tags: list[str],
                       cache_path: str, batch_size: int = 50) -> dict[str, str]:
    unique = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    cache = load_tag_cache(cache_path)
    missing = [tag for tag in unique if tag not in cache]
    for start in range(0, len(missing), max(1, batch_size)):
        chunk = missing[start:start + max(1, batch_size)]
        values = translate_prompts(client, model, chunk, batch_size=len(chunk))
        pairs = {tag: value.replace("，", "、").replace(",", "、")
                 for tag, value in zip(chunk, values) if value}
        if pairs:
            cache = update_tag_cache(cache_path, pairs)
    return {tag: cache.get(tag, tag) for tag in unique}
