"""Background worker for optional WD tagger post-render verification."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from comfyui_generator.core.config import AppConfig
from comfyui_generator.core.tagger import run_tagger
from comfyui_generator.core.trace import start_trace, stop_trace, trace_event


class TaggerWorker(QThread):
    done = Signal(list)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, images: list[str | Path],
                 device: str = "gpu", meta: dict | None = None):
        super().__init__()
        self.cfg = cfg
        self.images = images
        self.device = device
        self.meta = meta or {}

    def run(self) -> None:
        t = self.cfg.tagger
        trace = token = None
        try:
            trace, token = start_trace(
                self.cfg.single_projects_dir.parent / "log", "verify",
                {"images": len(self.images), "device": self.device,
                 **self.meta})
            trace_event("verify.start", {"images": len(self.images)})
            self.log.emit("正在加载 WD tagger 并反推 %d 张标签..."
                          % len(self.images))
            results = run_tagger(
                self.cfg.comfy.python, self.cfg.root, self.cfg.comfy.base_dir,
                self.images,
                model_path=t.model_path or None,
                device=self.device or t.device,
                general_threshold=t.general_threshold,
                log=self.log.emit,
                timeout=1800.0)
            errors = [r for r in results if r.get("error")]
            trace_event("verify.tagger_done",
                        {"ok": len(results) - len(errors),
                         "errors": len(errors),
                         "device": results[0].get("device") if results else ""})
            self.done.emit(results)
        except Exception as exc:
            trace_event("verify.failed", {"error": repr(exc)})
            self.failed.emit(str(exc))
        finally:
            if trace is not None:
                stop_trace(trace, token)
