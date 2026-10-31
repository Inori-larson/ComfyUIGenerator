"""Optional CLIP-based character/visual consistency scoring.

The scorer runs in ComfyUI's Python environment because that environment
already has torch/PIL.  open_clip is installed into the app's own data folder,
so ComfyUI itself is not modified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

WARN_SCORE = 0.55
BAD_SCORE = 0.40


def vision_packages_dir(root: Path) -> Path:
    return root / "vision_packages"


def find_clip_vision_model(base_dir: str | Path | None) -> Path | None:
    if not base_dir:
        return None
    folder = Path(base_dir) / "models" / "clip_vision"
    if not folder.is_dir():
        return None
    candidates = [
        path for path in folder.glob("*.safetensors")
        if "vit-h" in path.name.lower() or "vit_h" in path.name.lower()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def vision_ready(root: Path, python: str, base_dir: str | Path | None) -> tuple[bool, str]:
    if not python or not Path(python).is_file():
        return False, "没有找到 ComfyUI Python"
    model = find_clip_vision_model(base_dir)
    if model is None:
        return False, "没有找到 CLIP-ViT-H 视觉模型"
    if not (vision_packages_dir(root) / "open_clip").is_dir():
        return False, "首次使用需要安装 open_clip 依赖"
    return True, ""


def ensure_vision_packages(python: str, target: str | Path,
                           log: Callable[[str], None] | None = None,
                           timeout: float = 900.0) -> None:
    target = Path(target)
    if (target / "open_clip").is_dir():
        return
    if not python or not Path(python).is_file():
        raise RuntimeError("没有找到可用的 ComfyUI Python")
    target.mkdir(parents=True, exist_ok=True)
    if log:
        log("首次安装角色相似度依赖 open_clip（仅安装到应用数据目录）...")
    cmd = [
        python, "-m", "pip", "install", "--no-deps", "--target", str(target),
        "open_clip_torch", "ftfy", "regex", "timm", "wcwidth",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise RuntimeError("open_clip 安装失败：%s" % detail)
    if log:
        log("open_clip 依赖已安装。")


def run_similarity(python: str, root: Path, base_dir: str | Path | None,
                   reference: str | Path, images: list[str | Path],
                   device: str = "cpu", timeout: float = 900.0) -> list[dict[str, Any]]:
    model = find_clip_vision_model(base_dir)
    if model is None:
        raise RuntimeError("没有找到 CLIP-ViT-H 视觉模型")
    packages = vision_packages_dir(root)
    ensure_vision_packages(python, packages)
    runner = Path(__file__).with_name("vision_runner.py")
    payload = {
        "model": str(model),
        "reference": str(reference),
        "images": [str(path) for path in images],
        "device": device,
    }
    env = os.environ.copy()
    env["PYTHONPATH"] = str(packages) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [python or sys.executable, str(runner), json.dumps(payload, ensure_ascii=False)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise RuntimeError("CLIP 相似度检测失败：%s" % detail)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("CLIP 相似度检测没有输出")
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("CLIP 输出无法解析：%s" % lines[-1][:500]) from exc
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return list(data.get("scores") or [])


def format_similarity(scores: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in scores:
        path = Path(str(item.get("path") or ""))
        score = item.get("score")
        if score is None:
            lines.append("%s · 检测失败 %s" % (path.name, item.get("error", "")))
            continue
        value = float(score)
        if value < BAD_SCORE:
            mark = "严重偏低"
        elif value < WARN_SCORE:
            mark = "偏低"
        else:
            mark = "正常"
        lines.append("%s · %.3f · %s" % (path.name, value, mark))
    return "\n".join(lines) or "没有可检测的图片。"
