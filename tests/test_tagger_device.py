from __future__ import annotations

from comfyui_generator.core.tagger_device import resolve_device


def test_gpu_requested_and_actually_used():
    used, warning = resolve_device(
        "gpu", ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert used == "gpu"
    assert warning == ""


def test_gpu_requested_but_cpu_used_returns_warning():
    used, warning = resolve_device(
        "gpu", ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ["CPUExecutionProvider"])
    assert used == "cpu"
    assert "CUDAExecutionProvider" in warning
    assert "CPUExecutionProvider" in warning


def test_cpu_requested_stays_quiet():
    used, warning = resolve_device("cpu", ["CPUExecutionProvider"],
                                    ["CPUExecutionProvider"])
    assert used == "cpu"
    assert warning == ""

