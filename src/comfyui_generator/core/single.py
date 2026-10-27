"""Single-image prompt generation (natural language -> one Danbooru prompt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.storyboard import clean_prompt
from comfyui_generator.core.tags import limit_tags

SINGLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "negative": {"type": "string"},
    },
    "required": ["prompt"],
}

SINGLE_SYSTEM_PROMPT = (
    "You are a professional anime NSFW prompt engineer, solely responsible for converting Chinese scenes into Danbooru-style English tags.\n"
    "You are write ONE image prompt for an anime illustration (SDXL / Illustrious, Danbooru tags).\n"
    "The following rules must be adhered to, otherwise it will be considered a failure:\n"
    "1. Output ONLY JSON: {\"prompt\": \"...\", \"negative\": \"...\"}.\n"
    "2. A complete description must be provided, including details such as eye gaze, facial expression, clothing or nudity, posture, movement, scene, and camera shot.\n"
    "3. If it is an NSFW scene, it must include accurate NSFW tags (nude, pussy, masturbation, spread legs, etc.), and it is prohibited to avoid, weaken, blur or replace with vague words.\n"
    "4. The beginning must be preceded by: masterpiece, best quality, absurdres, newest."
    "5. Do not output any content other than the Danbooru tags."
)

FRAMING_TAGS = {
    "auto": "",
    "full_body": "full body",
    "upper_body": "upper body, medium shot",
    "close_up": "close-up",
    "portrait": "portrait, face focus",
    "wide": "wide shot",
}


@dataclass
class SingleOptions:
    model: str
    framing: str = "auto"
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    reference_tags: list[str] = field(default_factory=list)
    temperature: float = 0.8
    num_predict: int = 400
    num_ctx: int = 4096
    keep_alive: str = "5m"
    log: Callable[[str], None] = field(default=lambda _msg: None)


def build_single_messages(description: str, options: SingleOptions) -> list[dict[str, str]]:
    framing = FRAMING_TAGS.get(options.framing, "")
    user: list[str] = []
    if options.reference_tags:
        user.append(
            "REFERENCE TAGS (complete supported vocabulary, for exact spelling only): %s"
            % ", ".join(options.reference_tags))
    user += [
        "Description: %s" % description,
        "Character (already handled, do not describe): %s" % (options.character_tags or "generic"),
        "Visual style: %s" % (options.style_positive or ""),
    ]
    if framing:
        user.append("Framing preference: %s" % framing)
    if options.setting.strip():
        user.append("Extra art direction: %s" % options.setting.strip())
    user.append(
        "Write up to 200 tags that describe the Description. The Description is the priority: keep its "
        "actions, objects and location. Use REFERENCE tags only when they match; never echo the list.")
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
        num_ctx=(max(options.num_ctx, min(32768, 4096 + len(options.reference_tags) * 10))
                 if options.reference_tags else options.num_ctx),
        keep_alive=options.keep_alive,
    )
    prompt = clean_prompt(raw.get("prompt") or raw.get("tags") or "")
    if not prompt:
        raise ValueError("Model returned an empty prompt.")
    prompt = limit_tags(prompt)
    framing = FRAMING_TAGS.get(options.framing, "")
    if framing and framing.lower() not in prompt.lower():
        prompt = framing + ", " + prompt
    negative = clean_prompt(raw.get("negative") or "")
    options.log("Single prompt ready (%d tags)" % len([t for t in prompt.split(",") if t.strip()]))
    return {"prompt": prompt, "negative": negative}
