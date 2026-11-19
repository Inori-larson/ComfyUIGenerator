from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "comfyui_generator" / "core" / "tagger_runner.py")
spec = importlib.util.spec_from_file_location("tagger_runner_test", RUNNER_PATH)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def test_preprocess_shape_and_black_padding():
    image = Image.new("RGB", (100, 200), (120, 60, 30))
    tensor = tr._preprocess(image, 448, 448, channels_first=False)
    assert tensor.shape == (1, 448, 448, 3)
    assert tensor.dtype == np.float32
    assert float(tensor.max()) <= 255.0
    assert float(tensor.min()) == 0.0
    assert float(tensor[0, 0, 0, 0]) == 0.0


def test_preprocess_channels_first():
    image = Image.new("RGB", (64, 64), (10, 20, 30))
    tensor = tr._preprocess(image, 448, 448, channels_first=True)
    assert tensor.shape == (1, 3, 448, 448)


def test_tag_dict_thresholds_and_underscore_keys():
    names = ["1girl", "nipples", "rating_explicit", "hatsune_miku"]
    cats = [0, 0, 9, 4]
    probs = np.array([0.95, 0.4, 0.8, 0.9])
    tags = tr._tag_dict(names, cats, probs,
                         general_cutoff=0.5, character_cutoff=0.85)
    assert tags["general"] == {"1girl": pytest.approx(0.95)}
    assert tags["rating"]["rating_explicit"] == pytest.approx(0.8)
    assert tags["characters"]["hatsune_miku"] == pytest.approx(0.9)
    assert "nipples" not in tags["general"]
