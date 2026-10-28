"""Command line interface for M0: story generation, rendering, diagnostics."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from comfyui_generator import APP_NAME, __version__
from comfyui_generator.core.assets import Assets
from comfyui_generator.core.comfy import ComfyClient
from comfyui_generator.core.config import (
    AppConfig, default_config_path, load_config, load_template, resolve_template, save_config,
)
from comfyui_generator.core.detailers import local_detectors, resolve_detailers
from comfyui_generator.core.jobs import TaskRunner, build_tasks
from comfyui_generator.core.ollama import OllamaClient, OllamaError
from comfyui_generator.core.preview import PreviewFrame
from comfyui_generator.core.project import (
    new_project, save_profile, save_project,
)
from comfyui_generator.core.services import ComfyService, OllamaService, ServiceError
from comfyui_generator.core.single import SingleOptions, generate_single_prompt
from comfyui_generator.core.storyboard import StoryboardOptions, generate_storyboard, slugify


def _print(message: str = "") -> None:
    print(message, flush=True)


def _parse_loras(spec: str | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not spec:
        return result
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        name, strength = part, 0.9
        if ":" in part:
            left, right = part.rsplit(":", 1)
            try:
                strength = float(right)
                name = left
            except ValueError:
                name = part
        result.append({"name": name, "strength": strength})
    return result


def _append_tags(existing: str | None, extra: str | None) -> str:
    items = [x.strip() for x in (existing or "").split(",") if x.strip()]
    seen = {x.lower() for x in items}
    for token in (extra or "").split(","):
        token = token.strip()
        if token and token.lower() not in seen:
            items.append(token)
            seen.add(token.lower())
    return ", ".join(items)


def _apply_overrides(data: dict[str, Any], cfg: AppConfig, args: argparse.Namespace) -> tuple[bool, int]:
    """Merge CLI overrides into a storyboard config. Returns (hires_enabled, variants)."""
    loras = _parse_loras(getattr(args, "lora", None))
    if loras:
        if getattr(args, "lora_strength", None) is not None:
            for lora in loras:
                lora["strength"] = args.lora_strength
        data["loras"] = loras
        data.pop("lora", None)
    elif data.get("loras") is None and data.get("lora"):
        data["loras"] = [data.pop("lora")]

    if getattr(args, "character_tags", None):
        data.setdefault("character", {})["tags"] = args.character_tags

    settings = data.setdefault("settings", {})
    generation = cfg.generation
    settings["width"] = getattr(args, "width", None) or settings.get("width", generation.width)
    settings["height"] = getattr(args, "height", None) or settings.get("height", generation.height)
    settings["steps"] = getattr(args, "steps", None) or settings.get("steps", generation.steps)
    settings["cfg"] = (args.cfg if getattr(args, "cfg", None) is not None
                       else settings.get("cfg", generation.cfg))
    settings["sampler"] = getattr(args, "sampler", None) or settings.get("sampler", generation.sampler)
    settings["scheduler"] = getattr(args, "scheduler", None) or settings.get("scheduler", generation.scheduler)
    settings["seed_mode"] = (getattr(args, "seed_mode", None)
                             or settings.get("seed_mode", generation.seed_mode))
    settings["base_seed"] = int(getattr(args, "seed", None) or settings.get("base_seed")
                                or random.randint(1, 2 ** 31 - 1))

    hires = settings.setdefault("hires", {})
    if getattr(args, "no_hires", False):
        hires["enabled"] = False
    else:
        hires["enabled"] = hires.get("enabled", generation.hires_enabled)
        hires["scale"] = getattr(args, "hires_scale", None) or hires.get("scale", generation.hires_scale)
        if getattr(args, "hires_denoise", None) is not None:
            hires["denoise"] = args.hires_denoise
        else:
            hires["denoise"] = hires.get("denoise", generation.hires_denoise)
        hires["steps"] = hires.get("steps", generation.hires_steps)
        hires["upscale_model"] = getattr(args, "upscaler", None) or hires.get("upscale_model", generation.upscaler)

    variants = int(getattr(args, "variants", None) or data.get("variants") or generation.variants)
    data["variants"] = max(1, min(8, variants))

    if getattr(args, "detailers", None) is not None:
        detectors = Assets().detectors
        resolved = resolve_detailers(args.detailers, detectors or local_detectors(cfg.comfy.base_dir))
        data["detailers"] = [{
            "model": item["detector"],
            "prompt": item.get("prompt", ""),
            "denoise": item.get("denoise", 0.35),
            "guide_size": item.get("guide_size", 1024),
            "steps": 20,
            "cfg": settings["cfg"],
            "feather": 5,
        } for item in resolved]

    if getattr(args, "wildcards", False):
        data["wildcards"] = {"enabled": True,
                             "dir": getattr(args, "wildcard_dir", None) or data.get("wildcards", {}).get("dir", "")}
    elif data.get("wildcards") is None:
        data["wildcards"] = {"enabled": False, "dir": ""}

    style = data.setdefault("style", {})
    if getattr(args, "positive_extra", None):
        style["suffix"] = _append_tags(style.get("suffix", ""), args.positive_extra)
    if getattr(args, "negative_extra", None):
        style["negative"] = _append_tags(style.get("negative", ""), args.negative_extra)

    if getattr(args, "ipadapter_ref", None):
        from comfyui_generator.core.assets import find_preset_tags  # noqa: F401
        data.setdefault("character", {})["use_ipadapter"] = True
        data["character"]["ipadapter"] = {
            "reference": args.ipadapter_ref.replace("\\", "/"),
            "weight": getattr(args, "ipadapter_weight", None) or 0.6,
            "preset": "PLUS (high strength)",
            "weight_type": "linear",
            "start_at": 0.0,
            "end_at": 0.8,
        }
    if getattr(args, "style_ref", None):
        data["style_ref"] = {
            "enabled": True,
            "image": args.style_ref.replace("\\", "/"),
            "weight": getattr(args, "style_weight", None) or 0.8,
            "preset": "PLUS (high strength)",
            "weight_type": "style transfer",
            "start_at": 0.0,
            "end_at": 1.0,
        }

    return bool(hires.get("enabled", True)), data["variants"]


def _ensure_ollama(cfg: AppConfig, model: str | None = None) -> tuple[OllamaClient, str]:
    service = OllamaService(cfg)
    try:
        service.ensure()
    except ServiceError as exc:
        raise SystemExit("Ollama unavailable: %s" % exc)
    client = OllamaClient(cfg.ollama.base_url)
    try:
        names = client.model_names()
    except OllamaError as exc:
        raise SystemExit(str(exc))
    if model:
        if model in names:
            return client, model
        raise SystemExit("Model '%s' is not installed.\nInstalled: %s\nHint: ollama pull %s" %
                         (model, ", ".join(names) or "(none)", model))
    default = (cfg.ollama.default_model or "").strip()
    if default and default in names:
        return client, default
    if names:
        _print("未指定模型，使用已安装的：%s" % names[0])
        return client, names[0]
    raise SystemExit("Ollama 里没有任何模型。请先安装一个模型，例如：ollama pull <模型名>")


def _ensure_comfy(cfg: AppConfig, restart: bool, no_auto_start: bool) -> tuple[ComfyService, bool]:
    if no_auto_start:
        cfg.comfy.auto_start = False
    service = ComfyService(cfg)
    try:
        if restart:
            state = service.restart(force_external=True)
        else:
            state = service.ensure()
    except ServiceError as exc:
        raise SystemExit("ComfyUI unavailable: %s" % exc)
    return service, state == "started"


def cmd_story(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.no_auto_start:
        cfg.comfy.auto_start = False

    template_path = Path(args.template) if args.template else resolve_template(cfg)
    data = load_template(cfg) if not args.template else json.loads(
        template_path.read_text(encoding="utf-8-sig"))
    hires, variants = _apply_overrides(data, cfg, args)

    premise = args.premise
    if not premise:
        raise SystemExit("Please provide a premise.")
    character_tags = (data.get("character") or {}).get("tags", "")
    style_positive = (data.get("style") or {}).get("positive", "")

    client, llm = _ensure_ollama(cfg, args.model)

    _print("[1/2] Ollama 模型（%s）正在写 %d 镜分镜 ..." % (llm, args.shots))
    options = StoryboardOptions(
        model=llm, shots=args.shots, chunk=args.chunk, temperature=args.temperature,
        setting=args.setting, character_tags=character_tags,
        style_positive=style_positive, log=lambda msg: _print("      " + msg))
    started = time.time()
    shots = generate_storyboard(client, premise, options)
    _print("      done in %.1fs" % (time.time() - started))
    client.unload(llm)
    _print("      model unloaded, VRAM freed")

    name = slugify(args.name or "", "") or slugify(
        "".join(ch for ch in premise if ch.isascii()), "") or time.strftime("story_%Y%m%d_%H%M%S")
    project = new_project(name, premise, data, str(template_path))
    project["shots"] = shots
    project["prefix"] = "anime_story/" + name
    project["server"] = cfg.comfy.base_url
    out_path = Path(args.out) if args.out else save_project(project, cfg.root)
    if args.out:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    _print("\n      storyboard -> %s" % out_path)
    for shot in shots:
        _print("      %s  %-18s %s" % (shot["id"], shot["name"], shot["prompt"]))
    _print("\n      loras: %s" % (", ".join("%s(%.2f)" % (Path(l["name"]).name, l["strength"])
                                           for l in (data.get("loras") or [])) or "none"))
    _print("      size: %dx%d | steps %d | cfg %.1f | %s/%s | variants %d | hires %s" % (
        data["settings"]["width"], data["settings"]["height"], data["settings"]["steps"],
        data["settings"]["cfg"], data["settings"]["sampler"], data["settings"]["scheduler"],
        variants, "on" if hires else "off"))

    if args.plan_only:
        return 0

    service, started_comfy = _ensure_comfy(cfg, args.restart_comfy, args.no_auto_start)
    try:
        _render(cfg, project, hires, args, service, started_comfy)
    finally:
        if started_comfy and not args.keep_comfy:
            service.stop()
            _print("ComfyUI stopped (started by this run).")
    return 0


def cmd_image(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.no_auto_start:
        cfg.comfy.auto_start = False

    template_path = Path(args.template) if args.template else resolve_template(cfg)
    data = (json.loads(template_path.read_text(encoding="utf-8-sig"))
            if args.template else load_template(cfg))
    hires, variants = _apply_overrides(data, cfg, args)

    description = args.description
    if not description:
        raise SystemExit("Please provide a description.")
    client, llm = _ensure_ollama(cfg, args.model)

    _print("[1/2] Ollama 模型（%s）正在生成单图提示词 ..." % llm)
    started = time.time()
    options = SingleOptions(
        model=llm, framing=args.framing,
        setting=args.setting,
        character_tags=(data.get("character") or {}).get("tags", ""),
        style_positive=(data.get("style") or {}).get("positive", ""),
        log=lambda msg: _print("      " + msg))
    result = generate_single_prompt(client, description, options)
    client.unload(llm)
    _print("      done in %.1fs" % (time.time() - started))

    name = slugify(args.name or "", "") or slugify(
        "".join(ch for ch in description if ch.isascii()), "") or time.strftime("image_%Y%m%d_%H%M%S")
    project = new_project(name, description, data, str(template_path), mode="single")
    project["framing"] = args.framing
    project["shots"] = [{
        "id": "01",
        "name": slugify(description, "single") or "single",
        "prompt": result["prompt"],
        "negative": result["negative"],
    }]
    project["prefix"] = "anime_story/" + name
    project["server"] = cfg.comfy.base_url

    out_path = Path(args.out) if args.out else save_project(project, cfg.root)
    if args.out:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    _print("\n      single project -> %s" % out_path)
    _print("      prompt: %s" % result["prompt"])
    if result["negative"]:
        _print("      extra negative: %s" % result["negative"])

    if args.expand:
        if args.expand < 2:
            raise SystemExit("--expand must be >= 2")
        args.out = None  # the story project gets its own default path
        _expand_from_project(cfg, project, args, args.expand)
        return 0

    if args.plan_only:
        return 0
    service, started_comfy = _ensure_comfy(cfg, args.restart_comfy, args.no_auto_start)
    try:
        _render(cfg, project, hires, args, service, started_comfy)
    finally:
        if started_comfy and not args.keep_comfy:
            service.stop()
            _print("ComfyUI stopped (started by this run).")
    return 0


def cmd_expand(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.no_auto_start:
        cfg.comfy.auto_start = False
    path = Path(args.config)
    if not path.is_file():
        raise SystemExit("Project not found: %s" % path)
    source = json.loads(path.read_text(encoding="utf-8-sig"))
    if not source.get("shots"):
        raise SystemExit("Project has no shots: %s" % path)
    if args.shots < 2:
        raise SystemExit("--shots must be >= 2")
    if len(source["shots"]) > 1:
        _print("      note: using the first shot as anchor")
    _expand_from_project(cfg, source, args, args.shots)
    return 0


def _expand_from_project(cfg: AppConfig, source: dict[str, Any],
                         args: argparse.Namespace, total: int) -> dict[str, Any]:
    premise = source.get("premise") or source["shots"][0].get("prompt", "")
    client, llm = _ensure_ollama(cfg, getattr(args, "model", None))
    style = source.get("style") or {}
    options = StoryboardOptions(
        model=llm,
        shots=total,
        chunk=getattr(args, "chunk", 12),
        temperature=getattr(args, "temperature", 0.8),
        setting=getattr(args, "setting", ""),
        character_tags=(source.get("character") or {}).get("tags", ""),
        style_positive=style.get("positive", ""),
        log=lambda msg: _print("      " + msg))
    _print("\n[1/2] Ollama 模型正在扩写到 %d 镜（第 1 镜保留）..." % total)
    shots = generate_storyboard(client, premise, options, initial_shots=[source["shots"][0]])
    client.unload(llm)
    _print("      model unloaded, VRAM freed")

    name = slugify(getattr(args, "name", None) or "", "") or (
        slugify(str(source.get("name", "story")), "story") + "_story")
    story = new_project(name, premise, source, source.get("template", ""), mode="story")
    story["shots"] = shots
    story["prefix"] = "anime_story/" + name
    story["server"] = cfg.comfy.base_url
    if getattr(args, "variants", None):
        story["variants"] = args.variants
    if getattr(args, "seed", None) is not None:
        story.setdefault("settings", {})["base_seed"] = args.seed
    if getattr(args, "detailers", None) is not None:
        story["detailers"] = [{
            "model": item["detector"], "prompt": item.get("prompt", ""),
            "denoise": item.get("denoise", 0.35), "guide_size": item.get("guide_size", 1024),
            "steps": 20, "cfg": story.get("settings", {}).get("cfg", 5), "feather": 5,
        } for item in resolve_detailers(args.detailers, Assets().detectors or local_detectors(cfg.comfy.base_dir))]

    out_path = Path(args.out) if getattr(args, "out", None) else save_project(story, cfg.root)
    if getattr(args, "out", None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    _print("\n      story project -> %s" % out_path)
    for shot in shots:
        _print("      %s  %-18s %s" % (shot["id"], shot["name"], shot["prompt"]))

    if getattr(args, "plan_only", False):
        return story

    hires = bool((story.get("settings") or {}).get("hires", {}).get("enabled", True))
    if getattr(args, "no_hires", False):
        story.setdefault("settings", {}).setdefault("hires", {})["enabled"] = False
        hires = False
    service, started_comfy = _ensure_comfy(cfg, getattr(args, "restart_comfy", False),
                                           getattr(args, "no_auto_start", False))
    try:
        _render(cfg, story, hires, args, service, started_comfy)
    finally:
        if started_comfy and not getattr(args, "keep_comfy", False):
            service.stop()
            _print("ComfyUI stopped (started by this run).")
    return story


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    path = Path(args.config)
    if not path.is_file():
        raise SystemExit("Config not found: %s" % path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not data.get("shots"):
        raise SystemExit("Config has no shots: %s" % path)
    if args.variants:
        data["variants"] = args.variants
    if args.seed is not None:
        data.setdefault("settings", {})["base_seed"] = args.seed
    if args.no_hires:
        data.setdefault("settings", {}).setdefault("hires", {})["enabled"] = False
    if args.detailers is not None:
        data["detailers"] = [{
            "model": item["detector"], "prompt": item.get("prompt", ""),
            "denoise": item.get("denoise", 0.35), "guide_size": item.get("guide_size", 1024),
            "steps": 20, "cfg": data.get("settings", {}).get("cfg", 5), "feather": 5,
        } for item in resolve_detailers(args.detailers, Assets().detectors or local_detectors(cfg.comfy.base_dir))]
    hires = bool((data.get("settings") or {}).get("hires", {}).get("enabled", True))
    data.setdefault("prefix", "anime_story/" + (data.get("name") or "story"))
    service, started_comfy = _ensure_comfy(cfg, args.restart_comfy, args.no_auto_start)
    try:
        _render(cfg, data, hires, args, service, started_comfy)
    finally:
        if started_comfy and not args.keep_comfy:
            service.stop()
            _print("ComfyUI stopped (started by this run).")
    return 0


def _render(cfg: AppConfig, data: dict[str, Any], hires: bool, args: argparse.Namespace,
            service: ComfyService, started_comfy: bool) -> None:
    from comfyui_generator.core.config import ComfyConfig

    _print("\n[2/2] Rendering ...")
    assets = Assets(ComfyClient(cfg.comfy.base_url)).refresh()
    if assets.error:
        _print("      warning: cannot read /object_info: %s" % assets.error)
    model = data.get("model")
    if assets.checkpoints and model and model not in assets.checkpoints:
        _print("      warning: checkpoint not in ComfyUI list: %s" % model)
    missing = data.get("model") and not assets.checkpoints

    seed_mode = (data.get("settings") or {}).get("seed_mode", "increment")
    base_seed = int((data.get("settings") or {}).get("base_seed", 20251023))
    tasks = build_tasks(data, data["shots"], int(data.get("variants") or 1), seed_mode, base_seed)

    preview_dir = Path(args.save_previews) if args.save_previews else None
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
    stats = {"frames": 0, "last_print": {}}

    def on_update(task) -> None:
        key = task.id
        stage = task.stage or task.state
        last = stats["last_print"].get(key)
        if task.state in ("done", "failed", "canceled"):
            if last == task.state:
                return
            stats["last_print"][key] = task.state
            _print("      [%s] %s %s" % (task.label, task.state,
                                         task.image or (task.error or "")))
            if preview_dir and task.preview:
                suffix = ".png" if task.preview_type == "PNG" else ".jpg"
                (preview_dir / ("%s_final_preview%s" % (task.label, suffix))).write_bytes(task.preview)
        else:
            step = task.step or 0
            marker = "%s:%s" % (stage, step // 5)
            if last != marker:
                stats["last_print"][key] = marker
                total = task.total or "?"
                _print("      [%s] %s %s/%s" % (task.label, stage, step, total))

    def on_preview(task, frame: PreviewFrame) -> None:
        stats["frames"] += 1
        if preview_dir:
            suffix = ".png" if frame.image_type == "PNG" else ".jpg"
            path = preview_dir / ("%s_latest%s" % (task.label, suffix))
            path.write_bytes(frame.data)

    runner = TaskRunner(
        ComfyClient(cfg.comfy.base_url), data, tasks, cfg.comfy.ws_url,
        hires=hires, on_update=on_update, on_preview=on_preview,
        on_log=lambda msg: _print("      " + msg))
    runner.run()

    if stats["frames"] == 0:
        _print("      (no preview frames received; start ComfyUI with "
               "--preview-method latent2rgb to enable live preview)")
    else:
        _print("      preview frames: %d" % stats["frames"])

    done = [task for task in tasks if task.state == "done"]
    failed = [task for task in tasks if task.state == "failed"]
    _print("\n      finished: %d/%d done, %d failed" % (len(done), len(tasks), len(failed)))
    for task in done:
        _print("      %s -> %s" % (task.label, task.image))


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    _print("%s %s" % (APP_NAME, __version__))
    _print("config: %s" % default_config_path())
    _print("storage: %s" % cfg.root)
    _print("comfy: python=%s" % (cfg.comfy.python or "(unset)"))
    _print("       main=%s" % (cfg.comfy.main_py or "(unset)"))
    _print("       base=%s" % (cfg.comfy.base_dir or "(unset)"))
    if args.restart_comfy:
        try:
            _print("restart: %s" % ComfyService(cfg).restart(force_external=True))
        except ServiceError as exc:
            _print("restart failed: %s" % exc)
    service = ComfyService(cfg)
    status = service.status()
    _print("comfy status: %s" % json.dumps(status, ensure_ascii=False))
    if not status["running"]:
        _print("comfy log tail:\n" + service.tail_log(20))
    else:
        assets = Assets(ComfyClient(cfg.comfy.base_url)).refresh()
        _print("assets: %s" % json.dumps(assets.status(), ensure_ascii=False))
        _print("samplers: %s" % ", ".join(assets.samplers))
        _print("schedulers: %s" % ", ".join(assets.schedulers))
        _print("loras (%d): %s" % (len(assets.loras), ", ".join(assets.loras[:10])))
        _print("checkpoints (%d): %s" % (len(assets.checkpoints), ", ".join(assets.checkpoints[:10])))
        _print("detectors: %s" % ", ".join(assets.detectors))
    ollama = OllamaClient(cfg.ollama.base_url)
    try:
        names = ollama.model_names()
        _print("ollama: %s" % ", ".join(names))
        _print("ollama loaded: %s" % ", ".join(m.get("name", "") for m in ollama.ps()))
    except OllamaError as exc:
        _print("ollama: %s" % exc)
    return 0


def _add_common(p: argparse.ArgumentParser, include_shots: bool = True) -> None:
    p.add_argument("--template", default=None, help="storyboard template json")
    p.add_argument("--model", default=None, help="Ollama model")
    if include_shots:
        p.add_argument("--shots", type=int, default=6)
    p.add_argument("--variants", type=int, default=None)
    p.add_argument("--chunk", type=int, default=12)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--setting", default="")
    p.add_argument("--lora", default=None, help="name[:strength], comma separated")
    p.add_argument("--lora-strength", type=float, default=None)
    p.add_argument("--character-tags", default=None)
    p.add_argument("--detailers", default=None)
    p.add_argument("--positive-extra", default="")
    p.add_argument("--negative-extra", default="")
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--cfg", type=float, default=None)
    p.add_argument("--sampler", default=None)
    p.add_argument("--scheduler", default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--seed-mode", choices=["increment", "fixed", "random"], default=None)
    p.add_argument("--no-hires", action="store_true")
    p.add_argument("--hires-scale", type=float, default=None)
    p.add_argument("--hires-denoise", type=float, default=None)
    p.add_argument("--upscaler", default=None)
    p.add_argument("--ipadapter-ref", default=None)
    p.add_argument("--ipadapter-weight", type=float, default=None)
    p.add_argument("--style-ref", default=None)
    p.add_argument("--style-weight", type=float, default=None)
    p.add_argument("--wildcards", action="store_true")
    p.add_argument("--wildcard-dir", default=None)
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--out", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--save-previews", default=None)
    p.add_argument("--restart-comfy", action="store_true")
    p.add_argument("--no-auto-start", action="store_true")
    p.add_argument("--keep-comfy", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cui", description="%s %s" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="command")

    story = sub.add_parser("story", help="premise -> Ollama storyboard -> images")
    story.add_argument("premise", nargs="?")
    _add_common(story)
    story.set_defaults(func=cmd_story)

    image = sub.add_parser("image", help="description -> Ollama single prompt -> image")
    image.add_argument("description", nargs="?")
    _add_common(image, include_shots=False)
    image.add_argument("--framing", default="auto",
                       choices=["auto", "full_body", "upper_body", "close_up", "portrait", "wide"])
    image.add_argument("--expand", type=int, default=0,
                       help="after the single image, expand into N shots and render the story")
    image.set_defaults(func=cmd_image)

    expand = sub.add_parser("expand", help="expand a single-image project into a story")
    expand.add_argument("config")
    expand.add_argument("--shots", type=int, default=4)
    expand.add_argument("--model", default=None)
    expand.add_argument("--name", default=None)
    expand.add_argument("--out", default=None)
    expand.add_argument("--plan-only", action="store_true")
    expand.add_argument("--no-hires", action="store_true")
    expand.add_argument("--variants", type=int, default=None)
    expand.add_argument("--seed", type=int, default=None)
    expand.add_argument("--detailers", default=None)
    expand.add_argument("--chunk", type=int, default=12)
    expand.add_argument("--temperature", type=float, default=0.8)
    expand.add_argument("--setting", default="")
    expand.add_argument("--save-previews", default=None)
    expand.add_argument("--restart-comfy", action="store_true")
    expand.add_argument("--no-auto-start", action="store_true")
    expand.add_argument("--keep-comfy", action="store_true")
    expand.set_defaults(func=cmd_expand)

    run = sub.add_parser("run", help="render an existing story json")
    run.add_argument("config")
    run.add_argument("--variants", type=int, default=None)
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--detailers", default=None)
    run.add_argument("--no-hires", action="store_true")
    run.add_argument("--save-previews", default=None)
    run.add_argument("--restart-comfy", action="store_true")
    run.add_argument("--no-auto-start", action="store_true")
    run.add_argument("--keep-comfy", action="store_true")
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="show connection / asset status")
    doctor.add_argument("--restart-comfy", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
