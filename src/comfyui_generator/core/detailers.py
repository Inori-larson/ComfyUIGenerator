"""ADetailer-style repaint passes driven by scanned detector models.

The list is never hardcoded: every valid detector model under
``models/ultralytics`` becomes a selectable repaint pass. LoRA/embedding
files are ignored because Ultralytics cannot load them as detectors. Preset
prompts are chosen by filename keywords, with a generic fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DETECTOR_SUFFIXES = {".pt", ".pth", ".onnx", ".engine", ".torchscript", ".tflite", ".safetensors"}
LORA_PREFIXES = ("lora_", "lora.", "diffusion_model.", "emb_params")

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


def _safetensors_keys(path: Path) -> list[str]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(8)
            if len(raw) != 8:
                return []
            size = int.from_bytes(raw, "little")
            if size <= 0 or size > 64 * 1024 * 1024:
                return []
            header = json.loads(handle.read(size).decode("utf-8"))
        return [key for key in header if key != "__metadata__"]
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return []


def _is_detector_file(path: Path) -> bool:
    if path.suffix.lower() not in DETECTOR_SUFFIXES:
        return False
    if path.suffix.lower() != ".safetensors":
        return True
    keys = _safetensors_keys(path)
    if not keys:
        return False
    lower = [key.lower() for key in keys]
    return not any(key.startswith(LORA_PREFIXES) or key.endswith(".alpha") or ".lora_" in key
                   for key in lower)


def filter_detector_models(base_dir: str | Path | None, detectors: list[str]) -> list[str]:
    if not base_dir:
        return [name for name in detectors if Path(name).suffix.lower() != ".safetensors"]
    root = Path(base_dir) / "models" / "ultralytics"
    result: list[str] = []
    for name in detectors:
        path = root / Path(name)
        if path.is_file() and _is_detector_file(path):
            result.append(name)
    return result


def local_detectors(base_dir: str | Path | None) -> list[str]:
    """Fallback scan for CLI use when ComfyUI is not connected."""
    if not base_dir:
        return []
    root = Path(base_dir) / "models" / "ultralytics"
    if not root.is_dir():
        return []
    return [path.relative_to(root).as_posix() for path in sorted(root.rglob("*"))
            if path.is_file() and _is_detector_file(path)]
