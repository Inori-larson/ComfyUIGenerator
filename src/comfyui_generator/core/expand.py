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
         "撕破", "撕裂", "破洞", "破损", "湿透")
_FLUIDS = ("cum", "semen", "creampie", "ejaculat", "pussy juice")
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
    "arms": ("arm", "arms", "elbow", "elbows", "wrist", "wrists", "forearm",
             "hand", "hands", "finger", "fingers", "palm"),
    "hands": ("hand", "hands", "finger", "fingers", "palm"),
    "hips": ("hip", "hips", "waist", "pelvis"),
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


def _text(shot: dict[str, Any] | None) -> str:
    shot = shot or {}
    return " ".join(str(shot.get(key) or "") for key in
                    ("prompt", "script", "outline", "scene", "clothing",
                     "character_states", "clothing_details")).lower().strip()


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


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
    return banned


def _clothing_gate(tags: list[str], shot: dict[str, Any]) -> list[str]:
    text = _text(shot)
    nude = _has(text, _NUDE)
    allowed = {item: _has(text, words)
               for item, words in _CLOTHING_ITEM_WORDS.items()}
    result: list[str] = []
    for tag in tags:
        low = tag.lower()
        if nude and any(word in low for details in _CLOTHING_DETAILS.values()
                        for word in details):
            continue
        matched = [item for item, details in _CLOTHING_DETAILS.items()
                   if any(word in low for word in details)]
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
        low = tag.lower()
        if "intact" in low and any(item in low for item in damaged):
            continue
        result.append(tag)
    return result


def _filtered(tags: list[str], banned: set[str]) -> list[str]:
    result: list[str] = []
    for tag in tags:
        low = tag.lower()
        if any(word in low for word in banned):
            continue
        result.append(tag)
    return result


def _anchor_tags(shot: dict[str, Any],
                 next_shot: dict[str, Any] | None) -> list[str]:
    base = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
            if tag.strip()]
    next_text = _text(next_shot)
    anchors: list[str] = []
    for tag in base:
        low = tag.lower()
        if any(word in low for word in _STATE_WORDS):
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
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(tag)
    return ", ".join(result)


def _limb_slots(tag: str) -> set[str]:
    low = tag.lower()
    slots: set[str] = set()
    for slot, words in _LIMB_SLOTS.items():
        if any(re.search(r"\b" + re.escape(word) + r"\b", low) for word in words):
            slots.add(slot)
    return slots


def _is_pose_tag(tag: str) -> bool:
    low = tag.lower()
    return any(re.search(r"\b" + re.escape(word) + r"\b", low)
               for word in _POSE_WORDS)


def apply_expansion_delta(prompt: str, remove: list[str], add: list[str],
                          shot: dict[str, Any],
                          next_shot: dict[str, Any] | None) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    irreversible = [tag for tag in tags
                    if any(word in tag.lower() for word in _IRREVERSIBLE)]
    remove_words = [str(item).strip().lower() for item in remove if str(item).strip()]
    if remove_words:
        tags = [tag for tag in tags
                if not any(word in tag.lower() for word in remove_words)]
    added: list[str] = []
    added_slots: set[str] = set()
    seen = {tag.lower() for tag in tags}
    for item in add:
        tag = str(item or "").strip()
        if tag and tag.lower() not in seen:
            if _is_pose_tag(tag):
                slots = _limb_slots(tag)
                if slots:
                    if slots & added_slots:
                        continue
                    tags = [old for old in tags
                            if not (slots & _limb_slots(old))]
                    added_slots.update(slots)
            seen.add(tag.lower())
            added.append(tag)
    result = sanitize_expansion_prompt(", ".join(added + tags), shot, next_shot)
    result_tags = [tag.strip() for tag in result.split(",") if tag.strip()]
    seen = {tag.lower() for tag in result_tags}
    for tag in irreversible:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            result_tags.append(tag)
    return ", ".join(result_tags)
