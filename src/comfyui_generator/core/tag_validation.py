"""Structural booru-tag validation producing findings, never rewriting prompts.

Checks are generic and data-driven: cast consistency, clothing layer conflicts,
and optional unknown-tag/alias reporting against a danbooru export. Findings
describe violations; semantic rewrites stay the job of the AI rewrite loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from comfyui_generator.core.entity_state import (
    LIFTED,
    OPEN,
    REMOVED,
    WORN,
    PromptState,
    parse_state,
)
from comfyui_generator.core.mechanical import split_tags
from comfyui_generator.core.tagdb import (
    TagDatabase, _normalise_tag, load_tag_database,
)

WILDCARD_RE = re.compile(r"(__[^\s,]+__|\{[^{}]*\}|\$\{[^{}]*\})")


@dataclass
class ValidationOptions:
    report_unknown: bool = True
    report_aliases: bool = True
    auto_canonical_alias: bool = False
    max_findings: int = 50


@dataclass
class ValidationResult:
    prompt: str
    findings: list[dict[str, str]] = field(default_factory=list)
    canonical: dict[str, str] = field(default_factory=dict)

    @property
    def blocking(self) -> list[dict[str, str]]:
        return [f for f in self.findings if f.get("severity") == "P1"]

    @property
    def ready(self) -> bool:
        return not self.blocking


def _finding(kind: str, severity: str, message: str,
             evidence: list[str] | None = None) -> dict[str, str]:
    return {
        "kind": kind,
        "severity": severity,
        "message": message,
        "evidence": ", ".join(evidence or []),
    }


def _cast_findings(state: PromptState) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if state.solo and state.boys > 0:
        findings.append(_finding(
            "cast_conflict", "P1",
            "solo 与男性人数标签同时出现，画面人数自相矛盾",
            ["solo", f"{state.boys}boy/male"]))
    if state.solo and state.girls > 1:
        findings.append(_finding(
            "cast_conflict", "P1",
            "solo 与多女性人数标签同时出现，画面人数自相矛盾",
            ["solo", f"{state.girls}girls"]))
    return findings


def _layer_findings(state: PromptState, db: TagDatabase,
                    prompt: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if state.state_conflicts:
        findings.append(_finding(
            "state_conflict", "P1",
            "同一件衣物同时被写为穿着与脱下（含放在地上/椅子上），画面状态自相矛盾",
            state.state_conflicts[:6]))
    top_categories = {"outer_top", "onepiece"}
    bottom_categories = {"outer_bottom", "onepiece"}
    top = [g for g in state.garments if g.category in top_categories]
    bottom = [g for g in state.garments if g.category in bottom_categories]

    top_closed = any(g.state == WORN for g in top)
    top_open = any(g.state in (OPEN, LIFTED) for g in top)
    bottom_closed = any(g.state == WORN for g in bottom)
    bottom_lifted = any(g.state == LIFTED for g in bottom)

    if top_closed and state.skin_top and not top_open:
        tokens = sorted({g.token for g in top if g.state == WORN})
        findings.append(_finding(
            "layer_conflict", "P1",
            "外衣仍穿在身上却出现裸露胸部标签，外衣未敞开/脱下时胸部不应可见",
            tokens + ["nipples/bare breasts/topless"]))
    if top_closed and state.has_inner("inner_top") and not top_open:
        tokens = sorted({g.token for g in top if g.state == WORN})
        inner = sorted({g.token for g in state.garments if g.category == "inner_top"})
        findings.append(_finding(
            "layer_overexposure", "P1",
            "外衣穿好且未敞开时胸罩不可见，却写了胸罩标签（内衣应在敞衣/脱衣后才出现）",
            tokens + inner))
    if bottom_closed and state.skin_groin and not bottom_lifted:
        tokens = sorted({g.token for g in bottom if g.state == WORN})
        findings.append(_finding(
            "layer_conflict", "P2",
            "下装仍穿在身上且未撩起却出现裸露生殖器标签",
            tokens + ["pussy/vagina/labia"]))

    vocab = db.layer_vocab()
    prompt_lower = str(prompt or "").lower()
    claims = [token for token in vocab.get("inner_only_claims", [])
              if token and re.search(
                  r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                  prompt_lower)]
    if claims:
        non_inner = sorted({
            g.token for g in state.garments
            if g.category in set(vocab.get("non_inner_categories", []))
            and g.state != REMOVED})
        if non_inner:
            findings.append(_finding(
                "layer_claim_conflict", "P2",
                "写了 only lingerie 一类状态，却仍有非内衣衣物可见",
                claims + non_inner[:10]))

    if state.aside_legwear_conflict:
        aside = sorted({
            g.token for g in state.garments
            if g.category == "inner_bottom" and g.state in (OPEN, LIFTED)})
        findings.append(_finding(
            "layer_panty_under_legwear", "P2",
            "内裤拨开但覆盖胯部的裤袜/连裤袜仍完整穿着，物理层级难以成立",
            sorted(set(state.aside_legwear_conflict)) + aside[:4]))
    return findings


def _is_placeholder(tag: str) -> bool:
    return bool(WILDCARD_RE.search(tag)) or tag.startswith("<")


def _vocab_tags(db: TagDatabase) -> set[str]:
    values: set[str] = set()
    for tokens in db.layer_vocab().values():
        values.update(tokens)
    return values


def _unknown_findings(db: TagDatabase, tags: list[str],
                      options: ValidationOptions) -> list[dict[str, str]]:
    if not options.report_unknown or not db.has_table():
        return []
    known_vocab = _vocab_tags(db)
    unknown: list[str] = []
    for tag in tags:
        if not str(tag).strip() or _is_placeholder(str(tag)):
            continue
        core = _normalise_tag(tag)
        if core in known_vocab:
            continue
        if not db.is_known(core):
            unknown.append(tag)
        if len(unknown) >= 10:
            break
    if not unknown:
        return []
    return [_finding(
        "unknown_tag", "P3",
        "存在不在 danbooru 词表中的标签（可能是触发词/自造词，确认是否需要）",
        unknown)]


def _alias_findings(db: TagDatabase, tags: list[str],
                    options: ValidationOptions) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not options.report_aliases or not db.has_table():
        return [], {}
    mapping = db.canonical_map(tags)
    if not mapping:
        return [], {}
    shown = [f"{src} -> {dst}" for src, dst in list(mapping.items())[:10]]
    return [_finding(
        "alias_tag", "P3",
        "存在 danbooru 别名标签，建议使用规范标签（默认仅提示，不自动改写）",
        shown)], mapping


def validate_prompt(prompt: str, db: TagDatabase,
                    options: ValidationOptions | None = None) -> ValidationResult:
    options = options or ValidationOptions()
    tags = split_tags(prompt)
    state = parse_state(prompt, db.layer_vocab())

    findings = _cast_findings(state) + _layer_findings(state, db, prompt)
    findings += _unknown_findings(db, tags, options)
    alias_findings, mapping = _alias_findings(db, tags, options)
    findings += alias_findings

    findings = findings[: options.max_findings]
    result = ValidationResult(prompt=prompt, findings=findings)
    if options.auto_canonical_alias:
        result.canonical = mapping
    return result


def database_from_config(tagdb_config: Any) -> TagDatabase:
    csv_path = str(getattr(tagdb_config, "csv_path", "") or "").strip()
    alias_path = str(getattr(tagdb_config, "alias_path", "") or "").strip()
    return load_tag_database(csv_path or None, alias_path or None)


def options_from_config(tagdb_config: Any) -> ValidationOptions:
    return ValidationOptions(
        report_unknown=bool(getattr(tagdb_config, "report_unknown", True)),
        report_aliases=bool(getattr(tagdb_config, "report_aliases", True)),
        auto_canonical_alias=bool(getattr(tagdb_config, "auto_canonical_alias", False)),
    )


def annotate_shots(shots: list[dict[str, Any]], db: TagDatabase,
                   options: ValidationOptions | None = None) -> list[dict[str, str]]:
    """Attach findings/ready to shots in place; returns per-shot finding lists."""
    options = options or ValidationOptions()
    per_shot: list[dict[str, str]] = []
    for shot in shots:
        result = validate_prompt(str(shot.get("prompt") or ""), db, options)
        if result.canonical:
            tags = split_tags(str(shot.get("prompt") or ""))
            shot["prompt"] = ", ".join(result.canonical.get(t, t) for t in tags)
        findings = list(result.findings)
        shot["findings"] = findings
        shot["ready"] = result.ready
        per_shot.append(findings)
    return per_shot
