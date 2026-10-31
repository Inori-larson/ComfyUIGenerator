"""Optional visual style presets.

Each profile carries both prompt text and a recommended model setup.  The UI
applies that setup when the user picks a profile, and the default profile keeps
a known baseline so users can switch back without manually undoing changes.
"""

from __future__ import annotations

import copy
from typing import Any

STYLE_PROFILES: dict[str, dict[str, Any]] = {
    "none": {
        "label": "默认配置（恢复基础设置）",
        "description": (
            "恢复内置基础配置：WAI Illustrious、Anime6B 放大、1024x1344、"
            "30 步、CFG 5、euler_ancestral/normal。不注入风格提示词。"
        ),
        "positive": "",
        "negative": "",
        "suffix": "",
        "recommended": "WAI Illustrious / RealESRGAN Anime6B",
        "apply": {
            "checkpoint_hints": ["waiIllustriousSDXL_v170", "waiIllustrious"],
            "upscaler_hints": ["RealESRGAN_x4plus_anime_6B"],
            "style_lora_hints": [],
            "style_lora_strength": 0.0,
            "width": 1024,
            "height": 1344,
            "steps": 30,
            "cfg": 5.0,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "hires": {"enabled": True, "scale": 1.5, "denoise": 0.4, "steps": 20},
        },
    },
    "tv_anime": {
        "label": "TV 动画 / 赛璐璐",
        "description": (
            "适合连续动画剧情图。选中后会尝试自动切换二次元底模、"
            "Anime Screencap 风格 LoRA 和 Anime6B 放大模型。"
            "缺失的模型会保留当前设置并提示。"
        ),
        "positive": (
            "anime screencap, tv anime, cel shading, clean lineart, flat color, "
            "consistent character design, detailed background, cinematic composition"
        ),
        "negative": (
            "photorealistic, 3d, cgi, realistic skin texture, western cartoon, "
            "sketch, rough lineart"
        ),
        "suffix": "consistent character design",
        "recommended": "Anime Screencap / 二次元底模 / RealESRGAN Anime6B",
        "apply": {
            "checkpoint_hints": ["waiIllustriousSDXL_v170", "waiIllustrious"],
            "upscaler_hints": ["RealESRGAN_x4plus_anime_6B"],
            "style_lora_hints": [
                "anime_screencap-IllustriousV2",
                "fine_anime_screencap",
            ],
            "style_lora_strength": 0.5,
            "width": 1024,
            "height": 1344,
            "steps": 30,
            "cfg": 5.0,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "hires": {"enabled": True, "scale": 1.5, "denoise": 0.4, "steps": 20},
        },
    },
    "live_action": {
        "label": "真人电影 / 剧照",
        "description": (
            "适合真人连续剧情图。选中后会尝试切换写实底模、写实放大模型，"
            "并清空动漫风格 LoRA。缺失的写实模型会保留当前设置并提示。"
        ),
        "positive": (
            "cinematic film still, photorealistic, realistic skin texture, "
            "natural lighting, 35mm photograph, shallow depth of field, "
            "detailed background, cinematic composition"
        ),
        "negative": (
            "anime, cartoon, illustration, painting, 3d render, cgi, "
            "plastic skin, oversaturated, low quality"
        ),
        "suffix": "cinematic composition",
        "recommended": "写实 SDXL 底模 / 4x-UltraSharp / FaceDetailer",
        "apply": {
            "checkpoint_hints": [
                "realvis", "juggernaut", "epicrealism", "chilloutmix",
                "majicmix", "cyberrealistic",
            ],
            "upscaler_hints": [
                "4x-UltraSharp", "4x_UltraSharp", "4x_foolhardy", "4x_NMKD",
            ],
            "style_lora_hints": [],
            "style_lora_strength": 0.0,
            "width": 1024,
            "height": 1344,
            "steps": 30,
            "cfg": 5.0,
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
            "hires": {"enabled": True, "scale": 1.5, "denoise": 0.35, "steps": 20},
        },
    },
    "illustration": {
        "label": "插画 / 厚涂",
        "description": (
            "适合插画风连续剧情图。选中后会尝试切换插画向底模和风格 LoRA；"
            "缺失的模型会保留当前设置并提示。"
        ),
        "positive": (
            "digital illustration, painterly, detailed shading, rich color, "
            "consistent character design, cinematic composition"
        ),
        "negative": (
            "photorealistic, 3d, cgi, flat color, sketch, low quality"
        ),
        "suffix": "consistent character design",
        "recommended": "插画底模 / 风格 LoRA",
        "apply": {
            "checkpoint_hints": ["illustrious", "animagine", "noobai"],
            "upscaler_hints": ["4x-UltraSharp", "4x_UltraSharp", "4x_foolhardy"],
            "style_lora_hints": ["painterly", "illustration"],
            "style_lora_strength": 0.45,
            "width": 1024,
            "height": 1344,
            "steps": 30,
            "cfg": 5.0,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "hires": {"enabled": True, "scale": 1.5, "denoise": 0.4, "steps": 20},
        },
    },
}

STYLE_PROFILE_CHOICES: list[tuple[str, str]] = [
    (profile["label"], profile_id)
    for profile_id, profile in STYLE_PROFILES.items()
]


def get_style_profile(profile_id: str) -> dict[str, Any]:
    return STYLE_PROFILES.get(profile_id) or STYLE_PROFILES["none"]


def normalize_style_profile(value: Any) -> dict[str, Any]:
    """Return a stable selection dict, tolerating old/missing projects."""
    data = value if isinstance(value, dict) else {}
    profile_id = str(data.get("id") or "none")
    if profile_id not in STYLE_PROFILES:
        profile_id = "none"
    return {
        "id": profile_id,
        "use_prompt": bool(data.get("use_prompt", True)),
        "use_negative": bool(data.get("use_negative", True)),
        "use_suffix": bool(data.get("use_suffix", True)),
    }


def _merge_tags(*parts: Any) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        for token in str(part).split(","):
            tag = token.strip()
            key = tag.lower()
            if tag and key not in seen:
                seen.add(key)
                values.append(tag)
    return ", ".join(values)


def apply_style_profile(style: dict[str, Any] | None,
                        selection: Any) -> dict[str, Any]:
    """Return a copy of ``style`` with the selected profile applied."""
    result = dict(style or {})
    chosen = normalize_style_profile(selection)
    profile = get_style_profile(chosen["id"])
    if chosen["id"] == "none":
        return result
    if chosen["use_prompt"]:
        result["positive"] = _merge_tags(
            result.get("positive", ""), profile.get("positive", ""))
    if chosen["use_negative"]:
        result["negative"] = _merge_tags(
            result.get("negative", ""), profile.get("negative", ""))
    if chosen["use_suffix"]:
        result["suffix"] = _merge_tags(
            result.get("suffix", ""), profile.get("suffix", ""))
    return result


def style_profile_positive(selection: Any) -> str:
    chosen = normalize_style_profile(selection)
    if chosen["id"] == "none" or not chosen["use_prompt"]:
        return ""
    return str(get_style_profile(chosen["id"]).get("positive") or "")


def style_profile_apply_settings(selection: Any) -> dict[str, Any]:
    """Return the recommended setup for the selected profile.

    The default profile also has a setup, so choosing it restores a known
    baseline instead of leaving the previous profile's models in place.
    """
    chosen = normalize_style_profile(selection)
    return copy.deepcopy(get_style_profile(chosen["id"]).get("apply") or {})
