"""Automatic negative-tag guards derived from the positive prompt.

These only suppress specific rendering mistakes; they never introduce plot or
semantic content. A guard tag is added only when the positive prompt contains
the relevant clothing combination.
"""

from __future__ import annotations

from comfyui_generator.core.entity_state import parse_state
from comfyui_generator.core.mechanical import join_tags, split_tags
from comfyui_generator.core.tagdb import load_layers

def automatic_negative(positive: str,
                        negative: str = "",
                        layers: dict | None = None) -> str:
    """Append mistake-suppression tags to negative based on positive content."""
    text = str(positive or "")
    if not text:
        return negative
    vocab = layers or load_layers()
    state = parse_state(text, vocab)
    extra = [token for token in sorted(state.removed_tokens()) if token]
    if not extra:
        return negative
    existing = {t.strip().lower() for t in split_tags(negative)}
    for tag in extra:
        if tag not in existing:
            negative = join_tags(split_tags(negative) + [tag])
            existing.add(tag)
    return negative
