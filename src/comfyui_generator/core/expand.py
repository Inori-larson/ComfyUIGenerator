from __future__ import annotations

import re
from typing import Any

from comfyui_generator.core.trace import trace_event


def _norm(text: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(text or "").lower()).strip()


def _has(text: str, words: tuple[str, ...]) -> bool:
    blob = " " + _norm(text) + " "
    for word in words:
        needle = _norm(word)
        if needle and re.search(
                r"(?<![a-z0-9])" + re.escape(needle) + r"[a-z]*", blob):
            return True
    return False


def sanitize_expansion_prompt(prompt: str, shot: dict[str, Any],
                              next_shot: dict[str, Any] | None) -> str:
    del shot, next_shot
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(tag)
    return ", ".join(result)


def apply_expansion_delta(prompt: str, remove: list[str], add: list[str],
                          shot: dict[str, Any],
                          next_shot: dict[str, Any] | None,
                          preserve_irreversible: bool = True) -> str:
    del preserve_irreversible
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    remove_words = [_norm(item) for item in remove if str(item).strip()]
    if remove_words:
        tags = [tag for tag in tags
                if not any(_has(tag, (word,)) for word in remove_words)]
    seen = {tag.lower() for tag in tags}
    for item in add:
        tag = str(item or "").strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    result = sanitize_expansion_prompt(", ".join(tags), shot, next_shot)
    trace_event("expand.delta", {
        "id": str(shot.get("id") or ""),
        "before": str(prompt or ""),
        "remove": remove,
        "add": add,
        "after": result,
    })
    return result
