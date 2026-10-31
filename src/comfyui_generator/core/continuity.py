"""Project-level continuity bible and shot grammar.

The chain is deliberately style-neutral: it works for anime, live action and
illustration.  It only adds prompt tags; existing character/action/clothing
state handling remains the source of truth for irreversible changes.
"""

from __future__ import annotations

import re
from typing import Any

GRAMMAR_STYLES: dict[str, dict[str, Any]] = {
    "cinematic": {
        "label": "电影感",
        "shot_sizes": [
            "wide shot", "medium shot", "close-up", "upper body",
            "close-up", "full body",
        ],
        "camera_angles": [
            "eye level", "from side", "eye level", "from below",
            "eye level", "eye level",
        ],
        "compositions": [
            "cinematic composition", "rule of thirds", "depth of field",
            "cinematic composition", "shallow depth of field",
            "cinematic composition",
        ],
    },
    "dialogue": {
        "label": "对话/剧情",
        "shot_sizes": [
            "medium shot", "upper body", "close-up", "medium shot",
            "upper body", "wide shot",
        ],
        "camera_angles": [
            "eye level", "eye level", "from side", "eye level",
            "over the shoulder", "eye level",
        ],
        "compositions": [
            "rule of thirds", "cinematic composition", "depth of field",
            "rule of thirds", "cinematic composition", "wide composition",
        ],
    },
    "action": {
        "label": "动作",
        "shot_sizes": [
            "wide shot", "full body", "medium shot", "close-up",
            "full body", "wide shot",
        ],
        "camera_angles": [
            "eye level", "from side", "from below", "from above",
            "from side", "dutch angle",
        ],
        "compositions": [
            "wide composition", "dynamic composition", "cinematic composition",
            "close-up composition", "dynamic composition", "wide composition",
        ],
    },
    "intimate": {
        "label": "亲密/情色",
        "shot_sizes": [
            "full body", "upper body", "close-up", "close-up",
            "upper body", "full body",
        ],
        "camera_angles": [
            "eye level", "from above", "from side", "from below",
            "eye level", "eye level",
        ],
        "compositions": [
            "cinematic composition", "shallow depth of field",
            "close-up composition", "shallow depth of field",
            "cinematic composition", "cinematic composition",
        ],
    },
}

GRAMMAR_STYLE_CHOICES: list[tuple[str, str]] = [
    (value["label"], key) for key, value in GRAMMAR_STYLES.items()
]

_FRAMING_TAGS = (
    "full body", "upper body", "lower body", "close up", "extreme close up",
    "medium close up", "medium shot", "wide shot", "full shot", "cowboy shot",
    "from above", "from below", "from side", "from behind",
    "dutch angle", "eye level", "over the shoulder", "pov",
)

DEFAULT_CONTINUITY: dict[str, Any] = {
    "character": "",
    "scene": "",
    "state": "",
    "negative": "",
    "grammar": {"auto": True, "style": "cinematic"},
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
    grammar = data.get("grammar")
    grammar = grammar if isinstance(grammar, dict) else {}
    style = str(grammar.get("style") or "cinematic")
    if style not in GRAMMAR_STYLES:
        style = "cinematic"
    return {
        "character": str(data.get("character") or "").strip(),
        "scene": str(data.get("scene") or "").strip(),
        "state": str(data.get("state") or "").strip(),
        "negative": str(data.get("negative") or "").strip(),
        "grammar": {
            "auto": bool(grammar.get("auto", True)),
            "style": style,
        },
    }


def grammar_style(value: Any) -> dict[str, Any]:
    style = str((normalize_continuity(value).get("grammar") or {}).get("style")
                or "cinematic")
    return GRAMMAR_STYLES.get(style) or GRAMMAR_STYLES["cinematic"]


def auto_shot_grammar(index: int, total: int, continuity: Any = None) -> dict[str, str]:
    """Return an editable default shot size/angle for one storyboard row."""
    style = grammar_style(continuity)
    count = max(1, int(total))
    position = max(0, int(index)) % count
    sizes = style["shot_sizes"]
    angles = style["camera_angles"]
    compositions = style["compositions"]
    return {
        "shot_size": sizes[position % len(sizes)],
        "camera_angle": angles[position % len(angles)],
        "composition": compositions[position % len(compositions)],
    }


def strip_shot_grammar(text: Any) -> str:
    """Remove old framing tags before applying a new shot grammar."""
    if not text:
        return ""
    ignored = {tag.lower() for tag in _FRAMING_TAGS}
    result: list[str] = []
    for token in str(text).split(","):
        tag = token.strip()
        key = re.sub(r"[\s_-]+", " ", tag.lower()).strip()
        if tag and key not in ignored:
            result.append(tag)
    return ", ".join(result)


def continuity_positive(value: Any, shot: dict[str, Any] | None = None) -> str:
    data = normalize_continuity(value)
    scene = data["scene"]
    state = data["state"]
    if isinstance(shot, dict):
        scene = str(shot.get("continuity_scene") or scene)
        state = str(shot.get("continuity_state") or state)
    parts = [data["character"], scene, state]
    if isinstance(shot, dict):
        parts.extend([
            str(shot.get("shot_size") or ""),
            str(shot.get("camera_angle") or ""),
            str(shot.get("composition") or ""),
        ])
    return ", ".join(part.strip() for part in parts if str(part).strip())


def continuity_negative(value: Any) -> str:
    return normalize_continuity(value)["negative"]


def apply_auto_grammar(shots: list[dict[str, Any]],
                       continuity: Any = None, overwrite: bool = False) -> None:
    total = len(shots)
    for index, shot in enumerate(shots):
        if not overwrite and all(str(shot.get(key) or "").strip()
                                 for key in ("shot_size", "camera_angle")):
            continue
        shot.update(auto_shot_grammar(index, total, continuity))
