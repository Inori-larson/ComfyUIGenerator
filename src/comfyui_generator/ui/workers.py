"""Background workers for the Qt UI.

All heavy work (service startup, LLM calls, ComfyUI rendering) runs in QThreads.
Signals cross back to the GUI thread via Qt's queued connections.
"""

from __future__ import annotations

import copy
import os
import re
import time
from typing import Any

from PySide6.QtCore import QThread, Signal

from comfyui_generator.core.assets import Assets
from comfyui_generator.core.comfy import ComfyClient
from comfyui_generator.core.config import AppConfig
from comfyui_generator.core.jobs import Task, TaskRunner
from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.preview import PreviewFrame
from comfyui_generator.core.services import ComfyService, OllamaService
from comfyui_generator.core.lora_info import lora_tag_info
from comfyui_generator.core.rewrite import rewrite_shot_prompt
from comfyui_generator.core.single import SingleOptions, generate_single_prompt
from comfyui_generator.core.tagger import select_tags
from comfyui_generator.core.tag_cache import load_tag_cache, update_tag_cache
from comfyui_generator.core.translate import translate_prompts, translate_tag_list, translate_to_tags
from comfyui_generator.core.storyboard import StoryboardOptions, generate_storyboard


class ConnectWorker(QThread):
    connected = Signal(dict)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, service: ComfyService, restart: bool = False):
        super().__init__()
        self.cfg = cfg
        self.service = service
        self.restart = restart

    def run(self) -> None:
        try:
            if self.restart:
                self.log.emit("Restarting ComfyUI ...")
                state = self.service.restart(force_external=True)
            else:
                state = self.service.ensure()
            client = ComfyClient(self.cfg.comfy.base_url)
            stats = client.system_stats()
            version = ((stats.get("system") or {}).get("comfyui_version"))
            assets = Assets(client).refresh()
            ollama_ok = False
            models: list[str] = []
            try:
                OllamaService(self.cfg).ensure()
                models = OllamaClient(self.cfg.ollama.base_url).model_names()
                ollama_ok = True
            except Exception as exc:
                self.log.emit("Ollama: %s" % exc)
            self.connected.emit({
                "state": state,
                "version": version,
                "assets": assets,
                "ollama_ok": ollama_ok,
                "models": models,
            })
        except Exception as exc:
            self.failed.emit(str(exc))


class AssetsWorker(QThread):
    done = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        try:
            assets = Assets(ComfyClient(self.cfg.comfy.base_url)).refresh()
            self.done.emit(assets)
        except Exception as exc:
            self.failed.emit(str(exc))


class PromptWorker(QThread):
    single_ready = Signal(dict)
    story_ready = Signal(list)
    rewritten = Signal(dict)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, kind: str, text: str, *,
                 single_options: SingleOptions | None = None,
                 story_options: StoryboardOptions | None = None,
                 initial_shots: list[dict[str, str]] | None = None,
                 model: str = "",
                 current_prompt: str = "",
                 instruction: str = "",
                 character_tags: str = "",
                 style_positive: str = "",
                 reference_tags: list[str] | None = None):
        super().__init__()
        self.cfg = cfg
        self.kind = kind
        self.text = text
        self.single_options = single_options
        self.story_options = story_options
        self.initial_shots = initial_shots
        self.model = model
        self.current_prompt = current_prompt
        self.instruction = instruction
        self.character_tags = character_tags
        self.style_positive = style_positive
        self.reference_tags = reference_tags or []

    def run(self) -> None:
        client = OllamaClient(self.cfg.ollama.base_url)
        model = self.model or (self.single_options or self.story_options).model
        try:
            if self.kind == "single":
                result = generate_single_prompt(client, self.text, self.single_options)
                tags = self._split_tags(result["prompt"])
                result["prompt_zh"] = self._translate_tags(client, model, tags)
                self.single_ready.emit(result)
            elif self.kind == "rewrite":
                prompt = rewrite_shot_prompt(
                    client, model, self.current_prompt, self.instruction,
                    character_tags=self.character_tags,
                    style_positive=self.style_positive,
                    reference_tags=self.reference_tags)
                prompt_zh = self._translate_tags(client, model, self._split_tags(prompt))
                self.rewritten.emit({"prompt": prompt, "prompt_zh": prompt_zh})
            else:
                shots = generate_storyboard(
                    client, self.text, self.story_options, initial_shots=self.initial_shots)
                all_tags: list[str] = []
                for shot in shots:
                    all_tags += self._split_tags(shot.get("prompt", ""))
                mapping = self._translate_map(client, model, all_tags)
                for shot in shots:
                    zh_tags = [mapping.get(tag, tag) for tag in self._split_tags(shot.get("prompt", ""))]
                    shot["prompt_zh"] = "，".join(zh_tags)
                self.story_ready.emit(shots)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                client.unload(model)
            except Exception:
                pass

    @staticmethod
    def _split_tags(text: str) -> list[str]:
        return [tag.strip() for tag in str(text or "").split(",") if tag.strip()]

    def _translate_map(self, client: OllamaClient, model: str,
                       tags: list[str]) -> dict[str, str]:
        if not tags:
            return {}
        self.log.emit("英文提示词已生成，正在用模型翻译标签...")
        cache_path = str(self.cfg.root / "cache" / "tag_translation.json")
        try:
            return translate_tag_list(client, model, tags, cache_path)
        except Exception as exc:
            self.log.emit("中文翻译失败：%s" % exc)
            return {}

    def _translate_tags(self, client: OllamaClient, model: str, tags: list[str]) -> str:
        mapping = self._translate_map(client, model, tags)
        return "，".join(mapping.get(tag, tag) for tag in tags)


class RenderWorker(QThread):
    task_updated = Signal(dict)
    preview = Signal(str, bytes, str)
    log = Signal(str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, project: dict[str, Any], tasks: list[Task], hires: bool):
        super().__init__()
        self.cfg = cfg
        self.project = copy.deepcopy(project)
        self.tasks = tasks
        self.hires = hires
        self.runner: TaskRunner | None = None
        self._last_preview: dict[str, float] = {}

    def run(self) -> None:
        try:
            client = ComfyClient(self.cfg.comfy.base_url)
            self._prepare_refs(client)
            runner = TaskRunner(
                client, self.project, self.tasks, self.cfg.comfy.ws_url,
                hires=self.hires,
                on_update=lambda task: self.task_updated.emit(task.summary()),
                on_preview=self._on_preview,
                on_log=self.log.emit,
            )
            self.runner = runner
            runner.run()
            self.finished_ok.emit([
                {"id": task.id, "label": task.label, "state": task.state,
                 "image": task.image, "error": task.error, "seed": task.seed}
                for task in self.tasks
            ])
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()

    def _on_preview(self, task: Task, frame: PreviewFrame) -> None:
        now = time.time()
        if now - self._last_preview.get(task.id, 0.0) < 0.08:
            return
        self._last_preview[task.id] = now
        self.preview.emit(task.id, frame.data, frame.image_type)

    def _prepare_refs(self, client: ComfyClient) -> None:
        character = self.project.get("character") or {}
        ip = character.get("ipadapter") or {}
        ref = ip.get("reference")
        if ref and os.path.isabs(ref) and os.path.isfile(ref):
            ip["reference"] = client.upload_image(ref)
            character["use_ipadapter"] = True
        style_ref = self.project.get("style_ref") or {}
        image = style_ref.get("image")
        if style_ref.get("enabled") and image and os.path.isabs(image) and os.path.isfile(image):
            style_ref["image"] = client.upload_image(image)


class LoraTagsWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, entries: list[tuple[str, str]], civitai_base: str):
        super().__init__()
        self.entries = entries
        self.civitai_base = civitai_base

    def run(self) -> None:
        results = []
        try:
            for name, path in self.entries:
                try:
                    info = lora_tag_info(path, online=True,
                                         civitai_base=self.civitai_base)
                except Exception as exc:
                    info = {"reference": [], "triggers": [],
                            "source": "查询失败：%s" % exc}
                results.append((name, path, info))
            self.done.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class TagTranslateWorker(QThread):
    batch = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, model: str, tags: list[str],
                 cache_path: str, batch_size: int = 80):
        super().__init__()
        self.cfg = cfg
        self.model = model
        self.tags = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
        self.cache_path = cache_path
        self.batch_size = max(1, batch_size)

    def run(self) -> None:
        client = OllamaClient(self.cfg.ollama.base_url)
        cache = load_tag_cache(self.cache_path)
        cached = {tag: cache[tag] for tag in self.tags if tag in cache}
        if cached:
            self.batch.emit(cached)
        missing = [tag for tag in self.tags if tag not in cache]
        try:
            for start in range(0, len(missing), self.batch_size):
                if self.isInterruptionRequested():
                    break
                chunk = missing[start:start + self.batch_size]
                values = translate_prompts(client, self.model, chunk,
                                           batch_size=len(chunk))
                pairs = {tag: value.replace("，", "、").replace(",", "、")
                         for tag, value in zip(chunk, values) if value}
                if pairs:
                    cache = update_tag_cache(self.cache_path, pairs)
                    self.batch.emit(pairs)
            self.done.emit({tag: cache.get(tag, tag) for tag in self.tags})
        except Exception as exc:
            self.failed.emit(str(exc))
            self.done.emit({tag: cache.get(tag, tag) for tag in self.tags})
        finally:
            try:
                client.unload(self.model)
            except Exception:
                pass


class AutoTranslateWorker(QThread):
    done = Signal(str, str)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, model: str, text: str, cache_path: str):
        super().__init__()
        self.cfg = cfg
        self.model = model
        self.text = text
        self.cache_path = cache_path

    @staticmethod
    def _is_english(token: str) -> bool:
        has_ascii = any(char.isascii() and char.isalpha() for char in token)
        has_chinese = any("\u4e00" <= char <= "\u9fff" for char in token)
        return has_ascii and not has_chinese

    def run(self) -> None:
        client = OllamaClient(self.cfg.ollama.base_url)
        tokens = [token.strip() for token in re.split(r"[,，、]", self.text) if token.strip()]
        english_tags = list(dict.fromkeys(
            token for token in tokens if self._is_english(token)))
        mapping: dict[str, str] = {}
        try:
            if english_tags:
                mapping = translate_tag_list(client, self.model, english_tags, self.cache_path)
        except Exception as exc:
            self.failed.emit(str(exc))
        cache = load_tag_cache(self.cache_path)
        reverse: dict[str, str] = {}
        for english, chinese in cache.items():
            if chinese and chinese not in reverse:
                reverse[chinese] = english
        unknown_chinese = list(dict.fromkeys(
            token for token in tokens
            if not self._is_english(token) and token not in reverse))
        chinese_map: dict[str, str] = {}
        if unknown_chinese:
            try:
                values = translate_to_tags(client, self.model, unknown_chinese, batch_size=1)
                chinese_map = {token: value for token, value in zip(unknown_chinese, values) if value}
            except Exception as exc:
                self.failed.emit(str(exc))
        display: list[str] = []
        resolved: list[str] = []
        for token in tokens:
            if self._is_english(token):
                display.append(mapping.get(token, token))
                resolved.append(token)
            else:
                display.append(token)
                resolved.append(chinese_map.get(token) or reverse.get(token, token))
        self.done.emit("，".join(display), ", ".join(resolved))
        try:
            client.unload(self.model)
        except Exception:
            pass


class TagPickWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, model: str, reference: list[str], context: str,
                 character_tags: str, required: list[str] | None = None):
        super().__init__()
        self.cfg = cfg
        self.model = model
        self.reference = reference
        self.context = context
        self.character_tags = character_tags
        self.required = required or []

    def run(self) -> None:
        client = OllamaClient(self.cfg.ollama.base_url)
        try:
            tags = select_tags(client, self.model, self.reference, self.context,
                               character_tags=self.character_tags,
                               required=self.required)
            self.done.emit(tags)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                client.unload(self.model)
            except Exception:
                pass
