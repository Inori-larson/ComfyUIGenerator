"""Device resolution shared by the tagger runner and its tests."""

from __future__ import annotations

from typing import Any


def resolve_device(requested: str, available: list[str],
                   actual: list[str]) -> tuple[str, str]:
    used = "gpu" if "CUDAExecutionProvider" in actual else "cpu"
    warning = ""
    if requested == "gpu" and used == "cpu":
        warning = (
            "CUDAExecutionProvider 未能启用（实际 %s）；"
            "常见原因是缺少 CUDA 13/cuDNN 依赖或显存被 ComfyUI 占满。"
            % ", ".join(actual or available or ["none"]))
    return used, warning


def resolve_providers(device: str, available: Any) -> tuple[list[str], str]:
    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if device == "gpu" and "CUDAExecutionProvider" in set(available)
                 else ["CPUExecutionProvider"])
    return providers, "gpu" if len(providers) > 1 else "cpu"
