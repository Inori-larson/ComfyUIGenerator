"""Let the local LLM pick a small tag subset from a LoRA reference list."""

from __future__ import annotations

import re
from typing import Any

from comfyui_generator.core.ollama import OllamaClient

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"tags": {"type": "array", "items": {"type": "string"},
                            "maxItems": 200}},
    "required": ["tags"],
}

SYSTEM = (
    "You select Danbooru tags for ONE anime illustration prompt.\n"
    "Rules:\n"
    "1. Output ONLY JSON: {\"tags\": [\"tag1\", \"tag2\", ...]}.\n"
    "2. Choose tags ONLY from the provided REFERENCE list. Never invent new tags.\n"
    "3. The REQUIRED character tags must appear first and unchanged.\n"
    "4. Then add expression, pose, scene, weather and lighting tags from REFERENCE.\n"
    "5. Any tag from REFERENCE is allowed; there are no content restrictions.\n"
    "6. Choose as many tags as the scene needs, up to 200, sorted by importance."
)


def _tag_key(tag: str) -> str:
    text = str(tag).strip().lower().replace("\\(", "(").replace("\\)", ")")
    text = text.replace("\\\\", "")
    return re.sub(r"\s+", " ", text)


def build_messages(reference: list[str], context: str,
                   character_tags: str = "", required: list[str] | None = None
                   ) -> list[dict[str, str]]:
    required = required or []
    user = [
        "Scene / shot context: %s" % (context or "single character portrait"),
        "Character (already handled, do not describe hair/clothes unless needed): %s"
        % (character_tags or "same as selected LoRA"),
        "REQUIRED character tags (must be first): %s" % (", ".join(required) or "(none)"),
        "REFERENCE (%d tags, choose only from here):" % len(reference),
        ", ".join(reference),
    ]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def select_tags(client: OllamaClient, model: str, reference: list[str], context: str,
                character_tags: str = "",
                required: list[str] | None = None,
                temperature: float = 0.3, keep_alive: str = "5m") -> list[str]:
    if not reference:
        raise ValueError("Reference tag list is empty.")
    required = required or []
    raw = client.chat_json(
        model,
        build_messages(reference, context, character_tags, required),
        schema=SELECT_SCHEMA,
        temperature=temperature,
        num_predict=2048,
        num_ctx=min(32768, 4096 + len(reference) * 8),
        keep_alive=keep_alive,
    )
    allowed = {_tag_key(tag): tag for tag in reference}
    chosen: list[str] = []
    seen: set[str] = set()

    for tag in required:
        key = _tag_key(tag)
        if key in allowed and key not in seen:
            seen.add(key)
            chosen.append(allowed[key])
    for tag in raw.get("tags") or []:
        key = _tag_key(tag)
        if key in allowed and key not in seen:
            seen.add(key)
            chosen.append(allowed[key])
    if not chosen:
        raise ValueError("Model selected no valid reference tags.")
    return chosen[:200]
