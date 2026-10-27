"""ADetailer-style repaint passes driven by scanned detector models.

The list is never hardcoded: any ``.pt`` model under ``models/ultralytics``
(bbox or segm) becomes a selectable repaint pass. Preset prompts are chosen by
filename keywords, with a generic fallback for unknown models.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# key, detector filename keywords, label, focus prompt, denoise, guide size
DETECTOR_PRESETS = [
    ("face", ["face"], "脸部重绘", "detailed face, beautiful detailed eyes, sharp focus", 0.35, 1024),
    ("eyes", ["eye", "iris"], "眼睛重绘",
     "beautiful detailed eyes, sharp pupils, detailed iris, sparkling eyes", 0.25, 512),
    ("mouth", ["mouth", "lip"], "嘴巴重绘",
     "detailed lips, beautiful mouth, natural expression", 0.25, 512),
    ("expression", ["expression"], "表情重绘",
     "expressive face, emotional expression, detailed eyes", 0.45, 768),
    ("hand", ["hand"], "手部重绘", "detailed hands, perfect hands, five fingers", 0.40, 768),
    ("person", ["person", "body"], "人物重绘", "detailed body, perfect anatomy", 0.35, 1024),
]


def _preset_for(detector: str) -> dict[str, Any]:
    low = detector.lower()
    stem = Path(detector).stem
    for key, keywords, label, prompt, denoise, guide in DETECTOR_PRESETS:
        if any(keyword in low for keyword in keywords):
            return {
                "kind": key,
                "label": "%s · %s" % (label, stem),
                "prompt": prompt,
                "denoise": denoise,
                "guide_size": guide,
            }
    return {
        "kind": stem,
        "label": "重绘 · %s" % stem,
        "prompt": "detailed %s" % stem.replace("_", " ").replace("-", " "),
        "denoise": 0.35,
        "guide_size": 1024,
    }


def build_detailer_choices(detectors: list[str]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for detector in detectors:
        normalized = str(detector).replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        preset = _preset_for(normalized)
        choices.append({
            "key": normalized,
            "kind": preset["kind"],
            "detector": normalized,
            "label": preset["label"],
            "prompt": preset["prompt"],
            "denoise": preset["denoise"],
            "guide_size": preset["guide_size"],
            "dedicated": True,
        })
    return choices


def resolve_detailers(spec: str, detectors: list[str]) -> list[dict[str, Any]]:
    if not spec.strip():
        return []
    choices = build_detailer_choices(detectors)
    by_key = {choice["key"]: choice for choice in choices}
    by_stem = {Path(choice["detector"]).stem.lower(): choice for choice in choices}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for token in spec.replace("，", ",").split(","):
        key = token.strip().lower()
        if not key or key == "none":
            continue
        choice = by_key.get(key) or by_stem.get(key)
        if choice is None:
            for candidate in choices:
                if key in candidate["detector"].lower():
                    choice = candidate
                    break
        if choice and choice["key"] not in seen:
            seen.add(choice["key"])
            result.append(dict(choice))
    return result


def local_detectors(base_dir: str | Path | None) -> list[str]:
    """Fallback scan for CLI use when ComfyUI is not connected."""
    if not base_dir:
        return []
    root = Path(base_dir) / "models" / "ultralytics"
    found: list[str] = []
    for kind in ("bbox", "segm"):
        folder = root / kind
        if folder.is_dir():
            for path in sorted(folder.glob("*.pt")):
                found.append("%s/%s" % (kind, path.name))
    return found
