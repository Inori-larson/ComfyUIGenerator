"""Project-level continuity bible.

It only supplies optional prompt tags and a shared negative; it is style-neutral
and never alters existing story state.
"""

from __future__ import annotations

from typing import Any

DEFAULT_CONTINUITY: dict[str, Any] = {
    "character": "",
    "scene": "",
    "state": "",
    "negative": "",
}


CHARACTER_SHEET_TAGS = (
    "character reference sheet, character turnaround, multiple views, "
    "front view, side view, back view, expression sheet, full body, "
    "standing, neutral background, simple background, consistent design"
)


def character_sheet_prompt(character_tags: Any, clothing: Any = "",
                           style_positive: Any = "") -> str:
    parts = [CHARACTER_SHEET_TAGS, str(character_tags or ""),
             str(clothing or ""), str(style_positive or "")]
    return ", ".join(part.strip() for part in parts if str(part).strip())


def normalize_continuity(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {
        "character": str(data.get("character") or "").strip(),
        "scene": str(data.get("scene") or "").strip(),
        "state": str(data.get("state") or "").strip(),
        "negative": str(data.get("negative") or "").strip(),
    }


def continuity_positive(value: Any, shot: dict[str, Any] | None = None) -> str:
    data = normalize_continuity(value)
    scene = data["scene"]
    state = data["state"]
    if isinstance(shot, dict):
        scene = str(shot.get("continuity_scene") or scene)
        state = str(shot.get("continuity_state") or state)
    parts = [data["character"], scene, state]
    return ", ".join(part.strip() for part in parts if str(part).strip())


def continuity_negative(value: Any) -> str:
    return normalize_continuity(value)["negative"]
