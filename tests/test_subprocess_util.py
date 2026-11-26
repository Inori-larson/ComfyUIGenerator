from __future__ import annotations

import subprocess
from pathlib import Path

from comfyui_generator.core import subprocess_util


def test_run_hidden_injects_no_window_flag(monkeypatch):
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess_util.subprocess, "run", fake_run)
    subprocess_util.run_hidden(["echo"])
    assert captured.get("creationflags") == subprocess_util.CREATE_NO_WINDOW


def test_run_hidden_respects_explicit_flags(monkeypatch):
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess_util.subprocess, "run", fake_run)
    subprocess_util.run_hidden(["echo"], creationflags=123)
    assert captured["creationflags"] == 123


def test_tagger_and_vision_have_no_bare_subprocess_run():
    root = Path(subprocess_util.__file__).resolve().parent
    for name in ("tagger.py", "vision.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "subprocess.run(" not in text
