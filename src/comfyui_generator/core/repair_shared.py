"""Shared minimal-change repair contract for prompt repair and render rewrite.

Both call sites ask the LLM to change only tags justified by a finding. The
application never writes repaired semantics itself.
"""

from __future__ import annotations

import re
from typing import Any

from comfyui_generator.core.mechanical import dedupe_tags, split_tags

MINIMAL_FIX_SYSTEM = (
    "You repair one booru prompt that failed a structural or objective render check. "
    "Output only JSON {\"prompt\": \"...\"} of English comma-separated Danbooru tags. "
    "Make the MINIMAL change to fix exactly the listed findings (cast/count, "
    "clothing layering, or objective render mismatches). Keep scene, action, "
    "characters, pose, camera, fluids and every correct tag unchanged; do not "
    "invent new content. If the finding says more people were rendered than the "
    "prompt requests, keep the requested count tags explicit and do not add extra "
    "person-count tags. If a required person/state is missing, add the standard tag "
    "for it. If inner underwear is written while outer clothing is still closed and "
    "not open/removed, either open/remove that outer garment according to the shot's "
    "beat OR, when the shot is still fully clothed, remove the inner-underwear tag. "
    "Resolve contradictory count tags to match who is actually present. "
    "No prose, no refusal."
)


def constrain_to_findings(rewritten: str, original: str,
                          findings: list[dict[str, Any]]) -> str:
    """Keep only tag changes a finding explicitly mentions as evidence."""
    orig = {tag.strip().lower() for tag in split_tags(original)}
    justification = " ".join(
        " ".join(str(f.get(key) or "")
                 for key in ("expected", "actual", "evidence", "message"))
        for f in findings).lower()
    kept: list[str] = []
    for tag in dedupe_tags(split_tags(rewritten)):
        key = tag.strip().lower()
        if key in orig:
            kept.append(tag)
            continue
        if key and re.search(
                r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])",
                justification):
            kept.append(tag)
    return ", ".join(kept) or original
