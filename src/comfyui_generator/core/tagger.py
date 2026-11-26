"""Optional WD14/WD-v3 booru tagger for post-render visual verification.

Mirrors vision.py: dependencies install into the app data folder and inference
runs in ComfyUI's Python subprocess, so the main environment stays untouched.
This module only interrogates rendered images; it never rewrites prompts.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

from comfyui_generator.core.subprocess_util import run_hidden

TAGGER_REPO = "SmilingWolf/wd-eva02-large-tagger-v3"
TAGGER_FILES = ("model.onnx", "selected_tags.csv")

GENERAL_THRESHOLD = 0.55
CHARACTER_THRESHOLD = 0.85


def tagger_packages_dir(root: Path) -> Path:
    return root / "tagger_packages"


def find_tagger_model(base_dir: str | Path | None,
                      configured: str | Path | None = None) -> Path | None:
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        if path.is_dir():
            found = _model_in_dir(path)
            if found:
                return found
    candidates: list[Path] = []
    if base_dir:
        folder = Path(base_dir) / "models" / "tagger"
        if folder.is_dir():
            candidates.append(folder)
    return _model_in_dirs(candidates)


def _model_in_dir(folder: Path) -> Path | None:
    return _model_in_dirs([folder])


def _model_in_dirs(folders: list[Path]) -> Path | None:
    best: Path | None = None
    best_size = -1
    for folder in folders:
        for path in folder.glob("*.onnx"):
            size = path.stat().st_size
            if size > best_size:
                best, best_size = path, size
    return best


def _tags_csv_for(model_path: Path) -> Path | None:
    sibling = model_path.with_name("selected_tags.csv")
    if sibling.is_file():
        return sibling
    return None


def tagger_ready(root: Path, python: str, base_dir: str | Path | None,
                 model_path: str | Path | None = None) -> tuple[bool, str]:
    if not python or not Path(python).is_file():
        return False, "没有找到 ComfyUI Python"
    model = find_tagger_model(base_dir, model_path)
    if model is None:
        return False, "没有找到 WD tagger ONNX 模型"
    if _tags_csv_for(model) is None:
        return False, "缺少 tagger 的 selected_tags.csv"
    if (tagger_packages_dir(root) / "onnxruntime").is_dir():
        return True, ""
    probe = run_hidden(
        [python, "-c", "import onnxruntime, numpy, PIL"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode == 0:
        return True, ""
    return False, "首次使用需要安装 onnxruntime 依赖"


def ensure_tagger_packages(python: str, target: str | Path,
                           gpu: bool = True,
                           log: Callable[[str], None] | None = None,
                           timeout: float = 1800.0) -> None:
    target = Path(target)
    if (target / "onnxruntime").is_dir():
        return
    if not python or not Path(python).is_file():
        raise RuntimeError("没有找到可用的 ComfyUI Python")
    target.mkdir(parents=True, exist_ok=True)
    package = "onnxruntime-gpu" if gpu else "onnxruntime"
    if log:
        log("首次安装标签反推依赖 %s（仅安装到应用数据目录）..." % package)
    cmd = [python, "-m", "pip", "install", "--target", str(target),
           package, "numpy", "pillow"]
    proc = run_hidden(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)
    if proc.returncode != 0:
        if gpu:
            cmd = [python, "-m", "pip", "install", "--target", str(target),
                   "onnxruntime", "numpy", "pillow"]
            proc = run_hidden(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            raise RuntimeError("onnxruntime 安装失败：%s" % detail)
    if log:
        log("tagger 依赖已安装。")


def download_tagger_model(directory: str | Path,
                          repo: str = TAGGER_REPO,
                          hf_base: str = "https://huggingface.co",
                          log: Callable[[str], None] | None = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    base = hf_base.rstrip("/")
    for filename in TAGGER_FILES:
        dest = directory / filename
        if dest.is_file() and dest.stat().st_size > 0:
            continue
        url = "%s/%s/resolve/main/%s" % (base, repo, filename)
        if log:
            log("下载 %s ..." % filename)
        request = urllib.request.Request(url, headers={"User-Agent": "ComfyUIGenerator"})
        with urllib.request.urlopen(request, timeout=600) as response:
            dest.write_bytes(response.read())
    model = directory / "model.onnx"
    if not model.is_file():
        raise RuntimeError("tagger 模型下载失败")
    return model


def run_tagger(python: str, root: Path, base_dir: str | Path | None,
               images: list[str | Path],
               model_path: str | Path | None = None,
               device: str = "gpu",
               general_threshold: float = GENERAL_THRESHOLD,
               character_threshold: float = CHARACTER_THRESHOLD,
               log: Callable[[str], None] | None = None,
               timeout: float = 1800.0) -> list[dict[str, Any]]:
    model = find_tagger_model(base_dir, model_path)
    if model is None:
        raise RuntimeError("没有找到 WD tagger ONNX 模型")
    tags_csv = _tags_csv_for(model)
    if tags_csv is None:
        raise RuntimeError("缺少 tagger 的 selected_tags.csv")
    packages = tagger_packages_dir(root)
    probe = run_hidden(
        [python or sys.executable, "-c", "import onnxruntime"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        ensure_tagger_packages(python, packages, gpu=(device == "gpu"), log=log)
    runner = Path(__file__).with_name("tagger_runner.py")
    payload = {
        "model": str(model),
        "tags_csv": str(tags_csv),
        "images": [str(path) for path in images],
        "device": device,
        "general_threshold": general_threshold,
        "character_threshold": character_threshold,
    }
    env = os.environ.copy()
    extra_paths = [str(packages)]
    # onnxruntime-gpu needs CUDA cuBLAS; reuse torch's bundled CUDA DLLs when
    # available so a separate CUDA toolkit install is not required.
    try:
        probe = run_hidden(
            [python, "-c",
             "import importlib.util,os;s=importlib.util.find_spec('torch');"
             "print(os.path.join(os.path.dirname(s.origin),'lib') if s else '')"],
            capture_output=True, text=True, timeout=60)
        torch_lib = probe.stdout.strip()
        if torch_lib and Path(torch_lib).is_dir():
            extra_paths.append(torch_lib)
    except Exception:
        pass
    joined = os.pathsep.join(extra_paths)
    env["PYTHONPATH"] = joined + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PATH"] = joined + (os.pathsep + env["PATH"] if env.get("PATH") else "")
    env["COMFY_TAGGER_DLL_DIRS"] = joined
    env.setdefault("PYTHONIOENCODING", "utf-8")

    def _normalise(data: dict[str, Any]) -> list[dict[str, Any]]:
        results = list(data.get("results") or [])
        for item in results:
            for key in ("general", "rating", "characters"):
                bucket = item.get(key)
                if isinstance(bucket, dict):
                    item[key] = {str(name).replace("_", " "): score
                                 for name, score in bucket.items()}
        return results

    def _invoke(use_device: str) -> tuple[list[dict[str, Any]], str, str]:
        payload["device"] = use_device
        proc = run_hidden(
            [python or sys.executable, str(runner),
             json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, cwd=str(Path.home()))
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            if not detail:
                detail = ("子进程退出码 %s 且无错误输出（python=%s，图片=%d，device=%s，"
                          "常见于 GPU/CUDA 原生库初始化失败）"
                          % (proc.returncode, python, len(images), use_device))
            raise RuntimeError("WD tagger 检测失败：%s" % detail)
        out_lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if not out_lines:
            raise RuntimeError("WD tagger 没有输出")
        try:
            data = json.loads(out_lines[-1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "WD tagger 输出无法解析：%s" % out_lines[-1][:500]) from exc
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return (_normalise(data),
                str(data.get("device") or ""),
                str(data.get("provider_warning") or ""))

    try:
        results, used_device, warning = _invoke(device)
    except RuntimeError as exc:
        if device == "gpu":
            if log:
                log("GPU 反推失败（%s），改用 CPU 重试一次。" % str(exc)[:300])
            return _invoke("cpu")[0]
        raise
    if device == "gpu" and used_device and used_device != "gpu":
        if log:
            log("WD tagger GPU 未生效：%s（本批结果来自 CPU）"
                % (warning or "CUDAExecutionProvider 不可用"))
    return results
