"""ComfyUI workflow construction (API format).

The workflow format follows the JSON produced by the old CLI scripts so existing
story files keep working: loader/model/lora/character/style/settings/detailers.
"""

from __future__ import annotations

import os
import random
import re
from typing import Any



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


def compose_prompts(cfg: dict[str, Any], shot: dict[str, Any]) -> tuple[str, str]:
    style = cfg.get("style") or {}
    character = cfg.get("character") or {}
    body = cfg.get("body") or {}
    action = cfg.get("action") or {}
    clothing = cfg.get("clothing") or {}
    prompt = shot.get("prompt", "")
    negative = join_tags(shot.get("style_negative", style.get("negative", "")),
                         shot.get("negative", ""))
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
        prompt,
        shot.get("style_suffix", style.get("suffix", "")),
    )
    return positive, negative


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
    init_image = str(shot.get("init_image") or "").strip()
    if init_image:
        wf["70"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        wf["72"] = {"class_type": "ImageScale", "inputs": {
            "image": ["70", 0],
            "upscale_method": "lanczos",
            "width": int(settings.get("width", 1024)),
            "height": int(settings.get("height", 1344)),
            "crop": "disabled"}}
        wf["71"] = {"class_type": "VAEEncode", "inputs": {
            "pixels": ["72", 0], "vae": vae}}
        latent = ["71", 0]
    else:
        wf["8"] = {"class_type": "EmptyLatentImage", "inputs": {
            "width": settings.get("width", 1024),
            "height": settings.get("height", 1344),
            "batch_size": 1}}
        latent = ["8", 0]
    add_sampler(wf, cfg, "9", model, ["6", 0], ["7", 0], latent, seed)
    if init_image:
        wf["9"]["inputs"]["denoise"] = float(shot.get("init_denoise", 0.45))
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
        add_sampler(wf, cfg, "13", model, ["6", 0], ["7", 0], ["12", 0], seed, True)
        wf["14"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": vae}}
        final = ["14", 0]

    final = add_detailers(wf, cfg, final, model, clip, vae, ["6", 0], ["7", 0], seed)
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
    if nid == 13:
        return "hires"
    if 60 <= nid < 64:
        return "detail"
    return ""
