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
_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


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


def _weight_core(tag: str) -> tuple[str, str | None]:
    text = str(tag or "").strip()
    match = _WEIGHT_PAREN_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2)
    match = _SUFFIX_WEIGHT_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2)
    match = _BARE_WEIGHT_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, None


def _equivalence_key(tag: str) -> str:
    core, _weight = _weight_core(normalize_weight_syntax(tag))
    return re.sub(r"\s+", " ", core).strip().lower()


def dedupe_tags(tags: list[str]) -> list[str]:
    chosen: dict[str, str] = {}
    order: list[str] = []
    for raw in tags:
        tag = normalize_weight_syntax(raw)
        key = _equivalence_key(tag)
        if key not in chosen:
            chosen[key] = tag
            order.append(key)
            continue
        _core, existing_weight = _weight_core(chosen[key])
        _new_core, new_weight = _weight_core(tag)
        if existing_weight is None and new_weight is not None:
            chosen[key] = tag
    return [chosen[key] for key in order]


def strip_cjk_segments(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(",")]
    kept = [part for part in parts if part and not _CJK_RE.search(part)]
    return ", ".join(kept)


def normalize_prompt_text(value: str) -> str:
    tags = dedupe_tags(split_tags(normalize_whitespace(value)))
    return join_tags(tags)


def normalize_english_prompt_text(value: str) -> str:
    return strip_cjk_segments(normalize_prompt_text(value))
