"""Abstract clothing/entity state extracted from booru tag lists.

This is a structural parser, not a story policy. It recognises generic garment
layers (outer / inner / skin) and their worn/open/lifted/removed state without
knowing any specific character, outfit, scene, or plot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from comfyui_generator.core.mechanical import normalize_weight_syntax, split_tags

WORN = "worn"
OPEN = "open"
LIFTED = "lifted"
REMOVED = "removed"


@dataclass(frozen=True)
class Garment:
    category: str
    token: str
    state: str


@dataclass
class PromptState:
    garments: list[Garment] = field(default_factory=list)
    state_conflicts: list[str] = field(default_factory=list)
    aside_legwear_conflict: list[str] = field(default_factory=list)
    skin_top: bool = False
    skin_groin: bool = False
    girls: int = 0
    boys: int = 0
    solo: bool = False

    def _garments(self, categories: set[str]) -> list[Garment]:
        return [g for g in self.garments if g.category in categories]

    def removed_tokens(self) -> set[str]:
        return {g.token for g in self.garments if g.state == REMOVED}

    def has_outer_top(self, states: set[str]) -> bool:
        return any(g.state in states for g in self._garments({"outer_top", "onepiece"}))

    def has_outer_bottom(self, states: set[str]) -> bool:
        return any(g.state in states for g in self._garments({"outer_bottom", "onepiece"}))

    def has_inner(self, category: str) -> bool:
        return any(g.state != REMOVED
                   for g in self._garments({category}))

    def has_legwear(self) -> bool:
        return any(g.state != REMOVED
                   for g in self._garments({"legwear"}))


def _pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    return re.compile(r"(?<![a-z0-9_-])" + escaped + r"(?![a-z0-9_-])")


def _segment_core(segment: str) -> str:
    return normalize_weight_syntax(segment).strip().lower()


def _match_spans(text: str, tokens: list[str]) -> dict[int, str]:
    """Map character spans to category tokens, longest token wins on overlap."""
    hits: list[tuple[int, int, str]] = []
    for token in sorted({t for t in tokens if t}, key=len, reverse=True):
        for match in _pattern(token).finditer(text):
            hits.append((match.start(), match.end(), token))
    spans: dict[int, str] = {}
    occupied: list[tuple[int, int]] = []
    for start, end, token in sorted(hits, key=lambda h: (h[0], -(h[1] - h[0]))):
        if any(not (end <= a or start >= b) for a, b in occupied):
            continue
        occupied.append((start, end))
        for pos in range(start, end):
            spans[pos] = token
    return spans


def _has_marker(text: str, markers: list[str]) -> bool:
    return any(_pattern(marker).search(text) for marker in markers)


def _garment_state(text: str, vocab) -> str:
    # Open/shoulder exposure takes priority so "shirt off shoulders" is not
    # read as fully removed.
    if _has_marker(text, vocab.get("open_markers", [])):
        return OPEN
    if _has_marker(text, vocab.get("lifted_markers", [])):
        return LIFTED
    if _has_marker(text, vocab.get("removed_markers", [])):
        return REMOVED
    return WORN


_CATEGORY_ORDER = (
    "outer_top", "outer_bottom", "onepiece",
    "inner_top", "inner_bottom", "legwear",
    "footwear", "accessory",
)


def parse_state(prompt: str, vocab: dict[str, list[str]]) -> PromptState:
    state = PromptState()
    category_tokens: dict[str, str] = {}
    for category in _CATEGORY_ORDER:
        for token in vocab.get(category, []):
            category_tokens[token] = category

    skin_top_patterns = vocab.get("skin_top", [])
    skin_groin_patterns = vocab.get("skin_groin", [])
    allowlist = vocab.get("skin_feature_allowlist", [])
    crotch_tokens = [t for t in vocab.get("crotch_covering_legwear", [])
                     if category_tokens.get(t) == "legwear"]
    inner_bottom_tokens = [t for t, category in category_tokens.items()
                           if category == "inner_bottom"]
    aside_markers = [m for m in vocab.get("open_markers", [])
                     if "aside" in m] or ["aside"]

    for raw_segment in split_tags(prompt):
        text = _segment_core(raw_segment)
        if not text:
            continue

        spans = _match_spans(text, list(category_tokens))
        found: dict[str, str] = {}
        for token in category_tokens:
            match = _pattern(token).search(text)
            if not match:
                continue
            start, end = match.start(), match.end()
            if any(pos not in spans or spans[pos] != token for pos in range(start, end)):
                continue
            found.setdefault(category_tokens[token], token)
        for category, token in found.items():
            state.garments.append(Garment(category, token, _garment_state(text, vocab)))

        if (any(_pattern(m).search(text) for m in aside_markers)
                and any(_pattern(t).search(text) for t in inner_bottom_tokens)
                and not _has_marker(text, vocab.get("removed_markers", []))):
            state.aside_legwear_conflict.extend(
                token for token in crotch_tokens if _pattern(token).search(text))

        allowed_spans = _match_spans(text, allowlist)
        if any(_pattern(t).search(text) for t in skin_top_patterns):
            if not _covered_by_allowlist(text, skin_top_patterns, allowed_spans):
                state.skin_top = True
        if any(_pattern(t).search(text) for t in skin_groin_patterns):
            if not _covered_by_allowlist(text, skin_groin_patterns, allowed_spans):
                state.skin_groin = True

        if _pattern("solo").search(text):
            state.solo = True
        state.girls = max(state.girls, _count_people(text, ("girl", "woman", "female")))
        state.boys = max(state.boys, _count_people(text, ("boy", "man", "male")))

    by_token: dict[str, set[str]] = {}
    for garment in state.garments:
        by_token.setdefault(garment.token, set()).add(garment.state)
    state.state_conflicts = sorted(
        token for token, states in by_token.items()
        if WORN in states and REMOVED in states)

    return state


def _covered_by_allowlist(text: str, skin_patterns: list[str],
                          allowed_spans: dict[int, str]) -> bool:
    for token in skin_patterns:
        for match in _pattern(token).finditer(text):
            positions = range(match.start(), match.end())
            if not all(pos in allowed_spans for pos in positions):
                return False
    return True


def _count_people(text: str, words: tuple[str, ...]) -> int:
    best = 0
    for word in words:
        for match in re.finditer(r"(\d+)\s*" + word + r"s?(?![a-z])", text):
            best = max(best, int(match.group(1)))
    return best
