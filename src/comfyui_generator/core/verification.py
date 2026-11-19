"""Post-render verification: compare WD tagger output with prompt intent.

Generic checks only (cast count, clothing layering). Inputs are the shot
prompt (expected) and tagger scores (actual). Findings stay structural; the
AI rewrite loop turns them into new prompt wording elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from comfyui_generator.core.entity_state import OPEN, WORN, parse_state
from comfyui_generator.core.tagdb import TagDatabase
from comfyui_generator.core.tagdb import TagDatabase


@dataclass
class VerifyThresholds:
    cast: float = 0.6
    layer: float = 0.5
    general: float = 0.35


@dataclass
class RenderFinding:
    kind: str
    severity: str
    message: str
    expected: str = ""
    actual: str = ""
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "evidence": self.evidence,
            "source": "tagger",
        }


def _score(tags: dict[str, float], names: tuple[str, ...]) -> float:
    best = 0.0
    for name in names:
        best = max(best, float(tags.get(name, 0.0)))
    return best


def _people_count(tags: dict[str, float], female: bool, threshold: float) -> int:
    if female:
        single, multi = "1girl", ("2girls", "3girls", "multiple girls", "6+girls")
    else:
        single, multi = "1boy", ("2boys", "3boys", "multiple boys", "6+boys")
    if _score(tags, multi) >= threshold:
        return 2
    return 1 if float(tags.get(single, 0.0)) >= threshold else 0


def _cast_findings(actual: dict[str, float], state,
                    th: VerifyThresholds) -> list[RenderFinding]:
    findings: list[RenderFinding] = []
    girls = _people_count(actual, True, th.cast)
    boys = _people_count(actual, False, th.cast)
    multiple = _score(actual, ("multiple_views", "duo", "group"))
    wants_boy = state.boys > 0

    if girls == 0:
        findings.append(RenderFinding(
            "render_cast_missing_girl", "P1",
            "成品未检出明确女性角色", "1girl", f"girl_score={girls}",
            ["1girl"]))
    if wants_boy and boys == 0:
        findings.append(RenderFinding(
            "render_cast_missing_boy", "P1",
            "分镜要求男性参与，但成品未检出男性角色",
            "1boy", f"boy_score={boys}", ["1boy"]))
    if (not wants_boy) and boys >= 1 and (state.solo or state.boys == 0):
        findings.append(RenderFinding(
            "render_cast_extra_boy", "P1",
            "分镜为女主独处，但成品检出男性角色（服装/人物串台）",
            "1girl solo", f"1boy detected, score={_score(actual, ('1boy',)):.2f}",
            ["1boy", "solo"]))
    if state.solo and multiple >= th.cast:
        findings.append(RenderFinding(
            "render_cast_multiple", "P2",
            "solo 镜头成品疑似出现多人", "solo",
            f"multiple_score={multiple:.2f}", ["multiple views"]))
    return findings


def _actual_layers(actual: dict[str, float], db: TagDatabase,
                   threshold: float):
    outer_top: list[str] = []
    outer_bottom: list[str] = []
    inner_top: list[str] = []
    skin_top = _score(actual, tuple(db.layers.get("skin_top", [])))
    skin_groin = _score(actual, tuple(db.layers.get("skin_groin", [])))
    for token in db.layers.get("outer_top", []):
        if float(actual.get(token, 0.0)) >= threshold:
            outer_top.append(token)
    for token in db.layers.get("outer_bottom", []):
        if float(actual.get(token, 0.0)) >= threshold:
            outer_bottom.append(token)
    for token in db.layers.get("onepiece", []):
        if float(actual.get(token, 0.0)) >= threshold:
            outer_top.append(token)
            outer_bottom.append(token)
    for token in db.layers.get("inner_top", []):
        if float(actual.get(token, 0.0)) >= threshold:
            inner_top.append(token)
    return outer_top, outer_bottom, inner_top, skin_top, skin_groin


def _layer_findings(actual: dict[str, float], state, db: TagDatabase,
                    th: VerifyThresholds) -> list[RenderFinding]:
    findings: list[RenderFinding] = []
    outer_top, outer_bottom, inner_top, skin_top, skin_groin = _actual_layers(
        actual, db, th.layer)

    prompt_closed_top = state.has_outer_top({WORN})
    prompt_open_top = state.has_outer_top({OPEN, "lifted"})
    prompt_bare_top = state.skin_top

    if prompt_closed_top and not prompt_open_top:
        if skin_top >= th.layer:
            findings.append(RenderFinding(
                "render_layer_bra_over_outer", "P1",
                "外衣穿好时成品检出裸露胸部，服装层级错误",
                "外衣遮盖胸部", f"bare_breast_score={skin_top:.2f}",
                outer_top[:4] + ["nipples/bare breasts"]))
        elif inner_top and _score(actual, ("bra",)) >= th.layer:
            findings.append(RenderFinding(
                "render_layer_bra_visible", "P2",
                "成品疑似在外衣外检出胸罩",
                "胸罩不可见", f"bra_score={_score(actual, ('bra',)):.2f}",
                outer_top[:4] + inner_top[:2]))

    prompt_closed_bottom = state.has_outer_bottom({WORN})
    if prompt_closed_bottom and not state.has_outer_bottom({"lifted"}) and state.skin_groin:
        if skin_groin >= th.layer:
            findings.append(RenderFinding(
                "render_layer_groin_covered", "P2",
                "下装穿好时成品检出裸露生殖器", "下装遮盖",
                f"pussy_score={skin_groin:.2f}", outer_bottom[:4] + ["pussy"]))

    if state.has_inner("inner_top") and not prompt_closed_top:
        if prompt_bare_top and skin_top < th.layer and not outer_top:
            findings.append(RenderFinding(
                "render_layer_breasts_hidden", "P2",
                "分镜要求半脱胸罩露胸，但成品未稳定检出裸露胸部",
                "nipples/bare breasts", f"bare_breast_score={skin_top:.2f}",
                ["bra pulled down", "nipples"]))
    return findings


def verify_render(shot_prompt: str, tagger_result: dict[str, Any],
                  db: TagDatabase,
                  thresholds: VerifyThresholds | None = None) -> list[dict[str, Any]]:
    th = thresholds or VerifyThresholds()
    actual = dict(tagger_result.get("general") or {})
    if not actual:
        return []
    state = parse_state(shot_prompt, db.layer_vocab())
    findings = _cast_findings(actual, state, th)
    findings += _layer_findings(actual, state, db, th)
    return [f.as_dict() for f in findings]
