"""Subprocess helper: interrogate images with a SmilingWolf WD tagger ONNX.

Runs under ComfyUI's Python with onnxruntime/numpy/pillow installed into the
app's own tagger_packages target, so ComfyUI itself is not modified.
Writes one final JSON line on stdout.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image


def _add_extra_dll_dirs() -> None:
    dirs = str(os.environ.get("COMFY_TAGGER_DLL_DIRS") or "")
    for directory in dirs.split(os.pathsep):
        if directory and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(directory)
            except OSError:
                pass


_add_extra_dll_dirs()


def _providers(device: str) -> tuple[list[str], str]:
    import onnxruntime as ort

    available = set(ort.get_available_providers())
    if device == "gpu" and "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"], "gpu"
    return ["CPUExecutionProvider"], "cpu"


def _load_tags(csv_path: str) -> tuple[list[str], list[int]]:
    import csv

    names: list[str] = []
    categories: list[int] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        for row in reader:
            if len(row) < 3:
                continue
            names.append(row[1].strip())
            try:
                categories.append(int(row[2]))
            except ValueError:
                categories.append(0)
    return names, categories


def _preprocess(image: Image.Image, height: int, width: int,
                channels_first: bool) -> np.ndarray:
    canvas = image.convert("RGB")
    scale = 448.0 / max(canvas.width, canvas.height)
    if scale != 1.0:
        canvas = canvas.resize(
            (max(1, round(canvas.width * scale)),
             max(1, round(canvas.height * scale))), Image.BICUBIC)
    square = Image.new("RGB", (width, height), (0, 0, 0))
    square.paste(
        canvas, ((width - canvas.width) // 2, (height - canvas.height) // 2))
    # SmilingWolf WD-v3 ONNX expects raw 0-255 RGB input, not 0-1.
    array = np.asarray(square, dtype=np.float32)[:, :, :3]
    if channels_first:
        array = array.transpose(2, 0, 1)
    return array[np.newaxis, ...]


def _tag_dict(names, categories, probs, general_cutoff,
              character_cutoff) -> dict:
    general: dict[str, float] = {}
    characters: dict[str, float] = {}
    rating: dict[str, float] = {}
    for name, category, prob in zip(names, categories, probs):
        score = float(prob)
        if category == 9:
            rating[name] = score
        elif category == 4:
            if score >= character_cutoff:
                characters[name] = score
        elif category == 0:
            if score >= general_cutoff:
                general[name] = score
    return {"general": general, "rating": rating, "characters": characters}


def main() -> int:
    payload = json.loads(sys.argv[1])
    try:
        import onnxruntime as ort

        device = str(payload.get("device") or "gpu")
        providers, used_device = _providers(device)
        session = ort.InferenceSession(
            str(payload["model"]), providers=providers)
        input_info = session.get_inputs()[0]
        shape = input_info.shape
        size = int(payload.get("size") or 448)
        height = width = size
        channels_first = False
        if isinstance(shape[0], int) and len(shape) == 4:
            c_hw = int(shape[1])
            hw_c_last = int(shape[3])
            if c_hw in (1, 3):
                channels_first = True
                if isinstance(shape[2], int):
                    height, width = int(shape[2]), int(shape[3])
            elif hw_c_last in (1, 3):
                channels_first = False
                if isinstance(shape[1], int):
                    height, width = int(shape[1]), int(shape[2])
        names, categories = _load_tags(str(payload["tags_csv"]))
        # Emit a broad tag set; downstream verifier applies per-check
        # thresholds so cast tags near 0.6 are not silently dropped.
        general_cutoff = min(float(payload.get("general_threshold", 0.35)),
                            float(payload.get("emit_threshold", 0.30)))
        character_cutoff = float(payload.get("character_threshold", 0.85))

        results = []
        for path in payload.get("images") or []:
            try:
                image = Image.open(path)
                tensor = _preprocess(image, height, width, channels_first)
                outputs = session.run(None, {input_info.name: tensor})
                # SmilingWolf v3 ONNX already emits probabilities in [0, 1].
                probs = np.asarray(outputs[0][0], dtype=np.float32)
                probs = np.clip(probs, 0.0, 1.0)
                tags = _tag_dict(names, categories, probs,
                                 general_cutoff, character_cutoff)
                results.append({"path": str(path), "device": used_device,
                                **tags})
            except Exception as exc:
                results.append({"path": str(path), "error": str(exc)})
        print(json.dumps({"results": results, "device": used_device},
                         ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
