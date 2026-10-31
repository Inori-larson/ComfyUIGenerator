import sys
from pathlib import Path

from comfyui_generator.core.vision import (
    BAD_SCORE, WARN_SCORE, find_clip_vision_model, format_similarity,
    vision_ready,
)


def test_find_clip_vision_model_prefers_largest(tmp_path):
    folder = tmp_path / "models" / "clip_vision"
    folder.mkdir(parents=True)
    small = folder / "CLIP-ViT-H-14-small.safetensors"
    large = folder / "CLIP-ViT-H-14-large.safetensors"
    small.write_bytes(b"a")
    large.write_bytes(b"b" * 10)
    assert find_clip_vision_model(tmp_path) == large


def test_find_clip_vision_model_missing(tmp_path):
    assert find_clip_vision_model(tmp_path) is None


def test_find_clip_vision_model_rejects_other_architectures(tmp_path):
    folder = tmp_path / "models" / "clip_vision"
    folder.mkdir(parents=True)
    (folder / "CLIP-ViT-L-14.safetensors").write_bytes(b"a")
    assert find_clip_vision_model(tmp_path) is None


def test_vision_ready_reports_missing_python(tmp_path):
    ready, reason = vision_ready(tmp_path, "", tmp_path)
    assert not ready
    assert "Python" in reason


def test_vision_ready_reports_missing_model(tmp_path):
    ready, reason = vision_ready(tmp_path, sys.executable, tmp_path)
    assert not ready
    assert "CLIP" in reason


def test_format_similarity_thresholds(tmp_path):
    scores = [
        {"path": str(tmp_path / "ok.png"), "score": WARN_SCORE + 0.1},
        {"path": str(tmp_path / "warn.png"), "score": WARN_SCORE - 0.01},
        {"path": str(tmp_path / "bad.png"), "score": BAD_SCORE - 0.01},
        {"path": str(tmp_path / "fail.png"), "score": None, "error": "no face"},
    ]
    text = format_similarity(scores)
    assert "正常" in text
    assert "偏低" in text
    assert "严重偏低" in text
    assert "检测失败" in text


def test_format_similarity_empty():
    assert format_similarity([]) == "没有可检测的图片。"
