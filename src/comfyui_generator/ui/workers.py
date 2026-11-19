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
from comfyui_generator.core.external_llm import (
    EXTERNAL_LLM_MODEL,
    ContentFilterError,
    ExternalLLMClient,
    resolve_external_model,
)
from comfyui_generator.core.expand_ai import generate_expansions
from comfyui_generator.core.jobs import Task, TaskRunner
from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.preview import PreviewFrame
from comfyui_generator.core.services import ComfyService, OllamaService
from comfyui_generator.core.lora_info import lora_tag_info
from comfyui_generator.core.rewrite import rewrite_shot_prompt
from comfyui_generator.core.single import SingleOptions, generate_single_prompt
from comfyui_generator.core.tag_cache import load_tag_cache, update_tag_cache
from comfyui_generator.core.tag_validation import (
    annotate_shots, database_from_config, options_from_config,
)
from comfyui_generator.core.translate import translate_prompts, translate_tag_list, translate_to_tags
from comfyui_generator.core.storyboard import (
    StoryboardOptions, generate_storyboard, parse_character_profiles)
from comfyui_generator.core.trace import (
    TracedClient, start_trace, stop_trace, trace_event,
)


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
    canceled = Signal(str)
    log = Signal(str)
    request_started = Signal(str, str)
    request_finished = Signal(str, str)

    def __init__(self, cfg: AppConfig, kind: str, text: str, *,
                 single_options: SingleOptions | None = None,
                 story_options: StoryboardOptions | None = None,
                 initial_shots: list[dict[str, str]] | None = None,
                 model: str = "",
                 current_prompt: str = "",
                 instruction: str = "",
                 character_tags: str = "",
                 style_positive: str = "",
                  strip_appearance: bool = False,
                  use_external: bool = False):
        super().__init__()
        self.cfg = cfg
        self.kind = kind
        self.text = text
        self.single_options = single_options
        self.story_options = story_options
        if self.single_options is not None:
            self.single_options.log = self.log.emit
            self.single_options.policy = self.cfg.story_policy
        if self.story_options is not None:
            self.story_options.log = self.log.emit
            self.story_options.policy = self.cfg.story_policy
        self.initial_shots = initial_shots
        self.model = model
        self.current_prompt = current_prompt
        self.instruction = instruction
        self.character_tags = character_tags
        self.style_positive = style_positive
        self.strip_appearance = strip_appearance
        self.use_external = use_external

    def cancel(self) -> None:
        self.requestInterruption()

    def _canceled(self) -> bool:
        return self.isInterruptionRequested()

    def run(self) -> None:
        if self.use_external:
            client = ExternalLLMClient(self.cfg.external_llm)
            model = resolve_external_model(self.cfg.external_llm, self.model)
        else:
            client = OllamaClient(self.cfg.ollama.base_url)
            options = self.single_options or self.story_options
            model = self.model or (options.model if options is not None else "")
        local_client = client if not self.use_external else OllamaClient(self.cfg.ollama.base_url)
        local_model = model if not self.use_external else self.cfg.ollama.default_model
        if self.use_external:
            if self.single_options is not None:
                self.single_options.model = model
            if self.story_options is not None:
                self.story_options.model = model
        try:
            trace, trace_token = start_trace(
                self.cfg.single_projects_dir.parent / "log", self.kind, {
                    "kind": self.kind,
                    "model": model,
                    "use_external": self.use_external,
                    "text": self.text,
                    "initial_shots": len(self.initial_shots or []),
                    "options": (
                        self.story_options.__dict__
                        if self.story_options is not None
                        else self.single_options.__dict__
                        if self.single_options is not None else {}),
                })
        except Exception as exc:
            trace, trace_token = None, None
            self.log.emit("日志初始化失败：%s" % exc)
        client = TracedClient(
            client, self.kind,
            on_request_start=self.request_started.emit,
            on_request_end=self.request_finished.emit)
        trace_event("request", {"kind": self.kind, "text": self.text,
                                "model": model})
        try:
            self._run_generation(client, model, local_client, local_model,
                                 fell_back=False)
        except InterruptedError:
            trace_event("canceled", {"kind": self.kind})
            self.canceled.emit("已打断生成")
        except ContentFilterError as exc:
            trace_event("failed", {"kind": self.kind, "error": repr(exc)})
            self.failed.emit("外部模型内容审核拒绝：%s" % exc)
        except Exception as exc:
            trace_event("failed", {"kind": self.kind, "error": repr(exc)})
            self.failed.emit(str(exc))
        finally:
            try:
                client.unload(model)
            except Exception:
                pass
            if self.use_external and local_model:
                try:
                    local_client.unload(local_model)
                except Exception:
                    pass
            if trace is not None:
                stop_trace(trace, trace_token)

    def _run_generation(self, client, model, local_client, local_model,
                        fell_back: bool = False):
        if self._canceled():
            raise InterruptedError
        if self.kind == "single":
            result = generate_single_prompt(client, self.text, self.single_options)
            if self._canceled():
                raise InterruptedError
            tags = self._split_tags(result["prompt"])
            if local_model:
                result["prompt_zh"] = self._translate_tags(
                    local_client, local_model, tags)
            else:
                result["prompt_zh"] = "，".join(tags)
            if self._canceled():
                raise InterruptedError
            trace_event("single.result", result)
            self.single_ready.emit(result)
        elif self.kind == "rewrite":
            prompt = rewrite_shot_prompt(
                client, model, self.current_prompt, self.instruction,
                character_tags=self.character_tags,
                style_positive=self.style_positive,
                strip_appearance=self.strip_appearance,
                policy=self.cfg.story_policy)
            if self._canceled():
                raise InterruptedError
            if local_model:
                prompt_zh = self._translate_tags(
                    local_client, local_model, self._split_tags(prompt))
            else:
                prompt_zh = prompt
            if self._canceled():
                raise InterruptedError
            trace_event("rewrite.result", {
                "prompt": prompt, "prompt_zh": prompt_zh,
                "instruction": self.instruction})
            self.rewritten.emit({"prompt": prompt, "prompt_zh": prompt_zh})
        else:
            self._attach_fewshot()
            self._generated_beats = None
            if self.story_options is not None:
                self.story_options.on_contract = (
                    lambda beats: setattr(self, "_generated_beats", beats))
            shots = generate_storyboard(
                client, self.text, self.story_options,
                initial_shots=self.initial_shots,
                model_override=(model if fell_back else ""))
            self._finalize_story_shots(
                shots, local_client, local_model, "story.result")

    def _attach_fewshot(self) -> None:
        rag = getattr(self.cfg, "rag", None)
        if rag is None or not bool(getattr(rag, "enabled", False)):
            return
        if self.story_options is None or self.story_options.fewshot:
            return
        try:
            from comfyui_generator.core.rag import (
                render_fewshot_block, retrieve_fewshot)

            queries = str(getattr(rag, "queries", "") or "").strip()
            if not queries:
                self.log.emit("图站范例跳过：请先在设置里填写检索词。")
                return
            index_dir = rag.index_dir or str(self.cfg.cache_dir / "rag")
            examples = retrieve_fewshot(
                queries, index_dir=index_dir,
                source=getattr(rag, "source", "yande") or "yande",
                proxy=getattr(rag, "proxy", "") or "",
                login=rag.login, api_key=rag.api_key,
                max_examples=int(rag.max_examples or 4),
                limit=int(rag.limit_per_query or 20),
                min_score=int(rag.min_score if rag.min_score is not None else 5),
                cache_hours=float(rag.cache_hours or 24.0),
                log=self.log.emit)
            block = render_fewshot_block(examples)
            if block:
                self.story_options.fewshot = block
                self.log.emit("已加入 %d 条 Danbooru 真实范例（仅供学习标签搭配）"
                              % len(examples))
        except Exception as exc:
            self.log.emit("Danbooru 范例跳过（不影响生成）：%s" % exc)

    def _finalize_story_shots(self, shots, local_client, local_model, event):
        if self._canceled():
            raise InterruptedError
        self._auto_repair_story(shots)
        all_tags: list[str] = []
        for shot in shots:
            all_tags += self._split_tags(shot.get("prompt", ""))
        mapping = (self._translate_map(local_client, local_model, all_tags)
                   if local_model else {})
        if self._canceled():
            raise InterruptedError
        for shot in shots:
            zh_tags = [mapping.get(tag, tag)
                       for tag in self._split_tags(shot.get("prompt", ""))]
            shot["prompt_zh"] = "，".join(zh_tags)
        self._annotate_contract_findings(shots)
        self._summarise_tag_findings(shots)
        trace_event(event, shots)
        self.story_ready.emit(shots)

    def _auto_repair_story(self, shots: list[dict[str, Any]]) -> None:
        tagdb_cfg = getattr(self.cfg, "tagdb", None)
        if tagdb_cfg is not None and not bool(
                getattr(tagdb_cfg, "enabled", True)):
            return
        if not bool(getattr(tagdb_cfg, "auto_repair_story", True)):
            self._annotate_tag_findings(shots)
            return
        try:
            from comfyui_generator.core.prompt_repair import auto_repair_shots

            db = database_from_config(tagdb_cfg)
            if self.use_external:
                client = ExternalLLMClient(self.cfg.external_llm)
                model = resolve_external_model(self.cfg.external_llm, self.model)
            else:
                client = OllamaClient(self.cfg.ollama.base_url)
                model = self.model or self.cfg.ollama.default_model
            report = auto_repair_shots(
                shots, db, client, model,
                options=options_from_config(tagdb_cfg),
                max_rounds=2,
                character_tags=self.character_tags or "",
                strip_appearance=bool(getattr(self.story_options,
                                              "strip_appearance", False)),
                log=self.log.emit)
            if report.repaired:
                self.log.emit("自动修复：%s 镜 P1 已修正（%s）。" % (
                    len(report.repaired), ",".join(report.repaired)))
                trace_event("tagdb.repaired", {
                    "repaired": report.repaired,
                    "unresolved": report.unresolved})
            if report.unresolved:
                self.log.emit("仍有 %d 镜 P1 未通过校验，已标记待处理：%s" % (
                    len(report.unresolved), ",".join(report.unresolved)))
        except Exception as exc:
            self.log.emit("自动修复跳过（不影响就绪）：%s" % exc)
            self._annotate_tag_findings(shots)

    def _annotate_contract_findings(self, shots: list[dict[str, Any]]) -> None:
        beats = getattr(self, "_generated_beats", None)
        if not beats:
            self.log.emit("剧情契约：模型未声明 beat 结构，跳过校验。")
            return
        try:
            from comfyui_generator.core.story_contract import (
                StoryContract, validate_contract,
            )

            contract = StoryContract(beats=[b for b in beats
                                             if isinstance(b, dict)])
            if not contract.has_beats:
                self.log.emit("剧情契约：模型声明的 beat 不足 2 个，跳过校验。")
                return
            findings = validate_contract(shots, contract)
            if not findings:
                self.log.emit("剧情契约校验通过：%d 个 beat 全覆盖且保序。"
                              % len(contract.beats))
                return
            for finding in findings:
                self.log.emit("剧情契约 · [%s] %s" % (
                    finding.get("severity"), finding.get("message")))
            trace_event("contract.check", {"findings": findings})
            for shot in shots:
                existing = shot.setdefault("findings", [])
                existing.extend(findings)
        except Exception as exc:
            self.log.emit("剧情契约校验跳过：%s" % str(exc)[:160])

    def _summarise_tag_findings(self, shots: list[dict[str, Any]]) -> None:
        blocking = [s for s in shots if s.get("ready") is False]
        flagged = [s for s in shots if s.get("findings")]
        if blocking:
            self.log.emit("标签校验：%d 镜存在 P1（已标记待处理），%d 镜有提示。"
                          % (len(blocking), len(flagged)))
        elif flagged:
            self.log.emit("标签校验：%d 镜有 P2/P3 提示（不阻断）。" % len(flagged))
        else:
            self.log.emit("分镜标签校验通过：%d 镜全部就绪。" % len(shots))

    def _annotate_tag_findings(self, shots: list[dict[str, Any]]) -> None:
        tagdb_cfg = getattr(self.cfg, "tagdb", None)
        if tagdb_cfg is not None and not bool(
                getattr(tagdb_cfg, "enabled", True)):
            self.log.emit("分镜标签校验已在设置中关闭。")
            return
        try:
            db = database_from_config(tagdb_cfg)
            annotate_shots(shots, db, options_from_config(tagdb_cfg))
        except Exception as exc:
            self.log.emit("标签校验跳过（不影响就绪）：%s" % exc)

    @staticmethod
    def _split_tags(text: str) -> list[str]:
        return [tag.strip() for tag in str(text or "").split(",") if tag.strip()]

    def _translate_map(self, client: OllamaClient, model: str,
                       tags: list[str]) -> dict[str, str]:
        if not tags:
            return {}
        self.log.emit("英文提示词已生成，正在后台翻译标签（仅用于显示，不影响就绪）...")
        cache_path = str(self.cfg.root / "cache" / "tag_translation.json")
        try:
            return translate_tag_list(
                client, model, tags, cache_path, timeout=30.0)
        except Exception as exc:
            self.log.emit("中文标签翻译跳过（不影响就绪）：%s" % exc)
            return {}

    def _translate_tags(self, client: OllamaClient, model: str,
                        tags: list[str]) -> str:
        mapping = self._translate_map(client, model, tags)
        return "，".join(mapping.get(tag, tag) for tag in tags)


class ExpansionWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)
    canceled = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, shots: list[dict[str, Any]], count: int,
                 model: str = "", use_external: bool = False,
                 sequence: bool = False):
        super().__init__()
        self.cfg = cfg
        self.shots = copy.deepcopy(shots)
        self.count = count
        self.model = model
        self.use_external = use_external
        self.sequence = sequence

    def cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:
        if self.use_external:
            client = ExternalLLMClient(self.cfg.external_llm)
            model = resolve_external_model(self.cfg.external_llm, self.model)
        else:
            client = OllamaClient(self.cfg.ollama.base_url)
            model = self.model or self.cfg.ollama.default_model
        try:
            trace, trace_token = start_trace(
                self.cfg.single_projects_dir.parent / "log", "expand", {
                    "shots": len(self.shots),
                    "count": self.count,
                    "model": model,
                    "use_external": self.use_external,
                    "sequence": self.sequence,
                })
        except Exception as exc:
            trace, trace_token = None, None
            self.log.emit("日志初始化失败：%s" % exc)
        client = TracedClient(client, "expand")
        trace_event("expand.request", {"count": self.count,
                                       "sequence": self.sequence})
        try:
            if self.isInterruptionRequested():
                self.canceled.emit("AI expansion canceled")
                return
            result = generate_expansions(
                client, model, self.shots, self.count,
                sequence=self.sequence, log=self.log.emit)
            if self.isInterruptionRequested():
                self.canceled.emit("AI expansion canceled")
                return
            trace_event("expand.result", result)
            self.done.emit(result)
        except Exception as exc:
            trace_event("failed", {"kind": "expand", "error": repr(exc)})
            self.failed.emit(str(exc))
        finally:
            try:
                client.unload(model)
            except Exception:
                pass
            if trace is not None:
                stop_trace(trace, trace_token)


class RenderWorker(QThread):
    task_updated = Signal(dict)
    preview = Signal(str, bytes, str)
    log = Signal(str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, project: dict[str, Any], tasks: list[Task], hires: bool,
                 verify_model: str = "", verify_external: bool = False):
        super().__init__()
        self.cfg = cfg
        self.project = copy.deepcopy(project)
        self.tasks = tasks
        self.hires = hires
        self.verify_model = verify_model
        self.verify_external = verify_external
        self.runner: TaskRunner | None = None
        self._last_preview: dict[str, float] = {}

    def run(self) -> None:
        try:
            trace, trace_token = start_trace(
                self.cfg.single_projects_dir.parent / "log", "render", {
                    "project_id": self.project.get("id"),
                    "project_name": self.project.get("name"),
                    "tasks": len(self.tasks),
                    "hires": self.hires,
                    "settings": self.project.get("settings") or {},
                })
        except Exception as exc:
            trace, trace_token = None, None
            self.log.emit("日志初始化失败：%s" % exc)
        try:
            client = ComfyClient(self.cfg.comfy.base_url)
            self._prepare_refs(client)
            verifier = self._build_verifier()
            runner = TaskRunner(
                client, self.project, self.tasks, self.cfg.comfy.ws_url,
                hires=self.hires,
                on_update=lambda task: self.task_updated.emit(task.summary()),
                on_preview=self._on_preview,
                on_log=self.log.emit,
                verifier=verifier,
            )
            self.runner = runner
            runner.run()
            trace_event("render.finished", [
                {"id": task.id, "label": task.label, "state": task.state,
                 "image": task.image, "error": task.error, "seed": task.seed}
                for task in self.tasks
            ])
            self.finished_ok.emit([
                {"id": task.id, "label": task.label, "state": task.state,
                 "image": task.image, "error": task.error, "seed": task.seed}
                for task in self.tasks
            ])
        except Exception as exc:
            trace_event("render.failed", {"error": repr(exc)})
            self.failed.emit(str(exc))
        finally:
            if trace is not None:
                stop_trace(trace, trace_token)

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()

    def _build_verifier(self):
        t = getattr(self.cfg, "tagger", None)
        if not (t and t.enabled and t.auto_rewrite):
            return None
        try:
            from comfyui_generator.core.render_verify import RenderVerifier

            if self.verify_external:
                llm_client = ExternalLLMClient(self.cfg.external_llm)
                model = resolve_external_model(self.cfg.external_llm,
                                               self.verify_model)
            else:
                llm_client = OllamaClient(self.cfg.ollama.base_url)
                model = self.verify_model or self.cfg.ollama.default_model
            self.project.setdefault("comfy", {})
            self.project["comfy"]["output_dir"] = self.cfg.comfy.output_dir
            return RenderVerifier(
                python=self.cfg.comfy.python,
                root=self.cfg.root,
                base_dir=self.cfg.comfy.base_dir,
                tagger_config=self.cfg.tagger,
                tagdb_config=self.cfg.tagdb,
                llm_client=llm_client,
                llm_model=model,
                log=self.log.emit)
        except Exception as exc:
            self.log.emit("渲染后验收初始化失败，本次跳过：%s" % exc)
            return None

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