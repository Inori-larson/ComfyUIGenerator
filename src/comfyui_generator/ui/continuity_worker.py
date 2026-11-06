"""Background worker for LLM continuity extraction."""

from __future__ import annotations

import copy

from PySide6.QtCore import QThread, Signal

from comfyui_generator.core.auto_continuity import extract_continuity
from comfyui_generator.core.config import AppConfig
from comfyui_generator.core.external_llm import (
    ExternalLLMClient,
    resolve_external_model,
)
from comfyui_generator.core.ollama import OllamaClient


class ContinuityWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, premise: str,
                 shots: list[dict], character_tags: str,
                 model: str, use_external: bool):
        super().__init__()
        self.cfg = cfg
        self.premise = premise
        self.shots = copy.deepcopy(shots)
        self.character_tags = character_tags
        self.model = model
        self.use_external = use_external

    def run(self) -> None:
        client = None
        model = self.model
        if self.use_external:
            client = ExternalLLMClient(self.cfg.external_llm)
            model = resolve_external_model(self.cfg.external_llm, model)
        else:
            client = OllamaClient(self.cfg.ollama.base_url)
            model = model or self.cfg.ollama.default_model
        try:
            try:
                result = extract_continuity(
                    client, model, self.premise, self.shots,
                    self.character_tags, log=self.log.emit)
            except Exception:
                if not self.use_external or not self.cfg.ollama.default_model:
                    raise
                self.log.emit("外部模型提取失败，改用本地 Ollama。")
                client = OllamaClient(self.cfg.ollama.base_url)
                model = self.cfg.ollama.default_model
                result = extract_continuity(
                    client, model, self.premise, self.shots,
                    self.character_tags, log=self.log.emit)
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                client.unload(model)
            except Exception:
                pass
