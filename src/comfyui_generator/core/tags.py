"""Tag string helpers shared by CLI and UI."""

from __future__ import annotations


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


def limit_tags(text: str, limit: int = 100) -> str:
    """Dedupe and cap a single-image prompt at 100 tags by default."""
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
