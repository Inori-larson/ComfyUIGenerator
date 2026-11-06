"""Read-only clothing-state analysis and structural gate.

The software never produces or rewrites clothing semantics. This module only
reads the already-generated English tags and reports structural violations:

- weighted initial clothing must remain ACTIVE (never fully removed);
- removable (unweighted) clothing must be fully removed by the last shot;
- state moves forward only (ON -> displaced/off, no silent return to worn);
- any torn/ripped damage is permanent;
- a removed garment has one stable location (desk/floor/...);
- the base worn tag and a displaced/off tag do not coexist ambiguously.

Violations are returned as findings so the AI can be asked to rewrite; the
caller decides whether they block rendering.
"""

from __future__ import annotations

import re
from typing import Any

from .mechanical import split_tags, strip_cjk_segments

# --- garment categories -----------------------------------------------------
# Order matters: more specific categories must be matched first.
_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pantyhose", (r"pantyhose", r"\btights\b", r"crotch hole", r"legwear")),
    ("fishnet", (r"fishnet", r"net tights")),
    ("stockings", (r"\bstockings?", r"thighhighs?", r"hold[- ]?ups", r"garter")),
    ("panties", (r"pant(?:ies|y)", r"\bunderwear\b", r"\bbriefs?\b",
                 r"labia", r"crotchless")),
    ("bra", (r"\bbra\b", r"brassiere", r"bikini top")),
    ("leotard", (r"leotard", r"bodysuit", r"unitard",
                 r"skirt flipped|skirt rolled|skirt lifted|hem at waist")),
    ("skirt", (r"\bskirt\b",)),
    ("dress", (r"\bdress\b", r"\bgown\b")),
    ("blazer", (r"\bblazer\b", r"suit jacket")),
    ("coat", (r"\bcoat\b", r"\bcape\b", r"cloak", r"jacket")),
    ("shirt", (r"\bshirt\b", r"blouse", r"uniform top")),
    ("vest", (r"\bvest\b",)),
    ("collar", (r"\bcollar\b", r"neck piece")),
    ("brooch", (r"\bbrooch\b", r"flower badge", r"corsage")),
    ("necktie", (r"\bnecktie\b", r"\btie\b", r"ribbon tie", r"bowtie")),
    ("gloves", (r"\bglove\b", r"mittens")),
    ("socks", (r"\bsocks?\b", r"ankle high")),
    ("heels", (r"heels?", r"platform (?:heels|shoes)", r"footwear", r"shoes?")),
    ("boots", (r"boots?",)),
    ("hairclip", (r"hair ?clip", r"hair ornament", r"hairpin", r"barrette")),
    ("hat", (r"\bhat\b", r"\bberet\b", r"headwear", r"headdress")),
    ("belt", (r"\bbelt\b", r"sash", r"waist band")),
)

# categories that are, by default, removable when present as plain clothing
_REMOVABLE_CATEGORIES = {
    "panties", "bra", "leotard", "skirt", "dress", "blazer", "coat", "shirt",
    "vest", "collar", "brooch", "necktie", "gloves", "socks", "heels", "boots",
    "hat", "belt",
}

# state markers --------------------------------------------------------------
_WEIGHT_RE = re.compile(r"^([^():]+)\(([0-9]*\.?[0-9]+)\)$")

_OFF_RE = re.compile(
    r"\b(removed|taken off|discarded|cast aside|set aside|stripped off|"
    r"fully (?:off|removed)|on (?:the )?(?:floor|ground|desk|table|chair)|"
    r"barefoot|bare feet|nude feet|off body|off-body|lying (?:on|across)|"
    r"fallen|folded (?:on|over)|pile of clothes)\b")

_DISPLACED_RE = re.compile(
    r"\b(pulled (?:down|up|aside|to)|around (?:thighs|knees|legs|waist|ankles)|"
    r"aside|half[- ]?removed|lowered|pushed (?:down|aside|to)|"
    r"slid(?:den)? (?:down|off|to)|one (?:breast|heel|leg)|lifted|lifted up|"
    r"open(?:ed)?|unbuttoned|unzipped|off[- ]shoulder|askew|displaced|"
    r"wardrobe malfunction|slipped off|rolled (?:up|down|to)|flipped up|"
    r"hem at|skirt flipped|french tip|exposed (?:breast|chest|nipple|pussy))\b")

_TORN_RE = re.compile(
    r"\b(torn|tore|ripped|shredded|slit|cut open|frayed|damaged|crotch hole|"
    r"hole (?:in|on)|holes?)\b")

_RESTORE_RE = re.compile(
    r"\b(pulled (?:back )?up|put back on|putting back on|redressed|dressed|"
    r"tucked back|covered (?:up|back)|fixed (?:back )?up|zipped up|buttoned up|"
    r"readjusted|adjusted back|wearing again|back in place)\b")

_NEGATION_RE = re.compile(
    r"\b(?:no|not|without|never|don't|doesn't|isn't|aren't|won't)\b")

_ACTION_GARMENT_PREFIX_RE = re.compile(
    r"^(?:hand|hands|fingers?|male hands?|gripping|grabbing|holding|"
    r"pulling|pushing|removing|taking|undressing)\b")

_LOCATION_RE = re.compile(
    r"\bon (?:the )?([a-z]+)|\b([a-z]+) (?:on (?:the )?(?:floor|ground|desk|table|chair))\b")
_LOCATION_WORDS = ("floor", "ground", "desk", "table", "chair", "bed", "bench")


def _strip_weight(tag: str) -> tuple[str, str | None]:
    text = re.sub(r"^[^A-Za-z0-9(]+", "", tag.strip())
    match = _WEIGHT_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, None


def _clean_key(tag: str) -> str:
    core, _weight = _strip_weight(tag)
    return re.sub(r"[^a-z0-9]", "", core.lower())


def classify_category(tag: str) -> str | None:
    core, _weight = _strip_weight(tag)
    text = core.lower()
    for category, patterns in _CATEGORY_PATTERNS:
        if any(re.search(pattern, text) for pattern in patterns):
            return category
    return None


def _tags_of(shot: dict[str, Any]) -> list[str]:
    if "_positive_tags" in shot:
        value = shot.get("_positive_tags")
        if isinstance(value, list):
            return [str(t) for t in value]
    return split_tags(strip_cjk_segments(str(shot.get("prompt") or "")))


def initial_weighted_categories(premise: str) -> set[str]:
    """Categories declared as weighted (emphasized) in the initial clothing."""
    weighted: set[str] = set()
    region = ""
    for line in str(premise or "").splitlines():
        if re.search(r"initial\s*clothing|初始服装", line, re.I):
            region = re.sub(r".*?(?:initial\s*clothing|初始服装)\s*[::]?",
                            "", line, flags=re.I)
            break
    for raw in split_tags(strip_cjk_segments(region)):
        core, weight = _strip_weight(raw)
        if weight is None:
            continue
        category = classify_category(core)
        if category:
            weighted.add(category)
    return weighted


# --- per-shot, per-category state -------------------------------------------

def _location_of(tag: str) -> str | None:
    text = _strip_weight(tag)[0].lower()
    for word in _LOCATION_WORDS:
        if re.search(r"\b%s\b" % word, text):
            return word
    match = _LOCATION_RE.search(text)
    if match:
        return match.group(1) or match.group(2)
    return None


def _category_states(shot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for raw in _tags_of(shot):
        core, weight = _strip_weight(raw)
        if _ACTION_GARMENT_PREFIX_RE.search(core.lower()):
            continue
        category = classify_category(core)
        if not category:
            continue
        low = core.lower()
        off = bool(_OFF_RE.search(low))
        displaced = bool(_DISPLACED_RE.search(low))
        torn = bool(_TORN_RE.search(low))
        location = _location_of(raw) if off or displaced else None
        is_state = off or displaced or torn or location is not None
        entry = states.setdefault(category, {
            "worn": [], "off": [], "displaced": [], "torn": [],
            "locations": set(), "weighted": False,
        })
        if weight is not None:
            entry["weighted"] = True
        if torn:
            entry["torn"].append(raw)
        if off:
            entry["off"].append(raw)
        elif displaced:
            entry["displaced"].append(raw)
        elif not is_state:
            entry["worn"].append(raw)
        if location:
            entry["locations"].add(location)
    return entries_normalized(states)


def entries_normalized(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for entry in states.values():
        entry["damage"] = bool(entry["torn"])
        entry["off_body"] = bool(entry["off"]) and not (
            entry["worn"] or entry["displaced"])
        if entry["off"] and entry["worn"]:
            entry["ambiguous"] = True
        else:
            entry["ambiguous"] = False
        entry["active"] = bool(
            entry["worn"] or entry["displaced"] or entry["torn"])
    return states


def _restore_action(shot: dict[str, Any]) -> bool:
    for raw in _tags_of(shot):
        core, _weight = _strip_weight(raw)
        if _RESTORE_RE.search(core.lower()) and not _NEGATION_RE.search(core.lower()):
            return True
    return False


# --- gate -------------------------------------------------------------------

def _dominant_state(entry: dict[str, Any]) -> str:
    if entry["off_body"]:
        return "off"
    if entry["displaced"] or entry["torn"]:
        return "displaced"
    if entry["worn"]:
        return "worn"
    return "none"


def clothing_gate_findings(shots: list[dict[str, Any]],
                           premise: str = "") -> dict[str, list[str]]:
    if not shots:
        return {}
    weighted_init = initial_weighted_categories(premise)
    parsed = [_category_states(shot) for shot in shots]

    categories: set[str] = set()
    for states in parsed:
        categories |= set(states)

    findings: dict[str, list[str]] = {}

    def add(shot_id: Any, message: str) -> None:
        findings.setdefault(str(shot_id), []).append(message)

    for category in sorted(categories):
        is_weighted = category in weighted_init
        timeline = [states.get(category) for states in parsed]
        end_idx = max(i for i, entry in enumerate(timeline) if entry)
        end_entry = timeline[end_idx]
        end_id = shots[end_idx].get("id")

        if is_weighted:
            if _dominant_state(end_entry) == "off":
                add(end_id,
                    "带权重的 %s 已被完全脱下/移除；权重服装必须保留（允许 torn、pulled down、"
                    "aside、one heel off 等 active 状态），不得全脱" % category)
        elif category in _REMOVABLE_CATEGORIES and end_entry["active"]:
            add(end_id,
                "非权重服装 %s 到结尾仍穿着；常规服装须在最后一镜前完全脱下"
                "（请安排明确脱除镜头）" % category)

        prev_state = "none"
        damaged = False
        location: str | None = None
        for i, entry in enumerate(timeline):
            if entry is None:
                continue
            shot = shots[i]
            shot_id = shot.get("id")
            state = _dominant_state(entry)
            restoring = _restore_action(shot)

            if entry["damage"]:
                damaged = True
            elif damaged and state == "worn":
                add(shot_id,
                    "%s 此前已有 torn/ripped 破损，破损永久保留，不得恢复为完整基础标签"
                    % category)

            # base worn tag + displaced/off state in the same shot is a
            # conflict for removable clothing; weighted garments may keep the
            # base tag together with an allowed displaced (half-off) state.
            if entry["worn"] and state in ("displaced", "off") and not is_weighted:
                add(shot_id,
                    "%s 同一镜同时出现基础穿着标签与半脱/脱下标签；常规服装只能有一个有效状态"
                    % category)
            if len(entry["locations"]) > 1:
                add(shot_id,
                    "%s 同一镜出现多个放置位置（%s）；脱下的服装位置必须唯一"
                    % (category, "/".join(sorted(entry["locations"]))))

            # state may not move backward without an explicit restore action
            rank = {"worn": 2, "displaced": 1, "off": 0}
            if (prev_state == "off" and state in ("worn", "displaced")
                    and not restoring):
                if is_weighted:
                    add(shot_id,
                        "%s 已完全脱下，又在无明确穿回动作的镜中回到穿着/半脱；"
                        "权重服装不得全脱后再穿，半脱到穿回需明确非否定动作" % category)
                else:
                    add(shot_id,
                        "常规服装 %s 脱下后不得无过渡穿回；请保持脱下状态" % category)

            if entry["locations"]:
                current = next(iter(entry["locations"]))
                if location is not None and current != location and not restoring:
                    add(shot_id,
                        "已脱下的 %s 位置从 %s 跳变为 %s；脱后位置须全片保持一致"
                        % (category, location, current))
                location = current
            if state != "none":
                prev_state = state
    return findings


def clothing_gate_blockers(shots: list[dict[str, Any]],
                           premise: str = "") -> list[str]:
    """Flat list of hard blocker messages (one per violation), for render gate."""
    blockers: list[str] = []
    for shot_id, messages in clothing_gate_findings(shots, premise).items():
        for message in messages:
            blockers.append("shot %s: %s" % (shot_id, message))
    return blockers
