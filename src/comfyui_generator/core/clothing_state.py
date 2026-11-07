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


def _joined(entry: dict[str, Any], *groups: str) -> list[str]:
    out: list[str] = []
    for group in groups:
        out.extend(entry.get(group) or [])
    return out


def clothing_repair_plan(shots: list[dict[str, Any]],
                         premise: str = "") -> dict[str, Any]:
    """Structured, actionable repair plan + whole-film clothing ledger.

    Returns:
      {"weighted": [...], "ledger": {shot_id: {category: state}},
       "fixes": [ {shot, category, weighted, kind, tags, expected, keep}, ... ]}

    The caller feeds this to the AI; the software never edits tags itself.
    """
    if not shots:
        return {"weighted": [], "ledger": {}, "fixes": []}
    weighted_init = initial_weighted_categories(premise)
    parsed = [_category_states(shot) for shot in shots]

    categories: set[str] = set()
    for states in parsed:
        categories |= set(states)

    ledger: dict[str, dict[str, str]] = {}
    for shot, states in zip(shots, parsed):
        row = {category: _dominant_state(entry)
               for category, entry in states.items()}
        if row:
            ledger[str(shot.get("id"))] = row

    fixes: list[dict[str, Any]] = []

    def record(shot_id: Any, category: str, is_weighted: bool, kind: str,
               tags: list[str], expected: str, keep: list[str] | None = None) -> None:
        fixes.append({
            "shot": str(shot_id),
            "category": category,
            "weighted": bool(is_weighted),
            "kind": kind,
            "tags": sorted(set(tags)),
            "expected": expected,
            "keep": sorted(set(keep or [])),
        })

    for category in sorted(categories):
        is_weighted = category in weighted_init
        timeline = [states.get(category) for states in parsed]
        end_idx = max(i for i, entry in enumerate(timeline) if entry)
        end_entry = timeline[end_idx]
        end_id = shots[end_idx].get("id")

        if is_weighted:
            if _dominant_state(end_entry) == "off":
                record(end_id, category, True, "weighted_removed",
                       _joined(end_entry, "off"),
                       "恢复为 active：用 torn / pulled down / around / aside / "
                       "one heel off 等状态，不得 removed/barefoot/on floor")
        elif category in _REMOVABLE_CATEGORIES and end_entry["active"]:
            record(end_id, category, False, "must_be_off",
                   _joined(end_entry, "worn", "displaced", "torn"),
                   "删除该品类所有穿着/移位标签，只保留一个 off-body 标签，"
                   "并注明固定放置位置（如 discarded %s on floor）" % category)

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
                record(shot_id, category, is_weighted, "damage_recovered",
                       _joined(entry, "worn"),
                       "保留 torn/ripped/hole 破损标签，破损永久，"
                       "不得恢复为完整基础标签")

            if entry["worn"] and state in ("displaced", "off") and not is_weighted:
                tags = _joined(entry, "worn", "displaced", "off")
                keep = _joined(entry, "displaced", "off")
                record(shot_id, category, False, "conflicting_states",
                       tags,
                       "同一服装只能保留一个与剧情阶段相符的状态；"
                       "删除冲突的基础穿着标签", keep=keep)

            if len(entry["locations"]) > 1:
                record(shot_id, category, is_weighted, "multiple_locations",
                       _joined(entry, "off", "displaced"),
                       "只保留一个放置位置，删除多余位置标签")

            if is_weighted and state == "off":
                record(shot_id, category, True, "weighted_was_removed",
                       _joined(entry, "off"),
                       "权重服装不得在任何镜头完全脱下；把该镜头改回 active 状态"
                       "（torn / pulled down / around / aside / one heel off / "
                       "bra pulled down / bra strap slipped），删除 on desk/floor、"
                       "removed、barefoot 等全脱标签")

            if (prev_state == "off" and state in ("worn", "displaced")
                    and not restoring):
                kind = "weighted_reworn" if is_weighted else "reworn"
                expected = (
                    "权重服装不得全脱后再穿；恢复为半脱/移位 active 状态"
                    if is_weighted else "常规服装脱下后保持 OFF，删除穿回标签")
                record(shot_id, category, is_weighted, kind,
                       _joined(entry, "worn", "displaced"), expected)

            if entry["locations"]:
                current = next(iter(entry["locations"]))
                if location is not None and current != location and not restoring:
                    record(shot_id, category, is_weighted, "location_jump",
                           _joined(entry, "off", "displaced"),
                           "脱后位置全片统一为 %s，把位置标签改回 %s"
                           % (location, location))
                location = current
            if state != "none":
                prev_state = state

    return {"weighted": sorted(weighted_init), "ledger": ledger,
            "fixes": fixes}


_FIX_KIND_TEXT = {
    "weighted_removed": "带权重服装被完全脱下；须恢复为 active 状态，不得全脱",
    "weighted_was_removed": "权重服装在该镜头被完全脱下；任何镜头都须保持 active",
    "must_be_off": "非权重服装到结尾仍穿着；须完全脱下并注明固定位置",
    "damage_recovered": "破损被恢复；torn/ripped/hole 永久保留",
    "conflicting_states": "同镜基础穿着与半脱/脱下标签冲突；只保留一个状态",
    "multiple_locations": "同镜出现多个放置位置；位置须唯一",
    "weighted_reworn": "权重服装全脱后又穿回；恢复为半脱/移位 active 状态",
    "reworn": "常规服装脱后穿回；保持 OFF",
    "location_jump": "脱后位置跳变；全片统一放置位置",
}


def clothing_gate_findings(shots: list[dict[str, Any]],
                           premise: str = "") -> dict[str, list[str]]:
    plan = clothing_repair_plan(shots, premise)
    findings: dict[str, list[str]] = {}
    for fix in plan["fixes"]:
        message = "%s：%s（相关标签：%s）" % (
            fix["category"], _FIX_KIND_TEXT.get(fix["kind"], fix["kind"]),
            ", ".join(fix["tags"]))
        findings.setdefault(fix["shot"], []).append(message)
    return findings


def clothing_gate_blockers(shots: list[dict[str, Any]],
                           premise: str = "") -> list[str]:
    """Flat list of hard blocker messages (one per violation), for render gate."""
    blockers: list[str] = []
    for shot_id, messages in clothing_gate_findings(shots, premise).items():
        for message in messages:
            blockers.append("shot %s: %s" % (shot_id, message))
    return blockers
