"""Resource discovery through ComfyUI /object_info plus local preset tags."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from comfyui_generator.core.comfy import ComfyClient, ComfyError


def _options(info: dict[str, Any], node: str, field: str) -> list[str]:
    spec = (((info.get(node) or {}).get("input") or {}).get("required") or {}).get(field)
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    # legacy format: [ [ "a", "b" ], {...} ]
    if isinstance(spec[0], list):
        return [str(x) for x in spec[0]]
    # ComfyUI 0.4x format: [ "COMBO", { "options": [ ... ] } ]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return [str(x) for x in (spec[1].get("options") or [])]
    return []


class Assets:
    """Cached lists of selectable resources exposed by ComfyUI."""

    def __init__(self, client: ComfyClient | None = None):
        self.client = client
        self.checkpoints: list[str] = []
        self.loras: list[str] = []
        self.upscalers: list[str] = []
        self.detectors: list[str] = []
        self.samplers: list[str] = []
        self.schedulers: list[str] = []
        self.unets: list[str] = []
        self.clips: list[str] = []
        self.vaes: list[str] = []
        self.missing_nodes: list[str] = []
        self.error: str | None = None

    def refresh(self) -> "Assets":
        if self.client is None:
            self.error = "No ComfyUI client"
            return self
        try:
            info = self.client.object_info()
        except ComfyError as exc:
            self.error = str(exc)
            return self
        self.error = None
        self.checkpoints = _options(info, "CheckpointLoaderSimple", "ckpt_name")
        self.loras = _options(info, "LoraLoaderModelOnly", "lora_name")
        self.upscalers = _options(info, "UpscaleModelLoader", "model_name")
        self.detectors = _options(info, "UltralyticsDetectorProvider", "model_name")
        self.samplers = _options(info, "KSampler", "sampler_name")
        self.schedulers = _options(info, "KSampler", "scheduler")
        self.unets = _options(info, "UNETLoader", "unet_name")
        self.clips = _options(info, "CLIPLoader", "clip_name")
        self.vaes = _options(info, "VAELoader", "vae_name")
        needed = ["FaceDetailer", "UltralyticsDetectorProvider", "IPAdapterAdvanced",
                  "IPAdapterUnifiedLoader"]
        self.missing_nodes = [name for name in needed if name not in info]
        return self

    def status(self) -> dict[str, Any]:
        return {
            "checkpoints": len(self.checkpoints),
            "loras": len(self.loras),
            "upscalers": len(self.upscalers),
            "detectors": len(self.detectors),
            "missing_nodes": list(self.missing_nodes),
            "error": self.error,
        }


def find_preset_tags(lora_name: str, workflows_dir: str | Path) -> str:
    """Find character tags for a LoRA from existing storyboard JSON files."""
    if not lora_name:
        return ""
    root = Path(workflows_dir)
    if not root.is_dir():
        return ""
    for path in root.rglob("storyboard*.json"):
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        lora = cfg.get("lora") or {}
        if lora.get("name") == lora_name:
            tags = (cfg.get("character") or {}).get("tags") or ""
            if tags:
                return tags
    return ""
