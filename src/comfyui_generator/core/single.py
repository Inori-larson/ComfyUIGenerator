"""Single-image prompt generation (natural language -> one Danbooru prompt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.storyboard import clean_prompt

SINGLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "negative": {"type": "string"},
    },
    "required": ["prompt"],
}

SINGLE_SYSTEM_PROMPT = (
    "You write ONE image prompt for an anime illustration (SDXL / Illustrious, Danbooru tags).\n"
    "Rules:\n"
    "1. Output ONLY JSON: {\"prompt\": \"...\", \"negative\": \"...\"}.\n"
    "2. `prompt` is 8-20 comma-separated ENGLISH Danbooru tags, no sentences.\n"
    "3. Include framing (full body / upper body / close-up / portrait / wide shot), pose or action, "
    "expression, location, time of day, weather, lighting and mood.\n"
    "4. Do NOT write quality or rating tags (masterpiece, best quality, safe, nsfw...).\n"
    "5. Do NOT write character appearance tags (hair, eyes, clothes) - they are injected separately.\n"
    "6. `negative` is optional extra negative tags, or an empty string.\n"
    "7. DEFAULT MOOD: bright, cheerful and well lit (daytime, sunny, clear sky, vivid colors, "
    "sharp focus, character clearly visible). Do NOT use night, rain, dark or gloomy scenes unless "
    "the user explicitly asks for them."
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
    mood: str = ""
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    temperature: float = 0.8
    num_predict: int = 400
    num_ctx: int = 4096
    keep_alive: str = "5m"
    log: Callable[[str], None] = field(default=lambda _msg: None)


def build_single_messages(description: str, options: SingleOptions) -> list[dict[str, str]]:
    framing = FRAMING_TAGS.get(options.framing, "")
    user = [
        "Description: %s" % description,
        "Character (already handled, do not describe): %s" % (options.character_tags or "generic"),
        "Visual style: %s" % (options.style_positive or ""),
    ]
    if framing:
        user.append("Framing preference: %s" % framing)
    if options.setting.strip():
        user.append("Extra art direction: %s" % options.setting.strip())
    if options.mood:
        user.append("Preferred atmosphere and lighting (follow this): %s" % options.mood)
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
    prompt = clean_prompt(raw.get("prompt") or raw.get("tags") or "")
    if not prompt:
        raise ValueError("Model returned an empty prompt.")
    framing = FRAMING_TAGS.get(options.framing, "")
    if framing and framing.lower() not in prompt.lower():
        prompt = framing + ", " + prompt
    negative = clean_prompt(raw.get("negative") or "")
    options.log("Single prompt ready (%d tags)" % len([t for t in prompt.split(",") if t.strip()]))
    return {"prompt": prompt, "negative": negative}
