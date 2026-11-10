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
    ("pants", (r"\bpants?\b", r"trousers", r"\bjeans\b", r"\bshorts?\b",
               r"\bbottoms\b")),
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

# categories that are, by default, removable when present as plain clothing.
# fixed accessories and garment-attached trim (brooch, collar) are part of the
# outfit design and are never required to be removed.
_REMOVABLE_CATEGORIES = {
    "panties", "bra", "leotard", "skirt", "dress", "blazer", "coat",
    "shirt", "vest", "necktie", "gloves", "socks", "heels", "boots",
    "hat", "belt",
}

# Layer/occlusion model (parsing knowledge, not story content).
# Upper layers (outer -> inner): coat/blazer -> shirt -> bra.
# Lower layers: occluding bottoms (pants) hide panties; non-occluding
# bottoms (skirt/dress) let panties show when an exposure cue is present.
_UPPER_OCCLUDERS = ("blazer", "coat", "shirt", "vest", "leotard")
_LOWER_OCCLUDING = ("pants",)
_LOWER_NON_OCCLUDING = ("skirt", "dress")

_OPEN_CUE_RE = re.compile(
    r"\b(?:open(?:ed)?|unbuttoned|unzipped|parted|open shirt|open clothes)\b")

_EXPOSURE_CUE_RE = re.compile(
    r"\b(?:sitting|seated|sit|squatting|kneeling|on knees|knees up|"
    r"legs up|legs spread|spread legs|lying(?:\s+on)?(?:\s+(?:back|side|ground|floor|sand|bed))?|"
    r"on (?:back|side)|hugging own legs|hugging legs|"
    r"skirt (?:lift|lifted|up|raised|flip|flipped|flutter|fluttering|wind|blowing)|"
    r"lifted skirt|upskirt|pov upskirt|wind lift|updraft|"
    r"hand(?:s)? (?:under|up) skirt|under skirt|clothes lifting|"
    r"from below|low angle)\b")

_NO_PANTIES_RE = re.compile(
    r"\b(?:no panties|pantyless|panties removed|panties off|bottomless|"
    r"no underwear|commando|pussy peek|pussy exposed|exposed pussy|naked lower body)\b")

_NO_BRA_RE = re.compile(
    r"\b(?:no bra|braless|bra removed|bra off|topless|breasts out|"
    r"nipples out|exposed breasts|nude breasts)\b")

# state markers --------------------------------------------------------------
_WEIGHT_RE = re.compile(r"^([^():]+)\(([0-9]*\.?[0-9]+)\)$")

_OFF_RE = re.compile(
    r"\b(removed|taken off|discarded|cast aside|set aside|stripped off|"
    r"fully (?:off|removed)|on (?:the )?(?:floor|ground|desk|table|chair)|"
    r"barefoot|bare feet|nude feet|off body|off-body|lying (?:on|across)|"
    r"fallen|folded (?:on|over)|pile of clothes)\b")

_DISPLACED_RE = re.compile(
    r"\b(pulled (?:down|up|aside|to)|around (?:thighs|knees|legs|waist|ankles|"
    r"wrists|arms|elbows)|"
    r"aside|half[- ]?removed|lowered|pushed (?:down|aside|to)|"
    r"slid(?:den)? (?:down|off|to)|one (?:breast|heel|leg)|lifted|lifted up|"
    r"open(?:ed)?|unbuttoned|unzipped|off[- ]?shoulder|askew|displaced|"
    r"wardrobe malfunction|slipped off|slipping off|rolled (?:up|down|to)|"
    r"flipped up|hanging|dangling|"
    r"hem at|skirt flipped|french tip|exposed (?:breast|chest|nipple|pussy)|"
    r"loose|loosened|untied|untie|undone|hanging loose)\b")

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


def initial_clothing_region(premise: str) -> str:
    """Raw initial-clothing text after the 初始服装/initial clothing marker."""
    for line in str(premise or "").splitlines():
        if re.search(r"initial\s*clothing|初始服装", line, re.I):
            return re.sub(r".*?(?:initial\s*clothing|初始服装)\s*[::]?",
                          "", line, flags=re.I)
    return ""


def initial_undergarment_tags(premise: str) -> dict[str, list[str]]:
    """Exact initial bra/panties tags (weights preserved) if declared.

    Returned tags are evidence passed back to the AI; the app never injects
    them into prompts itself.
    """
    out: dict[str, list[str]] = {"panties": [], "bra": []}
    for raw in split_tags(strip_cjk_segments(initial_clothing_region(premise))):
        core, _weight = _strip_weight(raw)
        category = classify_category(core)
        if category in out:
            out[category].append(raw)
    return out


def _open_cue(text: str) -> bool:
    for match in _OPEN_CUE_RE.finditer(text):
        start = match.start()
        window = text[max(0, start - 25):start]
        if not _NEGATION_RE.search(window):
            return True
    return False


def _exposure_cue(text: str) -> bool:
    for match in _EXPOSURE_CUE_RE.finditer(text):
        start = match.start()
        window = text[max(0, start - 25):start]
        if not _NEGATION_RE.search(window):
            return True
    return False


def undergarment_visibility(shot: dict[str, Any],
                            premise: str) -> dict[str, dict[str, Any]]:
    """Decide whether panties/bra should be visible in this shot.

    Layer rules:
      bra: only required once a worn upper layer opens or every upper
           occluder is displaced/off; a closed shirt/blazer hides it.
      panties: never required under occluding pants; required under a
           skirt/dress only when an exposure cue is present.
    Explicit intentional-absence tags (bottomless/topless/...) suppress.
    Returns {category: {"tags": [initial tags...], "cue": str}}.
    """
    initial = initial_undergarment_tags(premise)
    if not initial["panties"] and not initial["bra"]:
        return {}

    raw_tags = _tags_of(shot)
    text = " ".join(_strip_weight(t)[0].lower() for t in raw_tags)
    states = _category_states(shot)
    result: dict[str, dict[str, Any]] = {}

    if initial["bra"]:
        open_layer = False
        seen_occluder = False
        for layer in _UPPER_OCCLUDERS:
            entry = states.get(layer)
            if not entry:
                continue
            seen_occluder = True
            if entry["displaced"] or entry["off"]:
                open_layer = True
            if entry["worn"] and _open_cue(" ".join(entry["worn"]).lower()):
                open_layer = True
        bra_present = bool(states.get("bra"))
        intentional = bool(_NO_BRA_RE.search(text))
        if (not bra_present and not intentional and seen_occluder
                and open_layer):
            result["bra"] = {"tags": initial["bra"],
                             "cue": "upper layer opened or removed"}

    if initial["panties"]:
        occluding = False
        for layer in _LOWER_OCCLUDING:
            entry = states.get(layer)
            if entry and (entry["worn"] or entry["displaced"]):
                occluding = True
        non_occluding = False
        for layer in _LOWER_NON_OCCLUDING:
            entry = states.get(layer)
            if entry and (entry["worn"] or entry["displaced"]):
                non_occluding = True
        panties_present = bool(states.get("panties"))
        intentional = bool(_NO_PANTIES_RE.search(text))
        if (not panties_present and not intentional and not occluding
                and non_occluding and _exposure_cue(text)):
            result["panties"] = {"tags": initial["panties"],
                                 "cue": "skirt/dress with exposure cue"}

    return result


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


_CN_CATEGORY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("necktie", ("领结", "蝴蝶结", "领带")),
    ("coat", ("外套", "西装外套", "夹克")),
    ("shirt", ("衬衫",)),
    ("bra", ("胸罩", "文胸", "胸衣")),
    ("skirt", ("百褶裙", "裙子")),
    ("panties", ("内裤",)),
    ("stockings", ("过膝袜", "长袜", "丝袜", "袜子")),
    ("heels", ("玛丽珍鞋", "厚底鞋", "高跟鞋", "鞋子")),
)


_CN_EXPLICIT_OFF = re.compile(
    r"(?:丢弃|脱下放在|脱下并放在|脱下.{0,4}放在|扔在|扔到|脱在|"
    r"搭在|挂在|放在(?:椅|桌|沙发|地|扶手))")


def _script_field(text: str, wanted: tuple[str, ...]) -> str:
    for field in re.split(r"[；;]", text):
        match = re.match(r"^\s*([^：:]+)[：:](.*)$", field)
        if match and match.group(1).strip() in wanted:
            return match.group(2).strip()
    return ""


def script_clothing_conflicts(shot: dict[str, Any],
                              prior_script_states: Any = None
                              ) -> dict[str, list[str]]:
    """Detect objective contradiction between tags and the shot's script.

    Only flags garments the tags mark as off-body ('discarded ... on ...')
    while the script keeps them worn/displaced. No state is carried across
    shots, so garments genuinely removed earlier are not re-flagged.
    """
    text = str(shot.get("script") or "")
    clothing_field = _script_field(text, ("服装", "衣物", "装束"))
    if not clothing_field:
        return {}
    tag_states = _category_states(shot)
    out: dict[str, list[str]] = {}
    for category, terms in _CN_CATEGORY_TERMS:
        entry = tag_states.get(category)
        if not entry or not entry["off"]:
            continue
        mentioned = next((t for t in terms if t in clothing_field), None)
        if mentioned is None:
            continue
        idx = clothing_field.find(mentioned)
        window = clothing_field[max(0, idx - 14):idx + 14]
        if not _CN_EXPLICIT_OFF.search(window):
            out.setdefault("garment_removed_vs_script", []).append(category)
    return out


def lower_occlusion_open(shot: dict[str, Any]) -> bool:
    """Whether the lower body is exposed given current clothing state."""
    states = _category_states(shot)
    if states.get("panties") and not states["panties"]["worn"]:
        return True
    if states.get("pants", {}).get("worn") or states.get(
            "pants", {}).get("displaced"):
        return False
    for layer in _LOWER_NON_OCCLUDING:
        entry = states.get(layer)
        if entry and not entry["worn"]:
            return True
    return False


def upper_occlusion_open(shot: dict[str, Any]) -> bool:
    """Whether the chest is exposed given current clothing state."""
    states = _category_states(shot)
    if states.get("bra") and not states["bra"]["worn"]:
        return True
    return not any(states.get(l, {}).get("worn") for l in _UPPER_OCCLUDERS)


def anatomy_conflicts(shot: dict[str, Any]) -> dict[str, list[str]]:
    """Anatomical nudity tags that contradict current clothing occlusion.

    Lower body: pussy/vagina/labia are only allowed once the lower
    occlusion is removed. Upper body: nipples/areola only once every
    covering upper layer is open/off or the bra is pulled down/off.
    Returns {kind: [offending tags...]}.
    """
    raw = [_strip_weight(t)[0].lower() for t in _tags_of(shot)]
    out: dict[str, list[str]] = {}

    pussy_tags = [t for t in raw if re.fullmatch(
        r"(?:wet |spread |exposed |open )?(?:pussy|vagina|labia)", t)]
    if pussy_tags and not lower_occlusion_open(shot):
        out["genital_exposed_while_covered"] = sorted(set(pussy_tags))

    nipple_tags = [t for t in raw if re.search(
        r"(?:^|\s)nipples?(?:$|\s)|areola", t)]
    if nipple_tags and not upper_occlusion_open(shot):
        out["nipple_exposed_while_covered"] = sorted(set(nipple_tags))

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
        displaced_run = 0
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

            if entry["ambiguous"]:
                tags = _joined(entry, "worn", "off")
                keep = _joined(entry, "off")
                record(shot_id, category, is_weighted, "conflicting_states",
                       tags,
                       ("该加权服装同一镜头既穿着又离体，二者矛盾；"
                        "只保留一个 active 状态，删除 on floor/removed 等离体标签"
                        if is_weighted else
                        "该服装同时既穿着又离体，二者矛盾；"
                        "只保留与剧情阶段相符的一个状态"), keep=keep)

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
            if state == "displaced":
                displaced_run += 1
                if (not is_weighted and displaced_run >= 3
                        and category in _REMOVABLE_CATEGORIES):
                    record(shot_id, category, False, "displaced_stall",
                           _joined(entry, "worn", "displaced"),
                           "该外衣已半脱/半挂多镜却没有继续，动作不得停在中途；"
                           "请在本镜把它完全脱下成离体状态，并注明固定放置位置"
                           "（如 discarded %s on chair），删除半挂/仍穿着标签"
                           % category)
            elif state != "none":
                displaced_run = 0

            if state != "none":
                prev_state = state

    for shot in shots:
        visibility = undergarment_visibility(shot, premise)
        for category, info in visibility.items():
            record(shot.get("id"), category,
                   category in weighted_init,
                   "undergarment_visible_missing",
                   [],
                   "补回当前应可见的内层标签：%s（依据：%s）；不得新增其它剧情内容"
                   % (", ".join(info["tags"]), info["cue"]),
                   keep=info["tags"])
        for kind, tags in anatomy_conflicts(shot).items():
            record(shot.get("id"), "anatomy", False, kind, tags,
                   "删除与当前服装遮挡矛盾的裸露标签，或先解除对应衣物遮挡；"
                   "二者择一，不得同时保留")
        for kind, categories in script_clothing_conflicts(shot).items():
            record(shot.get("id"), ", ".join(categories), False, kind, [],
                   "英文标签的服装状态须与中文脚本一致：%s（脚本为权威）；"
                   "不得把脚本中仍穿着/半挂的衣物写成丢弃"
                   % ", ".join(categories),
                   keep=categories)

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
    "displaced_stall": "外衣半脱/半挂后多镜未继续脱下；须在本镜脱成离体",
    "undergarment_visible_missing": "按服装层级当前应可见的内衣缺失；须补回",
    "genital_exposed_while_covered": "衣物仍遮挡却出现阴部裸露标签；二者矛盾",
    "nipple_exposed_while_covered": "上衣/胸罩仍遮挡却出现乳头标签；二者矛盾",
    "garment_missing_vs_script": "脚本中在场的衣物在英文标签里缺失；须补回",
    "garment_removed_vs_script": "标签把脚本中仍穿着/半挂的衣物写成丢弃；须改回",
    "garment_state_behind_script": "标签服装状态落后于脚本；须推进到一致",
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
