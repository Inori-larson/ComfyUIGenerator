"""Tag string helpers shared by CLI and UI."""

from __future__ import annotations

import re

_CAMERA_TAG_REPLACEMENTS = {
    "looking at camera": "looking at viewer",
    "looking at the camera": "looking at viewer",
    "looking into camera": "looking at viewer",
    "eye contact": "looking at viewer",
}
_CAMERA_OBJECT_TAGS = {
    "camera", "holding camera", "camera phone", "phone camera", "photographer",
    "viewfinder", "dslr", "tripod", "camera strap", "camera lens", "lens",
    "selfie", "selfie stick", "gopro", "webcam", "security camera", "cctv",
}
_PROMPT_TAG_ALIASES = {
    "yi xuan": "yixuan",
    "instrument yuan": "yixuan",
}
_NEGATED_PROMPT_TAGS = {
    "not nude", "not naked", "not explicit", "not nsfw", "no nudity",
    "no explicit content", "sfw", "nsfw",
}


def append_tags(existing: str | None, extra: str | None) -> str:
    items = [x.strip() for x in (existing or "").split(",") if x.strip()]
    seen = {x.lower() for x in items}
    for token in (extra or "").split(","):
        token = token.strip()
        if token and token.lower() not in seen:
            items.append(token)
            seen.add(token.lower())
    return ", ".join(items)


def dedupe_tag_list(tags: str | list[str] | None) -> list[str]:
    items = tags if isinstance(tags, list) else str(tags or "").split(",")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = str(item).strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def dedupe_tags(text: str | list[str] | None) -> str:
    return ", ".join(dedupe_tag_list(text))


def sanitize_prompt_tags(text: str | list[str] | None) -> str:
    """Normalize Booru tags and remove tags that draw physical cameras."""
    items = text if isinstance(text, list) else str(text or "").split(",")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = re.sub(r"\s+", " ", str(item).replace("_", " ")).strip().lower()
        tag = _CAMERA_TAG_REPLACEMENTS.get(tag, tag)
        tag = _PROMPT_TAG_ALIASES.get(tag, tag)
        if (not tag or tag in _CAMERA_OBJECT_TAGS or "camera" in tag
                or tag in _NEGATED_PROMPT_TAGS or ":" in tag or "：" in tag
                or re.search(r"[\u4e00-\u9fff]", tag)):
            continue
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return ", ".join(result)


def estimate_tokens(tags: str | list[str]) -> int:
    """Rough token estimate for prompt size (not a hard model limit)."""
    items = tags if isinstance(tags, list) else str(tags or "").split(",")
    total = 2  # start/end tokens
    for tag in items:
        clean = str(tag).strip()
        if not clean:
            continue
        total += max(1, (len(clean) + 3) // 4) + 1
    return total


def limit_tags(text: str, limit: int = 120) -> str:
    """Dedupe and cap a generated prompt at 120 tags by default."""
    tags: list[str] = []
    seen: set[str] = set()
    for token in str(text or "").split(","):
        tag = token.strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
        if len(tags) >= limit:
            break
    return ", ".join(tags)
