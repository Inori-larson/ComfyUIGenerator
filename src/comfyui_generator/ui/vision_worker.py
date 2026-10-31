"""Background worker for optional CLIP character-consistency scoring."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from comfyui_generator.core.config import AppConfig
from comfyui_generator.core.vision import run_similarity


class VisionWorker(QThread):
    done = Signal(list)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, reference: str | Path,
                 images: list[str | Path], device: str = "cpu"):
        super().__init__()
        self.cfg = cfg
        self.reference = reference
        self.images = images
        self.device = device

    def run(self) -> None:
        try:
            self.log.emit("正在加载 CLIP 视觉模型并检测角色一致性...")
            scores = run_similarity(
                self.cfg.comfy.python, self.cfg.root, self.cfg.comfy.base_dir,
                self.reference, self.images, device=self.device,
                timeout=900.0)
            self.done.emit(scores)
        except Exception as exc:
            self.failed.emit(str(exc))
