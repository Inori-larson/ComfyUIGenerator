"""Single-image prompt generation (natural language -> one Danbooru prompt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.mechanical import normalize_prompt_text
from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.storyboard import (
    BOORU_WORKFLOW, PROMPT_COVERAGE, clothing_from_premise, raw_prompt,
)
from comfyui_generator.core.tags import dedupe_tags

SINGLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "negative": {"type": "string"},
        "cast": {"type": "string"},
        "present_characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "gender": {"type": "string"},
                },
            },
        },
        "clothing_state": {"type": "string"},
    },
    "required": ["prompt"],
}

SINGLE_SYSTEM_PROMPT = (
    "你是 Danbooru 标签工程师。请把用户的中文画面描述转换成一组英文 Danbooru 标签。\n"
    "要求：\n"
    "1. 只输出 JSON：{\"prompt\": \"...\", \"negative\": \"...\"}。\n"
    "2. prompt 只能包含用英文逗号分隔的 Danbooru 标签，不写整句英文。\n"
    "3. 建议 40-75 个标签，复杂场景可到 75-100，最多 120 个；只为画面里确实存在的内容写标签。\n"
    "4. " + PROMPT_COVERAGE + "当前画面相关的维度尽量覆盖，缺少的补齐；被衣物遮住的部位不要写。"
    + BOORU_WORKFLOW +
    "镜头/构图只写抽象运镜词（full body, close-up, from below, dutch angle, depth of field），"
    "禁止 camera, holding camera, camera phone, lens, tripod, photographer 等会把实体相机画进画面的标签；"
    "看向镜头统一写 looking at viewer，不写 looking at camera。\n"
    "5. 服装和裸露状态按描述如实写清；不要添加描述里没有的裸露、性行为或角色。\n"
    "5b. 服装只能使用描述里给出的初始服装，禁止新增列表之外的衣物、鞋履、配饰，"
    "也不允许漏写或删除任何一件已列出的单品（包括鞋子、袜子、饰品）；"
    "颜色、材质、款式必须与描述完全一致，不能改色或替换成同类其他款式。\n"
    "5c. 服装有层级（外衣盖住内衣、连裤袜盖住内裤）：外层仍穿着且没有打开、掀起、"
    "滑落或脱掉时，被遮住的内衣、内裤和皮肤不要写进标签；只有外层明确打开、掀起、"
    "滑落或脱掉之后，才写露出的内层衣物和部位。只写画面里实际可见的衣物层级。\n"
    "6. 如果启用了角色 LoRA，不要生成角色发色、瞳色、发型、脸、身体特征或角色名；"
    "这些交给 LoRA 和激活标签，只写剧情画面。\n"
    "7. 同时返回结构化 cast：没有男性时写 1girl solo；有男性参与时写 1girl 1boy；"
    "每个画面最多一个男性，并删除 solo、male、couple 等会造成人数歧义的词。"
    "男主不写外貌；只有明确要求无脸或脸出框时才写 faceless male、male head out of frame。\n"
    "8. 同时返回 clothing_state：用英文 Booru 状态标签、逗号分隔，只写当前半脱/破损/脱下状态；"
    "没有这类状态时返回 none；不要把完整基础服装写进去。\n"
    "只输出 JSON，不要解释、评论或免责声明。"
)

FRAMING_TAGS = {
    "auto": "",
    "full_body": "full body",
    "upper_body": "upper body, medium shot",
    "close_up": "close-up",
    "portrait": "portrait, face focus",
    "wide": "wide shot",
}


def sanitize_single_prompt(prompt: str, cast: str = "",
                           clothing_state: str = "") -> str:
    return normalize_prompt_text(str(prompt or ""))


@dataclass
class SingleOptions:
    model: str
    framing: str = "auto"
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    strip_appearance: bool = False
    temperature: float = 0.8
    num_predict: int = 8192
    num_ctx: int = 32768
    keep_alive: str = "5m"
    log: Callable[[str], None] = field(default=lambda _msg: None)


def build_single_messages(description: str, options: SingleOptions) -> list[dict[str, str]]:
    framing = FRAMING_TAGS.get(options.framing, "")
    character_tags = dedupe_tags(options.character_tags)
    style_positive = dedupe_tags(options.style_positive)
    user: list[str] = []
    if options.strip_appearance:
        user.append("已启用角色 LoRA：不要生成角色外貌、发色、瞳色、发型、脸、身体特征或角色名；"
                    "这些由 LoRA 和激活标签负责。")
    user += [
        "描述：%s" % description,
    ]
    if character_tags and character_tags not in description:
        user.append("角色：%s" % character_tags)
    if style_positive:
        user.append("画风：%s" % style_positive)
    clothing = clothing_from_premise(description)
    if clothing:
        user.append(
            "初始服装（必须逐字保留，不得新增、删除或改色）：%s\n"
            "服装标签要写全『颜色+款式』，鞋履、袜子等已列出的单品也必须写进 prompt，"
            "不能漏掉。" % clothing)
    if framing:
        user.append("构图偏好：%s" % framing)
    if options.setting.strip():
        user.append("额外美术方向：%s" % options.setting.strip())
    user.append("请为描述生成 Danbooru 标签，写清当前服装/裸露状态和可见身体部位；"
                "建议 40-75 个，复杂场景可到 75-100 个，最多 120 个。")
    return [
        {"role": "system", "content": SINGLE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user)},
    ]


def generate_single_prompt(client: OllamaClient, description: str,
                           options: SingleOptions) -> dict[str, str]:
    raw = client.chat_json(
        options.model,
        build_single_messages(description, options),
        schema=SINGLE_SCHEMA,
        temperature=options.temperature,
        num_predict=options.num_predict,
        num_ctx=options.num_ctx,
        keep_alive=options.keep_alive,
    )
    prompt = sanitize_single_prompt(
        raw_prompt(raw.get("prompt") or raw.get("tags") or ""),
        cast=str(raw.get("cast") or ""),
        clothing_state=str(raw.get("clothing_state") or ""))
    if not prompt:
        raise ValueError("Model returned an empty prompt.")
    negative = raw_prompt(raw.get("negative") or "")
    options.log("Single prompt ready (%d tags)" % len([t for t in prompt.split(",") if t.strip()]))
    return {"prompt": prompt, "negative": negative}
