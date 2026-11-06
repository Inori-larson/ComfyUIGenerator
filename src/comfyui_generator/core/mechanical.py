"""Mechanical, semantics-preserving prompt normalization.

Nothing here may add, remove, or alter meaning. The only allowed operations
are whitespace normalization, equivalent weight-syntax normalization, and
removal of byte-for-byte identical duplicate tags.
"""

from __future__ import annotations

import re

_WEIGHT_PAREN_RE = re.compile(r"^\(\s*(.*?)\s*:\s*([0-9]*\.?[0-9]+)\s*\)$")
_SUFFIX_WEIGHT_RE = re.compile(r"^(.*?)\s*\(\s*([0-9]*\.?[0-9]+)\s*\)$")
_BARE_WEIGHT_RE = re.compile(r"^(.*?)\s*:\s*([0-9]*\.?[0-9]+)$")


def normalize_whitespace(value: str) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_weight_syntax(tag: str) -> str:
    text = str(tag or "").strip()
    match = _WEIGHT_PAREN_RE.match(text)
    if match:
        return "(%s:%s)" % (match.group(1).strip(), match.group(2))
    match = _SUFFIX_WEIGHT_RE.match(text)
    if match:
        return "(%s:%s)" % (match.group(1).strip(), match.group(2))
    match = _BARE_WEIGHT_RE.match(text)
    if match:
        return "(%s:%s)" % (match.group(1).strip(), match.group(2))
    return text


def split_tags(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def join_tags(tags: list[str]) -> str:
    return ", ".join(str(tag).strip() for tag in tags if str(tag).strip())


def dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        normalized = normalize_weight_syntax(tag)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def normalize_prompt_text(value: str) -> str:
    tags = dedupe_tags(split_tags(normalize_whitespace(value)))
    return join_tags(tags)
