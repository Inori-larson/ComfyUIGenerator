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
