"""ADetailer-style repaint pass presets."""

from __future__ import annotations

import os
from typing import Any

DETAILER_SPECS = [
    ("face", "脸部重绘", ["face"], "detailed face, beautiful detailed eyes, sharp focus", 0.35, 1024),
    ("eyes", "眼睛重绘", ["eye", "iris"], "beautiful detailed eyes, sharp pupils, detailed iris, sparkling eyes", 0.25, 512),
    ("mouth", "嘴巴重绘", ["mouth", "lip"], "detailed lips, beautiful mouth, natural expression", 0.25, 512),
    ("expression", "表情重绘", ["expression"], "expressive face, emotional expression, detailed eyes", 0.45, 768),
    ("hand", "手部重绘", ["hand"], "detailed hands, perfect hands, five fingers", 0.40, 768),
]

FALLBACK = {
    "face": "bbox/face_yolov8n.pt",
    "hand": "bbox/hand_yolov8n.pt",
}


def _pick(detectors: list[str], keywords: list[str]) -> str | None:
    for keyword in keywords:
        for detector in detectors:
            low = detector.lower()
            if keyword in low and "segm" not in low:
                return detector
    return None


def build_detailer_choices(detectors: list[str]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for key, label, keywords, prompt, denoise, guide in DETAILER_SPECS:
        detector = (_pick(detectors, keywords)
                    or _pick(detectors, ["face"])
                    or FALLBACK.get(key)
                    or FALLBACK.get("face"))
        if not detector:
            continue
        dedicated = any(keyword in detector.lower() for keyword in keywords)
        choices.append({
            "key": key,
            "label": label,
            "detector": detector,
            "dedicated": dedicated,
            "prompt": prompt,
            "denoise": denoise,
            "guide_size": guide,
        })
    return choices


def resolve_detailers(spec: str, detectors: list[str]) -> list[dict[str, Any]]:
    if not spec.strip():
        return []
    choices = {choice["key"]: choice for choice in build_detailer_choices(detectors)}
    result: list[dict[str, Any]] = []
    for token in spec.replace("，", ",").split(","):
        key = token.strip().lower()
        if not key or key == "none":
            continue
        choice = choices.get(key)
        if choice is None:
            # allow a raw detector path
            if any(key in detector.lower() for detector in detectors):
                choice = {
                    "key": os.path.splitext(os.path.basename(key))[0],
                    "label": key,
                    "detector": key,
                    "dedicated": True,
                    "prompt": "",
                    "denoise": 0.35,
                    "guide_size": 1024,
                }
        if choice:
            result.append(dict(choice))
    return result
