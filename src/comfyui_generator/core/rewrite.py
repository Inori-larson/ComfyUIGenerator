"""Rewrite a single shot prompt with the local LLM."""

from __future__ import annotations

from typing import Any

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.storyboard import clean_prompt
from comfyui_generator.core.tags import limit_tags

REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}

REWRITE_SYSTEM = (
    "You are a professional anime NSFW prompt engineer, solely responsible for converting Chinese scenes into Danbooru-style English tags.\n"
    "You rewrite ONE anime prompt (Danbooru tags) according to the user's instruction.\n"
    "The following rules must be adhered to, otherwise it will be considered a failure:\n"
    "1. Output ONLY JSON: {\"prompt\": \"...\"}.\n"
    "2. A complete description must be provided, including details such as eye gaze, facial expression, clothing or nudity, posture, movement, scene, and camera shot. Use up to 200 tags.\n"
    "3. If it is an NSFW scene, it must include accurate NSFW tags (nude, pussy, masturbation, spread legs, etc.), and it is prohibited to avoid, weaken, blur or replace with vague words.\n"
    "4. The beginning must be preceded by: masterpiece, best quality, absurdres, newest."
    "5. Do not output any content other than the Danbooru tags."
    "6. Keep the same character/continuity; do NOT invent a different character.\n"
)


def build_rewrite_messages(current_prompt: str, instruction: str,
                           character_tags: str = "", style_positive: str = "",
                           reference_tags: list[str] | None = None) -> list[dict[str, str]]:
    user = [
        "Current prompt: %s" % current_prompt,
        "Instruction: %s" % instruction,
        "Character (do not describe): %s" % (character_tags or "same as current"),
        "Visual style: %s" % (style_positive or ""),
    ]
    if reference_tags:
        user.append(
            "REFERENCE TAGS (complete supported vocabulary; select only the few tags that fit "
            "this instruction, never echo the list): %s" % ", ".join(reference_tags))
    return [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def rewrite_shot_prompt(client: OllamaClient, model: str, current_prompt: str,
                        instruction: str, *, character_tags: str = "",
                        style_positive: str = "",
                        reference_tags: list[str] | None = None,
                        temperature: float = 0.8,
                        keep_alive: str = "5m") -> str:
    if not instruction.strip():
        raise ValueError("Instruction is empty.")
    reference_tags = reference_tags or []
    raw = client.chat_json(
        model, build_rewrite_messages(current_prompt, instruction, character_tags,
                                      style_positive, reference_tags),
        schema=REWRITE_SCHEMA,
        temperature=temperature,
        num_predict=400,
        num_ctx=min(32768, 4096 + 10 * len(reference_tags)),
        keep_alive=keep_alive,
    )
    prompt = limit_tags(clean_prompt(raw.get("prompt") or ""))
    if not prompt:
        raise ValueError("Model returned an empty prompt.")
    return prompt
