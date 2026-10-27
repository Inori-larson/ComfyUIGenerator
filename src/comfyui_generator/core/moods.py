"""Lighting / mood presets shared by CLI and UI."""

from __future__ import annotations

MOODS: dict[str, tuple[str, str, str]] = {
    "bright": (
        "明亮欢快（推荐）",
        "bright daylight, sunny, vivid colors, clear sky, cheerful atmosphere, sharp focus",
        "dark, gloomy, low light, overcast, rainy, blurry",
    ),
    "cozy": (
        "温馨日常",
        "warm soft lighting, cozy, pastel colors, gentle atmosphere",
        "",
    ),
    "outdoor": (
        "清爽户外",
        "outdoor, blue sky, gentle sunlight, fresh air, vivid colors",
        "dark, gloomy, low light",
    ),
    "energetic": (
        "活力动感",
        "dynamic lighting, vibrant colors, energetic atmosphere, motion",
        "",
    ),
    "none": ("不限制（完全按剧情）", "", ""),
}


def resolve_mood(value: str | None) -> tuple[str, str]:
    key = (value or "bright").strip()
    if key in MOODS:
        return MOODS[key][1], MOODS[key][2]
    return key, ""
