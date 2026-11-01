from __future__ import annotations

import re
from typing import Any


_NUDE = (
    "completely nude", "full nude", "fully nude", "nude", "naked",
    "全裸", "裸体", "赤裸", "一丝不挂", "光着身子",
)
_TOP_WORDS = (
    "shirt", "blouse", "jacket", "coat", "sweater", "bra", "dress",
    "uniform", "hoodie", "vest", "robe", "kimono", "qipao", "camisole",
    "top", "leotard", "bodysuit",
    "衬衫", "上衣", "外套", "胸罩", "连衣裙", "制服", "睡衣", "旗袍",
    "马甲", "吊带", "衬衣",
)
_BOTTOM_WORDS = (
    "pants", "jeans", "shorts", "skirt", "panties", "pantyhose",
    "stockings", "thighhighs", "trousers", "leggings", "bikini bottom",
    "裤子", "牛仔裤", "短裤", "裙子", "内裤", "丝袜", "连裤袜",
    "长筒袜", "打底裤",
)
_TORN = ("torn", "ripped", "tear", "hole in clothes", "wet clothes",
         "撕破", "撕裂", "破洞", "破损", "湿衣")
_FLUIDS = ("cum", "semen", "creampie", "ejaculat", "pussy juice")
_SEX_ACTS = (
    "penetration", "insertion", "intercourse", "thrusting", "sex",
    "penis in pussy", "vaginal", "riding", "cowgirl", "missionary",
    "doggystyle", "doggy style", "mating press", "straddling",
)
_ORAL_ACTS = (
    "fellatio", "blowjob", "oral", "cunnilingus", "licking penis",
    "deepthroat", "deep throat",
)
_ANAL_ACTS = ("anal", "anal sex", "anal penetration", "anus")
_PULLOUT = (
    "pullout", "pull out", "penis out", "withdrawal", "after sex",
    "afterglow", "post sex", "post-coital",
)
_AFTER_SEX = ("after sex", "afterglow", "post sex", "post-coital")
_DEPTH_RANK = (
    (3, ("deep penetration", "deeper penetration", "deep insertion")),
    (2, ("moderate penetration", "moderate insertion")),
    (1, ("shallow penetration", "shallow insertion")),
)
_SOLO_PARTNER_WORDS = (
    "legs wrapped around waist", "legs wrapped around partner",
    "arms around neck", "arms around partner", "hand on partner",
    "hands on partner", "holding partner", "hugging", "embracing",
    "kissing", "against partner", "with partner", "another person",
    "second person", "multiple people", "wrapped around", "legs around",
    "arms around", "around waist", "around neck", "cowgirl", "missionary",
    "doggystyle", "doggy style", "mating press", "straddling", "riding",
)
_FUTURE_STATE_WORDS = (
    "blood", "bleed", "wound", "injured", "injury", "bruise",
    "dead", "corpse", "unconscious", "killed", "strangled", "stabbed",
    "gun", "pistol", "rifle", "sword", "knife", "blade", "weapon",
    "spear", "arrow", "shield", "armor",
    "fire", "burning", "burned", "smoke", "explosion", "exploded",
    "destroyed", "broken", "cracked", "collapsed", "ruins",
    "tied", "bound", "handcuffed", "restrained", "rope", "chain", "cage",
    "transformed", "transformation", "tentacle", "magic", "spell",
    "food", "cake", "meal", "drink", "bottle", "cup", "plate",
    "phone", "book", "umbrella", "bag", "box", "key", "door",
)
_IRREVERSIBLE = _FLUIDS + _TORN + ("crotchless",)
_STATE_WORDS = (
    "deep penetration", "shallow penetration", "deeper penetration",
    "cum", "semen", "creampie", "ejaculat", "pussy juice",
    "open mouth", "moaning", "half-closed eyes", "closed eyes",
    "blush", "sweat", "trembling", "afterglow", "heavy breathing",
    "biting lip", "tongue out", "saliva", "tears", "wet",
    "panties aside", "panties pulled aside", "panties off", "crotchless",
    "open shirt", "unbuttoned", "shirt pull", "shirt lift",
    "bra pull", "bra off", "bra hanging", "bra unhooked",
    "torn", "ripped", "tear", "hole in clothes",
    "arm", "arms", "elbow", "elbows", "wrist", "wrists",
    "leg", "legs", "thigh", "thighs", "knee", "knees",
    "hand", "hands", "finger", "fingers", "hip", "hips",
    "foot", "feet", "toe", "toes", "spread legs", "legs up",
    "arms up", "legs apart", "legs crossed",
)

_LIMB_SLOTS = {
    "legs": ("leg", "legs", "thigh", "thighs", "knee", "knees",
             "calf", "calves", "foot", "feet", "toe", "toes"),
    "arms": ("arm", "arms", "elbow", "elbows", "wrist", "wrists", "forearm"),
    "hands": ("hand", "hands", "finger", "fingers", "palm",
              "grab", "grabbing", "grip", "gripping", "hold", "holding",
              "touch", "touching", "fingering"),
    "hips": ("hip", "hips", "waist", "pelvis"),
}

_EXPRESSION_SLOTS = {
    "eyes": (
        "gaze", "looking at viewer", "looking away",
        "looking down", "looking up", "looking back", "eye contact",
        "closed eyes", "half closed eyes", "open eyes", "teary eyes",
        "rolling eyes", "empty eyes", "wide eyes",
        "eyes squeezed shut", "eyes rolled up",
    ),
    "mouth": (
        "mouth", "lip", "lips", "tongue", "biting lip", "open mouth",
        "closed mouth", "parted lips", "licking lips",
    ),
    "expression": (
        "expression", "smile", "smirk", "frown", "calm", "ahegao",
        "pout", "orgasm face", "seductive",
    ),
}

_STATE_SLOTS = {
    "depth": (
        "penetration", "deep penetration", "shallow penetration",
        "moderate penetration", "deep insertion", "shallow insertion",
        "penis in pussy", "vaginal", "insertion", "thrusting",
    ),
    "pullout": (
        "pullout", "penis pullout", "pull out", "penis out", "withdrawal",
        "after sex",
    ),
    "vagina": (
        "gaping", "gape", "wet pussy", "pussy juice", "cream",
        "creampie", "used pussy", "after sex",
    ),
}
_POSE_WORDS = (
    "spread", "wrapped", "raised", "lifted", "lifting", "raising",
    "lowering", "bent", "bending", "apart", "parted", "holding",
    "gripping", "grabbing", "pressing", "pressed", "outward", "inward",
    "relaxed", "relaxing", "loose", "loosely", "sides", "arched",
    "upward", "downward",
    "crossed", "around", "up", "down", "forward", "backward", "on",
    "against", "over", "under", "behind", "front", "side",
    "limp", "resting", "slipping", "settling", "crossing",
)

_CLOTHING_ITEM_WORDS = {
    "panties": ("panties", "underwear", "内裤"),
    "bra": ("bra", "胸罩"),
    "shirt": ("shirt", "blouse", "衬衫", "衬衣"),
    "pantyhose": ("pantyhose", "stockings", "thighhighs", "legwear",
                  "丝袜", "连裤袜", "长筒袜"),
    "skirt": ("skirt", "裙子"),
}

_CLOTHING_DETAILS = {
    "panties": ("panties aside", "panties pulled aside", "panties off",
                "crotchless", "拨开内裤", "内裤拨开", "内裤拉下", "内裤脱下"),
    "bra": ("bra pull", "bra off", "bra hanging", "bra unhooked",
            "胸罩松开", "胸罩滑落", "胸罩拉下"),
    "shirt": ("open shirt", "unbuttoned", "shirt pull", "shirt lift",
              "敞开衬衫", "解开衬衫", "衬衫滑落"),
    "pantyhose": ("torn pantyhose", "ripped pantyhose", "crotchless",
                  "torn stockings",
                  "ripped stockings", "撕破丝袜", "撕裂丝袜"),
    "skirt": ("skirt lift", "skirt pulled", "裙子掀起", "裙子拉下"),
}


def _norm(text: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(text or "").lower()).strip()


def _text(shot: dict[str, Any] | None) -> str:
    shot = shot or {}
    return _norm(" ".join(str(shot.get(key) or "") for key in
                            ("prompt", "script", "outline", "scene", "clothing",
                             "character_states", "clothing_details")))


def _has(text: str, words: tuple[str, ...]) -> bool:
    blob = " " + _norm(text) + " "
    for word in words:
        needle = _norm(word)
        if needle and re.search(
                r"(?<![a-z0-9])" + re.escape(needle) + r"[a-z]*", blob):
            return True
    return False


def guard_next(next_shot: dict[str, Any] | None) -> set[str]:
    text = _text(next_shot)
    if not text:
        return set()
    nude = _has(text, _NUDE)
    top = _has(text, _TOP_WORDS) and not _has(
        text, ("topless", "breasts out", "nude", "naked"))
    bottom = _has(text, _BOTTOM_WORDS) and not _has(
        text, ("bottomless", "nude", "naked"))
    pants_aside = _has(text, ("panties aside", "panties pulled aside",
                              "panties off", "crotchless", "拨开内裤",
                              "内裤拨开", "内裤拉下", "内裤脱下", "扯到一边"))
    shirt_open = _has(text, ("open shirt", "unbuttoned", "shirt pull",
                             "shirt lift", "敞开衬衫", "解开衬衫",
                             "衬衫滑落", "衬衫拉开"))
    bra_open = _has(text, ("bra pull", "bra off", "bra hanging",
                           "bra unhooked", "breasts out", "topless",
                           "胸罩松开", "胸罩滑落", "胸罩拉下", "露胸",
                           "胸部露出"))
    torn = _has(text, _TORN)
    next_after = _has(text, _AFTER_SEX)
    next_sex = _has(text, _SEX_ACTS) and not next_after
    banned: set[str] = set()
    if not nude:
        banned.update(_NUDE)
    if top:
        banned.update(("topless", "breasts out", "bare breasts", "nipples"))
        if not bra_open:
            banned.update(("bra pull", "bra off", "bra hanging",
                           "bra unhooked"))
    if bottom:
        banned.update(("bottomless", "pussy", "spread pussy"))
        if not pants_aside:
            banned.update(("panties aside", "panties pulled aside",
                           "panties off", "crotchless", "penetration",
                           "vaginal", "insertion", "intercourse",
                           "penis in pussy", "sex", "thrusting"))
    if not shirt_open:
        banned.update(("open shirt", "unbuttoned", "shirt pull", "shirt lift"))
    if not torn:
        banned.update(_TORN)
    if not _has(text, _FLUIDS):
        banned.update(_FLUIDS)
    if not next_sex:
        banned.update(_SEX_ACTS)
    else:
        max_depth = 3
        for rank, words in _DEPTH_RANK:
            if _has(text, words):
                max_depth = rank
                break
        for rank, words in _DEPTH_RANK:
            if rank > max_depth:
                banned.update(words)
    if not next_after and not _has(text, _PULLOUT):
        banned.update(_PULLOUT)
    if not _has(text, _ORAL_ACTS):
        banned.update(_ORAL_ACTS)
    if not _has(text, _ANAL_ACTS):
        banned.update(_ANAL_ACTS)
    return banned


def _clothing_gate(tags: list[str], shot: dict[str, Any]) -> list[str]:
    text = _text(shot)
    nude = _has(text, _NUDE)
    allowed = {item: _has(text, words)
               for item, words in _CLOTHING_ITEM_WORDS.items()}
    result: list[str] = []
    for tag in tags:
        low = _norm(tag)
        if nude and any(_has(low, details)
                        for details in _CLOTHING_DETAILS.values()):
            continue
        matched = [item for item, details in _CLOTHING_DETAILS.items()
                   if _has(low, details)]
        if not matched or any(allowed[item] for item in matched):
            result.append(tag)
    return result


def _damage_gate(tags: list[str], shot: dict[str, Any]) -> list[str]:
    text = _text(shot)
    damaged = {item for item, details in _CLOTHING_DETAILS.items()
               if _has(text, details)}
    if "crotchless" in text:
        damaged.add("pantyhose")
    result: list[str] = []
    for tag in tags:
        low = _norm(tag)
        if "intact" in low and any(item in low for item in damaged):
            continue
        result.append(tag)
    return result


def _filtered(tags: list[str], banned: set[str]) -> list[str]:
    result: list[str] = []
    for tag in tags:
        low = _norm(tag)
        if any(_has(low, (word,)) for word in banned):
            continue
        result.append(tag)
    return result


def _future_blocked(tag: str, next_text: str) -> bool:
    low = _norm(tag)
    matched = [word for word in _FUTURE_STATE_WORDS if _has(low, (word,))]
    if not matched:
        return False
    return not any(_has(next_text, (word,)) for word in matched)


def _solo_blocked(shot: dict[str, Any]) -> set[str]:
    text = _text(shot)
    if not _has(text, ("solo",)):
        return set()
    has_girl = _has(text, ("1girl",))
    has_boy = _has(text, ("1boy",))
    if _has(text, ("2girls", "2boys", "multiple girls", "multiple boys",
                   "multiple people", "group")):
        return set()
    if has_girl and has_boy:
        return set()
    blocked = set(_SOLO_PARTNER_WORDS)
    if has_girl:
        blocked.update(("1boy", "2boys", "multiple boys"))
    elif has_boy:
        blocked.update(("1girl", "2girls", "multiple girls"))
    return blocked


def _anchor_tags(shot: dict[str, Any],
                 next_shot: dict[str, Any] | None) -> list[str]:
    base = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
            if tag.strip()]
    next_text = _text(next_shot)
    anchors: list[str] = []
    for tag in base:
        low = _norm(tag)
        if (_has(low, _STATE_WORDS) or _is_pose_tag(low)
                or _expression_slots(low) or _state_slots(low)):
            continue
        clothing = [item for item, words in _CLOTHING_ITEM_WORDS.items()
                    if _has(low, words)]
        if clothing and next_text:
            if not all(_has(next_text, _CLOTHING_ITEM_WORDS[item])
                       for item in clothing):
                continue
        anchors.append(tag)
    return anchors


def sanitize_expansion_prompt(prompt: str, shot: dict[str, Any],
                              next_shot: dict[str, Any] | None) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    tags += _anchor_tags(shot, next_shot)
    tags = _clothing_gate(tags, shot)
    tags = _damage_gate(tags, shot)
    tags = _filtered(tags, guard_next(next_shot))
    next_text = _text(next_shot)
    if next_text:
        tags = [tag for tag in tags if not _future_blocked(tag, next_text)]
    solo_blocked = _solo_blocked(shot)
    if solo_blocked:
        tags = _filtered(tags, solo_blocked)
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(tag)
    return ", ".join(result)


def _limb_slots(tag: str) -> set[str]:
    low = _norm(tag)
    slots: set[str] = set()
    for slot, words in _LIMB_SLOTS.items():
        if any(_has(low, (word,)) for word in words):
            slots.add(slot)
    return slots


def _expression_slots(tag: str) -> set[str]:
    low = _norm(tag)
    return {
        slot for slot, words in _EXPRESSION_SLOTS.items()
        if any(_has(low, (word,)) for word in words)
    }


def _state_slots(tag: str) -> set[str]:
    low = _norm(tag)
    return {
        slot for slot, words in _STATE_SLOTS.items()
        if any(_has(low, (word,)) for word in words)
    }


def _is_pose_tag(tag: str) -> bool:
    low = _norm(tag)
    return any(_has(low, (word,)) for word in _POSE_WORDS)


def apply_expansion_delta(prompt: str, remove: list[str], add: list[str],
                          shot: dict[str, Any],
                          next_shot: dict[str, Any] | None,
                          preserve_irreversible: bool = True) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    irreversible = [tag for tag in tags
                    if any(_has(tag, (word,)) for word in _IRREVERSIBLE)]
    remove_words = [_norm(item) for item in remove if str(item).strip()]
    if remove_words:
        tags = [tag for tag in tags
                if not any(_has(tag, (word,)) for word in remove_words)]
    added: list[str] = []
    added_slots: set[str] = set()
    added_state: set[str] = set()
    expression_replaced = False
    seen = {tag.lower() for tag in tags}
    for item in add:
        tag = str(item or "").strip()
        if tag and tag.lower() not in seen:
            slots = _limb_slots(tag)
            if slots:
                if slots & added_slots:
                    continue
                remove_slots = set(slots)
                if "hands" in slots or "arms" in slots:
                    remove_slots.update(("hands", "arms"))
                tags = [old for old in tags
                        if not (remove_slots & _limb_slots(old))]
                added_slots.update(slots)
            expression = _expression_slots(tag)
            if expression and not expression_replaced:
                tags = [old for old in tags if not _expression_slots(old)]
                expression_replaced = True
            state = _state_slots(tag)
            if state:
                if (("depth" in state and "depth" in added_state)
                        or ("vagina" in state and "vagina" in added_state
                            and "pullout" not in state)):
                    continue
                remove_slots = set(state)
                if "depth" in state or "pullout" in state:
                    remove_slots.update(("depth", "pullout"))
                tags = [old for old in tags
                        if not (remove_slots & _state_slots(old))]
                added_state.update(state)
            seen.add(tag.lower())
            added.append(tag)
    result = sanitize_expansion_prompt(", ".join(added + tags), shot, next_shot)
    result_tags = [tag.strip() for tag in result.split(",") if tag.strip()]
    seen = {tag.lower() for tag in result_tags}
    if preserve_irreversible:
        for tag in irreversible:
            if tag.lower() not in seen:
                seen.add(tag.lower())
                result_tags.append(tag)
    return ", ".join(result_tags)
