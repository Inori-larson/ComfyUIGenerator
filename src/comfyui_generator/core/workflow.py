"""ComfyUI workflow construction (API format).

The workflow format follows the JSON produced by the old CLI scripts so existing
story files keep working: loader/model/lora/character/style/settings/detailers.
"""

from __future__ import annotations

import os
import random
import re
from typing import Any

from comfyui_generator.core.continuity import (
    continuity_negative, continuity_positive, strip_shot_grammar,
)
from comfyui_generator.core.style_profile import apply_style_profile


_BODY_TRIGGER_GROUPS = (
    (("juice", "cum", "ejaculat", "squirt", "liquid", "orgasm", "drip"), (
        "pussy juice", "love liquid", "cum", "came", "orgasm", "ejaculation",
        "squirt", "wet", "dripping", "after sex", "after came",
        "female ejaculation", "fluid")),
    (("pussy", "vagina", "vulva", "labia", "clit", "anus", "anal"), (
        "pussy", "vagina", "vulva", "labia", "clit", "anus", "anal", "nude",
        "naked", "bottomless", "spread legs", "masturbation", "fingering",
        "sex", "revealing pussy", "pussy juice", "private parts",
        "hand on pussy", "finger in pussy", "quick hand movements",
        "hand movements", "orgasm")),
    (("nipple", "breast", "areola", "boob"), (
        "nipples", "breasts", "breast", "areola", "topless", "breasts out",
        "breast out", "nude", "naked")),
    (("penis", "cock", "testicle", "phallus"), (
        "penis", "cock", "testicles", "phallus", "nude", "naked", "sex")),
    (("ass", "butt"), ("ass", "anus", "anal", "nude", "naked", "bottomless")),
)

_ACTION_TRIGGER_GROUPS = (
    (("missionary",), ("missionary", "lying on back", "on back", "legs up",
                       "legs spread")),
    (("doggy", "doggystyle", "from behind"), (
        "doggystyle", "doggy style", "from behind", "all fours",
        "on all fours", "sex from behind", "bent over")),
    (("cowgirl", "girl on top", "woman on top"), (
        "cowgirl", "girl on top", "woman on top", "straddling",
        "straddle", "riding")),
    (("paizuri", "titjob", "titfuck", "breast sex"), (
        "paizuri", "titjob", "titfuck", "breast sex", "breasts around penis")),
    (("fellatio", "blowjob", "oral"), (
        "fellatio", "blowjob", "oral", "penis in mouth", "licking penis")),
    (("cunnilingus", "oral"), (
        "cunnilingus", "oral", "licking pussy", "mouth on pussy")),
    (("handjob", "hand job"), (
        "handjob", "hand job", "hand on penis", "stroking penis")),
    (("masturbation", "fingering"), (
        "masturbation", "fingering", "finger in pussy", "self pleasure")),
    (("anal", "analsex"), (
        "anal sex", "penis in anus", "anal penetration")),
    (("standing", "standing sex"), (
        "standing sex", "standing", "sex while standing")),
    (("squatting", "squat"), (
        "squatting", "squat", "crouching", "sex while squatting")),
    (("spread legs", "legs spread"), (
        "spread legs", "legs spread", "legs up", "m legs")),
    (("all fours", "on all fours"), (
        "all fours", "on all fours", "hands and knees", "bent over")),
)

_CLOTHING_TRIGGER_GROUPS = (
    (("school uniform", "serafuku"), (
        "school uniform", "serafuku", "sailor collar", "pleated skirt",
        "school bag")),
    (("maid",), ("maid", "maid outfit", "maid uniform", "maid headdress")),
    (("nurse",), ("nurse", "nurse outfit", "nurse uniform", "nurse cap")),
    (("qipao", "cheongsam"), ("qipao", "cheongsam", "china dress")),
    (("kimono",), ("kimono", "japanese clothes", "obi")),
    (("bunny",), ("bunny girl", "bunny suit", "playboy bunny",
                  "rabbit ears")),
    (("wedding dress", "bridal"), ("wedding dress", "bridal", "veil",
                                   "wedding gown")),
    (("swimsuit", "bikini"), ("swimsuit", "bikini", "one-piece swimsuit",
                              "school swimsuit")),
    (("latex", "leather"), ("latex", "leather", "bodysuit", "catsuit")),
    (("armor",), ("armor", "armour", "breastplate", "gauntlets")),
    (("uniform",), ("uniform", "military uniform", "police uniform")),
)

_ACTION_TERMS = (
    "missionary", "cowgirl", "doggy", "doggystyle", "fellatio", "blowjob",
    "cunnilingus", "handjob", "paizuri", "titjob", "anal", "penetration",
    "mating", "press", "grab", "exposure", "uterus", "nipple", "nipples",
    "breast", "breasts", "bouncing", "spread", "grip", "thigh", "thighs",
    "leg", "legs", "pussy", "penis", "cum", "ejaculation", "orgasm",
    "riding", "straddling", "squat", "standing", "bent", "fours", "knees",
    "lick", "mouth", "foot", "feet", "ass",
)

_CLOTHING_TERMS = (
    "skirt", "dress", "shirt", "bra", "panty", "panties", "lingerie",
    "underwear", "thighhigh", "thighhighs", "stocking", "stockings",
    "pantyhose", "legwear", "sock", "socks", "shoe", "shoes", "boot",
    "boots", "heel", "heels", "sneaker", "sneakers", "footwear", "uniform",
    "serafuku",
    "leotard", "bodysuit", "catsuit", "swimsuit", "bikini", "apron", "kimono",
    "qipao", "cheongsam", "hanfu", "yukata", "corset", "garter", "glove",
    "gloves", "hat", "scarf", "necktie", "belt", "coat", "jacket", "blazer",
    "sweater", "hoodie", "top", "shorts", "jeans", "pants", "trousers",
    "vest", "robe", "armor", "choker", "collar", "veil", "mask", "outfit",
    "clothes", "clothing", "latex", "leather", "sleeve", "sleeves", "strap",
    "straps",
)

_SCOPE_TERMS = {
    "action": _ACTION_TERMS,
    "clothing": _CLOTHING_TERMS,
}


def _scope_terms_from_values(values: Any, hints: tuple[str, ...]) -> set[str]:
    terms: set[str] = set()
    for value in values or ():
        key = _tag_key(str(value))
        for hint in hints:
            if hint in key:
                terms.add(key)
                terms.add(hint)
    return terms


def _scope_name_terms(lora: dict[str, Any], scope: str) -> set[str]:
    hints = _SCOPE_TERMS.get(scope, ())
    if not hints:
        return set()
    name = str(lora.get("name") or "").replace("\\", "/").split("/")[-1].lower()
    return {hint for hint in hints if hint in name}


def _scope_reference_terms(lora: dict[str, Any], scope: str) -> set[str]:
    hints = _SCOPE_TERMS.get(scope, ())
    if not hints:
        return set()
    return _scope_terms_from_values(lora.get("reference") or [], hints)


def _tag_key(tag: str) -> str:
    text = tag.lower().replace("\\", "")
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_word(text: str, word: str) -> bool:
    blob = " " + _tag_key(text).replace("_", " ").replace("-", " ") + " "
    needle = _tag_key(word).replace("_", " ").replace("-", " ")
    return bool(needle) and re.search(
        r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", blob) is not None


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(_contains_word(text, word) for word in words)


def join_tags(*parts: Any) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        for token in str(part).split(","):
            tag = token.strip()
            key = _tag_key(tag)
            if tag and key not in seen:
                seen.add(key)
                values.append(tag)
    return ", ".join(values)


def merge(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base or {})
    if extra:
        out.update(extra)
    return out


def expand_wildcards(text: str, seed: int, wc: dict[str, Any] | None) -> str:
    if not text or not isinstance(wc, dict) or not wc.get("enabled"):
        return text
    rng = random.Random(seed)

    def brace(match: re.Match[str]) -> str:
        return rng.choice([x.strip() for x in match.group(1).split("|")])

    for _ in range(4):
        new = re.sub(r"\{([^{}]+)\}", brace, text)
        if new == text:
            break
        text = new

    folder = wc.get("dir") or ""

    def word(match: re.Match[str]) -> str:
        name = match.group(1)
        path = os.path.join(folder, name + ".txt")
        if os.path.isfile(path):
            try:
                lines = [line.strip() for line in open(path, encoding="utf-8")
                         if line.strip() and not line.startswith("#")]
            except OSError:
                lines = []
            if lines:
                return rng.choice(lines)
        return match.group(0)

    return re.sub(r"__([A-Za-z0-9_\-]+)__", word, text)


def base_loader(cfg: dict[str, Any]) -> tuple[dict[str, Any], list[Any], list[Any], list[Any]]:
    if cfg.get("loader") == "unet":
        wf: dict[str, Any] = {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": cfg["unet_name"], "weight_dtype": cfg.get("weight_dtype", "default")}},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": cfg["clip_name"], "type": cfg.get("clip_type", "stable_diffusion"),
                "device": cfg.get("clip_device", "default")}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg["vae_name"]}},
        }
        return wf, ["1", 0], ["2", 0], ["3", 0]
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["model"]}},
        "2": {"class_type": "CLIPSetLastLayer", "inputs": {
            "clip": ["1", 1], "stop_at_clip_layer": cfg.get("clip_skip", -2)}},
    }
    return wf, ["1", 0], ["2", 0], ["1", 2]


def sampler_inputs(cfg: dict[str, Any], seed: int, hires_part: bool = False) -> dict[str, Any]:
    settings = cfg["settings"]
    hires = settings.get("hires", {})
    return {
        "seed": seed,
        "steps": hires.get("steps", 20) if hires_part else settings.get("steps", 30),
        "cfg": settings.get("cfg", 5),
        "sampler_name": settings.get("sampler", "euler_ancestral"),
        "scheduler": settings.get("scheduler", "normal"),
        "denoise": hires.get("denoise", 0.4) if hires_part else 1.0,
    }


def add_sampler(wf: dict[str, Any], cfg: dict[str, Any], nid: str, model: list[Any],
                positive: list[Any], negative: list[Any], latent: list[Any],
                seed: int, hires_part: bool = False) -> None:
    wf[nid] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model,
            "positive": positive,
            "negative": negative,
            "latent_image": latent,
            **sampler_inputs(cfg, seed, hires_part),
        },
    }


def add_detailers(wf: dict[str, Any], cfg: dict[str, Any], image: list[Any], model: list[Any],
                  clip: list[Any], vae: list[Any], positive: list[Any], negative: list[Any],
                  seed: int) -> list[Any]:
    for i, detailer in enumerate(cfg.get("detailers") or []):
        det_id = str(60 + i * 2)
        fd_id = str(61 + i * 2)
        pos_ref, neg_ref = positive, negative
        if detailer.get("prompt"):
            wf[str(200 + i)] = {"class_type": "CLIPTextEncode",
                                "inputs": {"clip": clip, "text": detailer["prompt"]}}
            pos_ref = [str(200 + i), 0]
        if detailer.get("negative"):
            wf[str(220 + i)] = {"class_type": "CLIPTextEncode",
                                "inputs": {"clip": clip, "text": detailer["negative"]}}
            neg_ref = [str(220 + i), 0]
        wf[det_id] = {"class_type": "UltralyticsDetectorProvider",
                      "inputs": {"model_name": detailer.get("model", "bbox/face_yolov8n.pt")}}
        wf[fd_id] = {"class_type": "FaceDetailer", "inputs": {
            "image": image, "model": model, "clip": clip, "vae": vae,
            "guide_size": detailer.get("guide_size", 512),
            "guide_size_for": detailer.get("guide_size_for", True),
            "max_size": detailer.get("max_size", 1024),
            "seed": seed,
            "steps": detailer.get("steps", 20),
            "cfg": detailer.get("cfg", cfg["settings"].get("cfg", 5)),
            "sampler_name": detailer.get("sampler", "euler_ancestral"),
            "scheduler": detailer.get("scheduler", "normal"),
            "positive": pos_ref, "negative": neg_ref,
            "denoise": detailer.get("denoise", 0.3),
            "feather": detailer.get("feather", 5),
            "noise_mask": detailer.get("noise_mask", True),
            "force_inpaint": detailer.get("force_inpaint", True),
            "bbox_threshold": detailer.get("bbox_threshold", 0.5),
            "bbox_dilation": detailer.get("bbox_dilation", 10),
            "bbox_crop_factor": detailer.get("bbox_crop_factor", 3.0),
            "sam_detection_hint": detailer.get("sam_detection_hint", "center-1"),
            "sam_dilation": 0,
            "sam_threshold": 0.93,
            "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 10,
            "bbox_detector": [det_id, 0],
            "wildcard": "",
            "cycle": detailer.get("cycle", 1),
        }}
        image = [fd_id, 0]
    return image


_SCOPE_GROUPS = {
    "body": _BODY_TRIGGER_GROUPS,
    "action": _ACTION_TRIGGER_GROUPS,
    "clothing": _CLOTHING_TRIGGER_GROUPS,
}


def _lora_scope(lora: dict[str, Any]) -> str:
    scope = str(lora.get("scope") or "").strip().lower()
    if scope in _SCOPE_GROUPS:
        return scope
    if lora.get("body") is True:
        return "body"
    if lora.get("action") is True:
        return "action"
    if lora.get("clothing") is True:
        return "clothing"
    name = "\\" + str(lora.get("name") or "").replace("/", "\\").lower() + "\\"
    if "\\身体部位\\" in name or "\\body\\" in name:
        return "body"
    if ("\\动作\\" in name or "\\action\\" in name or "\\actions\\" in name
            or "\\pose\\" in name or "\\poses\\" in name):
        return "action"
    if ("\\服装\\" in name or "\\clothes\\" in name or "\\clothing\\" in name
            or "\\outfit\\" in name or "\\outfits\\" in name):
        return "clothing"
    return ""


def _is_character_lora(lora: dict[str, Any]) -> bool:
    if lora.get("character") is True:
        return True
    name = "\\" + str(lora.get("name") or "").replace("/", "\\").lower() + "\\"
    return "\\角色\\" in name or "\\characters\\" in name or "\\character\\" in name


def _is_body_lora(lora: dict[str, Any]) -> bool:
    return _lora_scope(lora) == "body"


def _is_action_lora(lora: dict[str, Any]) -> bool:
    return _lora_scope(lora) == "action"


def _is_clothing_lora(lora: dict[str, Any]) -> bool:
    return _lora_scope(lora) == "clothing"


def _lora_relevant(lora: dict[str, Any], prompt: str, scope: str) -> bool:
    triggers = [str(tag).strip() for tag in (lora.get("triggers") or [])
                if str(tag).strip()]
    if any(_contains_word(prompt, trigger) for trigger in triggers):
        return True
    for trigger in triggers:
        key = _tag_key(trigger)
        for hints, terms in _SCOPE_GROUPS.get(scope, ()):
            if any(hint in key for hint in hints):
                if _contains_any(prompt, terms):
                    return True
                break
    if scope in _SCOPE_TERMS:
        terms = _scope_reference_terms(lora, scope) | _scope_name_terms(lora, scope)
        if terms and _contains_any(prompt, tuple(sorted(terms))):
            return True
    return False


def _body_lora_relevant(lora: dict[str, Any], prompt: str) -> bool:
    return _lora_relevant(lora, prompt, "body")


def _scope_trigger_tags(cfg: dict[str, Any], shot: dict[str, Any],
                        scope: str) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for lora in lora_chain(cfg, shot):
        if _lora_scope(lora) != scope:
            continue
        for tag in lora.get("triggers") or []:
            text = str(tag).strip()
            key = _tag_key(text)
            if text and key not in seen:
                seen.add(key)
                tags.append(text)
    return ", ".join(tags)


def _body_trigger_tags(cfg: dict[str, Any], shot: dict[str, Any]) -> str:
    return _scope_trigger_tags(cfg, shot, "body")


_DOUBLE_NEGATIVE = (
    "merged bodies, fused, conjoined, extra arms, extra limbs, extra hands"
)
_FEMALE_ONLY_NEGATIVE = (
    "1boy, male, man, penis, testicles, masculine, broad shoulders"
)
_MALE_ONLY_NEGATIVE = (
    "1girl, female, woman, breasts, pussy, vagina, long hair, dress, skirt, "
    "bra, panties, pantyhose, stockings, high heels"
)
_EXPLICIT_TAGS = (
    "penis", "pussy", "vagina", "labia", "clitoris", "sex", "hetero",
    "cum", "semen", "ejaculat", "creampie",
)
_UNCENSORED_POSITIVE = (
    "uncensored, mosaic removal, no mosaic, no pixelation, "
    "detailed genitals, detailed penis, detailed pussy"
)
_UNCENSORED_NEGATIVE = (
    "mosaic, pixelated, pixelation, censor bar, censored penis, "
    "censored pussy, blurred penis, blurred pussy, mosaic censoring"
)


def _apply_uncensored(positive: str, negative: str) -> tuple[str, str]:
    if not _contains_any(positive, _EXPLICIT_TAGS):
        return positive, negative
    return (join_tags(positive, _UNCENSORED_POSITIVE),
            join_tags(negative, _UNCENSORED_NEGATIVE))


def _cast_counts(shot: dict[str, Any]) -> tuple[int, int]:
    text = " ".join((str(shot.get("cast") or ""), str(shot.get("prompt") or "")))
    girls = sum(int(value) for value in
                re.findall(r"(\d+)\s*(?:girl|woman|female)s?", text, re.I))
    boys = sum(int(value) for value in
               re.findall(r"(\d+)\s*(?:boy|man|male)s?", text, re.I))
    return girls, boys


def is_double_shot(shot: dict[str, Any]) -> bool:
    girls, boys = _cast_counts(shot)
    return girls > 0 and boys > 0


def _group_key(tag: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(tag or "").lower()).strip()


_GIRL_TAG_RE = re.compile(
    r"\b(?:1girl|girl|female|woman|breasts?|nipples?|pussy|vagina|labia|"
    r"clitoris|uterus|womb|pantyhose|stockings?|thighhighs?|skirt|dress|"
    r"bra|panties|lingerie|high heels?|makeup|mature female|long hair|"
    r"(?:red|pink|blonde|white|silver|blue|purple|orange|green|"
    r"multicolored) hair)\b"
)
_BOY_TAG_RE = re.compile(
    r"\b(?:1boy|boy|male|man|penis|cock|testicles|phallus|beard|muscular|"
    r"abs|pectorals|short(?:\s+\w+){0,2}\s+hair|adam's apple|sperm|jeans|"
    r"trousers)\b"
)


def _tag_owner(tag: str, girl_owned: set[str], boy_owned: set[str]) -> str:
    key = _group_key(tag)
    if not key:
        return ""
    in_girl, in_boy = key in girl_owned, key in boy_owned
    if in_girl and not in_boy:
        return "girl"
    if in_boy and not in_girl:
        return "boy"
    if in_girl and in_boy:
        return "shared"
    text = " " + key.replace("_", " ").replace("-", " ") + " "
    if _GIRL_TAG_RE.search(text):
        return "girl"
    if _BOY_TAG_RE.search(text):
        return "boy"
    return "shared"


def _owned_tags(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        tags = [str(item) for item in value]
    else:
        tags = str(value or "").split(",")
    return {_group_key(tag) for tag in tags if _group_key(tag)}


def _character_owned(shot: dict[str, Any]) -> tuple[set[str], set[str]]:
    states = shot.get("character_states")
    details = shot.get("clothing_details")
    states = states if isinstance(states, dict) else {}
    details = details if isinstance(details, dict) else {}
    keys = list(states) or list(details)
    if len(keys) < 2:
        return set(), set()
    values = {
        key: (_owned_tags(states.get(key)) if key in states
              else _owned_tags(details.get(key)))
        for key in keys
    }
    scores: dict[str, tuple[int, int]] = {}
    for key, tags in values.items():
        text = " " + " ".join(sorted(tags)).replace("-", " ") + " "
        scores[key] = (len(_GIRL_TAG_RE.findall(text)),
                       len(_BOY_TAG_RE.findall(text)))
    girl_key = max(keys, key=lambda key: (scores[key][0] - scores[key][1],
                                          scores[key][0]))
    if scores[girl_key][0] == 0:
        girl_key = keys[0]
    remaining = [key for key in keys if key != girl_key]
    boy_key = max(remaining, key=lambda key: (scores[key][1] - scores[key][0],
                                              scores[key][1]))
    if scores[boy_key][1] == 0 and keys[1] in remaining:
        boy_key = keys[1]
    return values[girl_key], values[boy_key]


def split_prompt_groups(shot: dict[str, Any]) -> list[dict[str, str]]:
    """Fallback split for old projects without generated per-character prompts."""
    girls, boys = _cast_counts(shot)
    if not (girls and boys):
        return []
    tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
            if tag.strip() and not _cast_tag(tag)]
    girl_owned, boy_owned = _character_owned(shot)
    girl_tags: list[str] = ["1girl"]
    boy_tags: list[str] = ["1boy"]
    for tag in tags:
        owner = _tag_owner(tag, girl_owned, boy_owned)
        if owner in ("girl", "shared"):
            girl_tags.append(tag)
        if owner in ("boy", "shared"):
            boy_tags.append(tag)
    return [
        {"gender": "girl", "name": "main", "prompt": join_tags(*girl_tags)},
        {"gender": "boy", "name": "male", "prompt": join_tags(*boy_tags)},
    ]


def _cast_tag(tag: str) -> bool:
    return bool(re.match(
        r"^(?:\d+\s*(?:girl|boy|other)s?|1girl|1boy|solo|multiple girls|"
        r"multiple boys)$", str(tag).strip(), re.I))


def prompt_groups(shot: dict[str, Any]) -> list[dict[str, str]]:
    groups = shot.get("prompt_groups")
    if isinstance(groups, list) and groups:
        valid = [group for group in groups
                 if isinstance(group, dict) and str(group.get("prompt") or "").strip()]
        if valid:
            return valid
    return split_prompt_groups(shot)


def _gender_negative(gender: str, text: str) -> str:
    if gender == "boy":
        tags = [tag.strip() for tag in _MALE_ONLY_NEGATIVE.split(",") if tag.strip()]
        if _contains_word(text, "long hair"):
            tags = [tag for tag in tags if tag.lower() != "long hair"]
    else:
        tags = [tag.strip() for tag in _FEMALE_ONLY_NEGATIVE.split(",") if tag.strip()]
        if _contains_word(text, "penis"):
            tags = [tag for tag in tags if tag.lower() != "penis"]
    return ", ".join(tags)


_SPLIT_REGION_BOXES: dict[str, tuple[float, float, float, float]] = {
    "right": (0.45, 0.0, 0.55, 1.0),
    "left": (0.0, 0.0, 0.55, 1.0),
    "top": (0.0, 0.0, 1.0, 0.55),
    "bottom": (0.0, 0.45, 1.0, 0.55),
    "center": (0.12, 0.08, 0.76, 0.84),
}


def _auto_split_region(shot: dict[str, Any]) -> str:
    text = " ".join(str(shot.get(key) or "") for key in
                    ("script", "outline", "prompt", "scene")).lower()
    if re.search(
            r"(?:boy|male|man|1boy|男主|男性|男孩|他).{0,20}"
            r"(?:on the left|left side|左侧|左边|在左)|"
            r"(?:左侧|左边|在左).{0,20}(?:boy|male|man|男主|男性)", text):
        return "left"
    if re.search(
            r"(?:boy|male|man|1boy|男主|男性|男孩|他).{0,20}"
            r"(?:on the right|right side|右侧|右边|在右)|"
            r"(?:右侧|右边|在右).{0,20}(?:boy|male|man|男主|男性)", text):
        return "right"
    if re.search(
            r"cowgirl|girl on top|woman on top|straddl|riding|骑乘|骑在|"
            r"跨坐|坐在.{0,6}(?:腿|身)上|坐上来|"
            r"女上男下|女主在上|女上位", text):
        return "bottom"
    if re.search(
            r"\bstacked\b|on top of|lying on|pressing|overlap|\b69\b|"
            r"from behind|from the back|贴身|叠在|叠在一起|上下叠|叠着|"
            r"压着|压在|趴在|趴着|抱在|抱着|拥抱|背后|身后|后面|"
            r"抱起|抱起来|抱起双腿|抱着腿|悬空|托起|站立抱起|"
            r"在.{0,4}身上|"
            r"hugging|cuddling|embrace|spooning", text):
        return "center"
    if re.search(
            r"boy on top|male on top|man on top|on top of|lying on top|"
            r"上方|上面|上边|男上女下|男上位|男主在上|男性在上", text):
        return "top"
    if re.search(
            r"underneath|under (?:her|him)|boy under|male under|"
            r"下方|下面|下边|底下|男下女上|男主在下|男性在下", text):
        return "bottom"
    return "right"


def split_mask_region(shot: dict[str, Any], region: str = "auto") -> dict[str, Any]:
    region = str(region or "auto").strip().lower()
    if region not in _SPLIT_REGION_BOXES:
        region = _auto_split_region(shot)
    x, y, width, height = _SPLIT_REGION_BOXES[region]
    return {
        "region": region,
        "x": x, "y": y, "width": width, "height": height, "grow": 8,
    }


def compose_pass_prompts(cfg: dict[str, Any], shot: dict[str, Any],
                         group: dict[str, str]) -> tuple[str, str]:
    style = apply_style_profile(cfg.get("style") or {},
                                cfg.get("style_profile") or {})
    character = cfg.get("character") or {}
    body = cfg.get("body") or {}
    action = cfg.get("action") or {}
    clothing = cfg.get("clothing") or {}
    text = str(group.get("prompt") or "").strip()
    render_text = (strip_shot_grammar(text)
                   if shot.get("shot_size") or shot.get("camera_angle") else text)
    gender = str(group.get("gender") or "")
    pass_continuity = cfg.get("continuity") or {}
    if gender == "boy":
        pass_continuity = dict(pass_continuity)
        pass_continuity["character"] = ""
        pass_continuity["state"] = ""
    pass_shot = dict(shot)
    pass_shot["prompt"] = text
    continuity_shot = shot
    if gender == "boy":
        pass_shot.pop("continuity_state", None)
        continuity_shot = pass_shot
    chain = lora_chain(cfg, pass_shot)
    action_tags = ""
    clothing_tags = ""
    body_tags = ""
    if any(_is_action_lora(lora) for lora in chain):
        action_tags = _scope_trigger_tags(cfg, pass_shot, "action")
    elif gender == "girl":
        action_tags = shot.get("action_tags", action.get("tags", ""))
    if any(_is_clothing_lora(lora) for lora in chain):
        clothing_tags = _scope_trigger_tags(cfg, pass_shot, "clothing")
    elif gender == "girl":
        clothing_tags = shot.get("clothing_tags", clothing.get("tags", ""))
    if any(_is_body_lora(lora) for lora in chain):
        body_tags = _body_trigger_tags(cfg, pass_shot)
    elif gender == "girl":
        body_tags = shot.get("body_tags", body.get("tags", ""))
    character_tags = ""
    if gender == "girl":
        character_tags = shot.get("character_tags", character.get("tags", ""))
    positive = join_tags(
        shot.get("style_positive", style.get("positive", "")),
        shot.get("style_lora_tags", style.get("lora_tags", "")),
        character_tags,
        action_tags,
        clothing_tags,
        body_tags,
        continuity_positive(pass_continuity, continuity_shot),
        render_text,
        shot.get("style_suffix", style.get("suffix", "")),
    )
    negative = join_tags(
        shot.get("style_negative", style.get("negative", "")),
        shot.get("negative", ""),
        _DOUBLE_NEGATIVE,
        _gender_negative(gender, text),
        continuity_negative(cfg.get("continuity")),
    )
    return _apply_uncensored(positive, negative)


def compose_prompts(cfg: dict[str, Any], shot: dict[str, Any]) -> tuple[str, str]:
    style = apply_style_profile(cfg.get("style") or {},
                                cfg.get("style_profile") or {})
    character = cfg.get("character") or {}
    body = cfg.get("body") or {}
    action = cfg.get("action") or {}
    clothing = cfg.get("clothing") or {}
    prompt = shot.get("prompt", "")
    render_prompt = (strip_shot_grammar(prompt)
                     if shot.get("shot_size") or shot.get("camera_angle") else prompt)
    negative = join_tags(shot.get("style_negative", style.get("negative", "")),
                         shot.get("negative", ""),
                         continuity_negative(cfg.get("continuity")))
    if is_double_shot(shot):
        negative = join_tags(negative, _DOUBLE_NEGATIVE)
    chain = lora_chain(cfg)
    if any(_is_action_lora(lora) for lora in chain):
        action_source = _scope_trigger_tags(cfg, shot, "action")
    else:
        action_source = shot.get("action_tags", action.get("tags", ""))
    if any(_is_clothing_lora(lora) for lora in chain):
        clothing_source = _scope_trigger_tags(cfg, shot, "clothing")
    else:
        clothing_source = shot.get("clothing_tags", clothing.get("tags", ""))
    if any(_is_body_lora(lora) for lora in chain):
        body_source = _body_trigger_tags(cfg, shot)
    else:
        body_source = shot.get("body_tags", body.get("tags", ""))
    positive = join_tags(
        shot.get("style_positive", style.get("positive", "")),
        shot.get("style_lora_tags", style.get("lora_tags", "")),
        shot.get("character_tags", character.get("tags", "")),
        action_source,
        clothing_source,
        body_source,
        continuity_positive(cfg.get("continuity"), shot),
        render_prompt,
        shot.get("style_suffix", style.get("suffix", "")),
    )
    return _apply_uncensored(positive, negative)


def lora_chain(cfg: dict[str, Any], shot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    loras = cfg.get("loras")
    if loras is None:
        legacy = cfg.get("lora")
        loras = [legacy] if legacy else []
    result = [lora for lora in loras if lora.get("name")]
    if shot is None:
        return result
    prompt = shot.get("prompt", "")
    filtered: list[dict[str, Any]] = []
    for lora in result:
        if shot.get("skip_character_loras") and _is_character_lora(lora):
            continue
        scope = _lora_scope(lora)
        if scope and not _lora_relevant(lora, prompt, scope):
            continue
        filtered.append(lora)
    return filtered


def build_workflow(cfg: dict[str, Any], shot: dict[str, Any], positive: str, negative: str,
                   seed: int, hires: bool, prefix: str) -> dict[str, Any]:
    wf, model, clip_ref, vae = base_loader(cfg)
    clip = clip_ref

    if cfg.get("v_prediction"):
        wf["50"] = {"class_type": "ModelSamplingDiscrete", "inputs": {
            "model": model, "sampling": "v_prediction", "zsnr": cfg.get("zsnr", True)}}
        model = ["50", 0]

    use_ip = shot.get("use_ipadapter", (cfg.get("character") or {}).get("use_ipadapter", False))
    if use_ip:
        ip = merge((cfg.get("character") or {}).get("ipadapter"), shot.get("ipadapter"))
        wf["40"] = {"class_type": "IPAdapterUnifiedLoader",
                    "inputs": {"model": model, "preset": ip.get("preset", "PLUS (high strength)")}}
        wf["41"] = {"class_type": "LoadImage",
                    "inputs": {"image": ip.get("reference", "anime_story/character_ref.png")}}
        wf["42"] = {"class_type": "IPAdapterAdvanced", "inputs": {
            "model": ["40", 0], "ipadapter": ["40", 1], "image": ["41", 0],
            "weight": ip.get("weight", 0.6), "weight_type": ip.get("weight_type", "linear"),
            "combine_embeds": ip.get("combine_embeds", "concat"),
            "start_at": ip.get("start_at", 0.0), "end_at": ip.get("end_at", 0.8),
            "embeds_scaling": ip.get("embeds_scaling", "V only")}}
        model = ["42", 0]

    style_ref = merge(cfg.get("style_ref"), shot.get("style_ref"))
    if shot.get("use_style_ref", style_ref.get("enabled", False)) and style_ref.get("image"):
        wf["30"] = {"class_type": "IPAdapterUnifiedLoader",
                    "inputs": {"model": model, "preset": style_ref.get("preset", "PLUS (high strength)")}}
        wf["31"] = {"class_type": "LoadImage", "inputs": {"image": style_ref["image"]}}
        wf["32"] = {"class_type": "IPAdapterAdvanced", "inputs": {
            "model": ["30", 0], "ipadapter": ["30", 1], "image": ["31", 0],
            "weight": style_ref.get("weight", 0.8),
            "weight_type": style_ref.get("weight_type", "style transfer"),
            "combine_embeds": style_ref.get("combine_embeds", "concat"),
            "start_at": style_ref.get("start_at", 0.0), "end_at": style_ref.get("end_at", 1.0),
            "embeds_scaling": style_ref.get("embeds_scaling", "V only")}}
        model = ["32", 0]

    for i, lora in enumerate(lora_chain(cfg, shot)[:10]):
        nid = str(20 + i)
        strength = lora.get("strength", 0.8)
        if lora.get("clip_strength") is not None:
            wf[nid] = {"class_type": "LoraLoader", "inputs": {
                "model": model, "clip": clip, "lora_name": lora["name"],
                "strength_model": strength,
                "strength_clip": lora.get("clip_strength", strength)}}
            model = [nid, 0]
            clip = [nid, 1]
        else:
            wf[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": model, "lora_name": lora["name"], "strength_model": strength}}
            model = [nid, 0]

    settings = cfg["settings"]
    wildcards = cfg.get("wildcards") or {}
    positive = expand_wildcards(positive, seed, wildcards)
    negative = expand_wildcards(negative, seed, wildcards)
    wf["6"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": positive}}
    wf["7"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": negative}}
    positive_ref = ["6", 0]
    negative_ref = ["7", 0]
    pose_image = str(shot.get("pose_image") or "").strip()
    pose_controlnet = str(shot.get("pose_controlnet") or "").strip()
    if pose_image and pose_controlnet:
        wf["100"] = {"class_type": "ControlNetLoader",
                     "inputs": {"control_net_name": pose_controlnet}}
        wf["101"] = {"class_type": "LoadImage", "inputs": {"image": pose_image}}
        wf["102"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": positive_ref, "negative": negative_ref,
            "control_net": ["100", 0], "image": ["101", 0],
            "strength": float(shot.get("pose_strength", 0.7)),
            "start_percent": float(shot.get("pose_start", 0.0)),
            "end_percent": float(shot.get("pose_end", 0.9)),
        }}
        positive_ref = ["102", 0]
        negative_ref = ["102", 1]
    init_image = str(shot.get("init_image") or "").strip()
    inpaint_mask = shot.get("inpaint_mask")
    if init_image:
        width = int(settings.get("width", 1024))
        height = int(settings.get("height", 1344))
        wf["70"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        wf["72"] = {"class_type": "ImageScale", "inputs": {
            "image": ["70", 0],
            "upscale_method": "lanczos",
            "width": width,
            "height": height,
            "crop": "disabled"}}
        if isinstance(inpaint_mask, dict):
            x_ratio = max(0.0, min(1.0, float(inpaint_mask.get("x", 0.5))))
            y_ratio = max(0.0, min(1.0, float(inpaint_mask.get("y", 0.0))))
            w_ratio = max(0.01, min(1.0 - x_ratio,
                                     float(inpaint_mask.get("width", 0.5))))
            h_ratio = max(0.01, min(1.0 - y_ratio,
                                     float(inpaint_mask.get("height", 1.0))))
            mask_x = int(round(width * x_ratio))
            mask_y = int(round(height * y_ratio))
            mask_w = max(1, int(round(width * w_ratio)))
            mask_h = max(1, int(round(height * h_ratio)))
            wf["90"] = {"class_type": "SolidMask", "inputs": {
                "value": 0.0, "width": width, "height": height}}
            wf["91"] = {"class_type": "SolidMask", "inputs": {
                "value": 1.0, "width": mask_w, "height": mask_h}}
            wf["92"] = {"class_type": "MaskComposite", "inputs": {
                "destination": ["90", 0], "source": ["91", 0],
                "x": mask_x, "y": mask_y, "operation": "add"}}
            wf["71"] = {"class_type": "VAEEncodeForInpaint", "inputs": {
                "pixels": ["72", 0], "vae": vae, "mask": ["92", 0],
                "grow_mask_by": int(inpaint_mask.get("grow", 8))}}
        else:
            wf["71"] = {"class_type": "VAEEncode", "inputs": {
                "pixels": ["72", 0], "vae": vae}}
        latent = ["71", 0]
    else:
        wf["8"] = {"class_type": "EmptyLatentImage", "inputs": {
            "width": settings.get("width", 1024),
            "height": settings.get("height", 1344),
            "batch_size": 1}}
        latent = ["8", 0]
    add_sampler(wf, cfg, "9", model, positive_ref, negative_ref, latent, seed)
    if init_image:
        default_denoise = 1.0 if isinstance(inpaint_mask, dict) else 0.45
        wf["9"]["inputs"]["denoise"] = float(shot.get("init_denoise", default_denoise))
    wf["10"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": vae}}

    final = ["10", 0]
    if hires:
        hires_cfg = settings.get("hires", {})
        upscaler = hires_cfg.get("upscale_model")
        if upscaler:
            wf["16"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscaler}}
            wf["17"] = {"class_type": "ImageUpscaleWithModel", "inputs": {
                "upscale_model": ["16", 0], "image": ["10", 0]}}
            wf["11"] = {"class_type": "ImageScaleBy", "inputs": {
                "image": ["17", 0], "upscale_method": "lanczos",
                "scale_by": hires_cfg.get("scale", 1.5) / hires_cfg.get("model_scale", 4.0)}}
        else:
            wf["11"] = {"class_type": "ImageScaleBy", "inputs": {
                "image": ["10", 0], "upscale_method": "lanczos",
                "scale_by": hires_cfg.get("scale", 1.5)}}
        wf["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": vae}}
        add_sampler(wf, cfg, "13", model, positive_ref, negative_ref, ["12", 0], seed, True)
        wf["14"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": vae}}
        final = ["14", 0]

    final = add_detailers(wf, cfg, final, model, clip, vae, positive_ref, negative_ref, seed)
    wf["64"] = {"class_type": "SaveImage", "inputs": {"images": final, "filename_prefix": prefix}}
    return wf


def stage_for_node(node_id: str | int | None) -> str:
    if node_id is None:
        return ""
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return ""
    if nid == 9:
        return "base"
    if nid in (90, 91, 92):
        return "inpaint"
    if nid in (100, 101, 102):
        return "pose"
    if nid == 13:
        return "hires"
    if 60 <= nid < 64:
        return "detail"
    return ""
