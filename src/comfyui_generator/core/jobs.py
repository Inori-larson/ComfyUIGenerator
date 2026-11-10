"""Task model and sequential runner with live preview routing."""

from __future__ import annotations

import random
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from comfyui_generator.core.comfy import ComfyClient, ComfyError, ComfyEventStream
from comfyui_generator.core.pose import (
    builtin_pose_json, builtin_pose_reference, generate_pose_json_skeleton,
    generate_pose_skeleton, pose_preset_for_shot, pose_should_apply,
)
from comfyui_generator.core.preview import PreviewFrame
from comfyui_generator.core.trace import trace_event
from comfyui_generator.core.workflow import (
    build_workflow,
    compose_prompts,
    is_double_shot,
    stage_for_node,
)


@dataclass
class Task:
    shot_id: str
    shot_name: str
    variant: int
    seed: int
    shot: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: str = "keyframe"
    expand_step: int = 0
    expand_steps: int = 0
    state: str = "pending"  # pending|submitted|running|done|failed|canceled
    stage: str = ""
    step: int = 0
    total: int = 0
    prompt_id: str | None = None
    image: str | None = None
    error: str | None = None
    preview: bytes | None = None
    preview_type: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    label: str = ""

    @property
    def prefix(self) -> str:
        return self.label or self.shot_id

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "stage": self.stage,
            "step": self.step,
            "total": self.total,
            "seed": self.seed,
            "image": self.image,
            "error": self.error,
        }


def build_tasks(cfg: dict[str, Any], shots: list[dict[str, Any]], variants: int,
                seed_mode: str, base_seed: int,
                expansions: int = 0) -> list[Task]:
    tasks: list[Task] = []
    variants = max(1, int(variants))
    expansions = max(0, int(expansions))
    task_counter = 0
    for index, shot in enumerate(shots):
        label = "%s_%s" % (shot.get("id", index), shot.get("name", "shot"))
        next_shot = shots[index + 1] if index + 1 < len(shots) else None
        shot_tasks: list[Task] = []
        shot_counter = 0
        for variant in range(variants):
            if shot.get("seed") is not None:
                seed = int(shot["seed"]) + (
                    shot_counter if seed_mode != "fixed" else 0)
            elif seed_mode == "fixed":
                seed = int(base_seed)
            elif seed_mode == "random":
                seed = random.randint(0, 2 ** 31 - 1)
            else:
                seed = int(base_seed) + task_counter
            shot_counter += 1
            task_counter += 1
            suffix = label + (("_v%02d" % (variant + 1)) if variants > 1 else "")
            keyframe_shot = shot
            if str(shot.get("keyframe_prompt") or "").strip():
                keyframe_shot = dict(shot)
                keyframe_shot["prompt"] = str(shot["keyframe_prompt"])
            shot_tasks.append(Task(
                shot_id=str(shot.get("id", "")),
                shot_name=shot.get("name", ""),
                variant=variant + 1, seed=seed, shot=keyframe_shot,
                label=suffix))
            ai_prompts = list(shot.get("ai_expansions") or [])[:expansions]
            for step, prompt in enumerate(ai_prompts, 1):
                if seed_mode == "fixed":
                    expand_seed = seed + step
                elif seed_mode == "random":
                    expand_seed = random.randint(0, 2 ** 31 - 1)
                elif shot.get("seed") is not None:
                    expand_seed = int(shot["seed"]) + shot_counter
                    shot_counter += 1
                    task_counter += 1
                else:
                    expand_seed = int(base_seed) + task_counter
                    task_counter += 1
                expanded = dict(shot)
                expanded["id"] = "%s_e%02d" % (shot.get("id", ""), step)
                expanded["name"] = "%s_expand_%02d" % (
                    shot.get("name", "shot"), step)
                expanded["prompt"] = str(prompt)
                expanded["base_shot_id"] = shot.get("id", "")
                expanded["base_shot_name"] = shot.get("name", "shot")
                expanded["base_prompt_zh"] = (
                    shot.get("prompt_zh") or shot.get("prompt", ""))
                expanded["expand_step"] = step
                shot_tasks.append(Task(
                    shot_id=str(expanded.get("id", "")),
                    shot_name=str(expanded.get("name", "")),
                    variant=variant + 1, seed=expand_seed, shot=expanded,
                    kind="expand", expand_step=step, expand_steps=len(ai_prompts),
                    label="%s_e%02d" % (suffix, step)))
        tasks.extend(shot_tasks)
    return tasks


def cross_shot_allowed(previous: Task | None, current: Task,
                       setting: dict[str, Any] | None) -> bool:
    """Whether a keyframe may use the last finished image as img2img init."""
    data = setting if isinstance(setting, dict) else {}
    if not data.get("enabled") or not data.get("cross_shot"):
        return False
    if current.kind != "keyframe" or previous is None or not previous.image:
        return False
    if previous.shot_id == current.shot_id:
        return False
    if is_double_shot(current.shot):
        return False
    if str(current.shot.get("init_image") or "").strip():
        return False
    return True


class TaskRunner:
    def __init__(self, client: ComfyClient, cfg: dict[str, Any],
                 tasks: list[Task],
                 ws_url: str,
                 hires: bool = True,
                 on_update: Callable[[Task], None] | None = None,
                 on_preview: Callable[[Task, PreviewFrame], None] | None = None,
                 on_log: Callable[[str], None] | None = None,
                 poll_interval: float = 0.5,
                 task_timeout: float = 1800.0):
        self.client = client
        self.cfg = cfg
        self.tasks = tasks
        self.ws_url = ws_url
        self.hires = hires
        self.on_update = on_update
        self.on_preview = on_preview
        self.on_log = on_log
        self.poll_interval = poll_interval
        self.task_timeout = task_timeout
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._current: Task | None = None
        self._stream: ComfyEventStream | None = None
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous: Task | None = None
        self._last_done: Task | None = None
        self._pose_controlnet_cache: str | None = None
        self._pose_missing_logged = False
        self._pose_image_cache: dict[tuple[Any, ...], str] = {}

    # ---------------------------------------------------------------- helpers

    def log(self, message: str) -> None:
        if self.on_log:
            self.on_log(message)

    def _notify(self, task: Task) -> None:
        if self.on_update:
            self.on_update(task)

    def _task_for_prompt(self, prompt_id: str | None) -> Task | None:
        if prompt_id:
            for task in self.tasks:
                if task.prompt_id == prompt_id:
                    return task
        return self._current

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        data = event.get("data") or {}
        if not isinstance(data, dict):
            return
        task = self._task_for_prompt(data.get("prompt_id"))
        if task is None:
            return
        with self._lock:
            if kind == "execution_start":
                task.state = "running"
                task.started_at = task.started_at or time.time()
            elif kind == "executing":
                node = data.get("node")
                if node is None:
                    task.stage = ""
                else:
                    stage = stage_for_node(node)
                    if stage:
                        task.stage = stage
                task.state = "running"
                task.started_at = task.started_at or time.time()
            elif kind == "progress":
                if isinstance(data.get("value"), int):
                    task.step = data["value"]
                    task.total = int(data.get("max") or 0)
            elif kind == "execution_error":
                task.error = str(data.get("exception_message") or data)[:2000]
                task.state = "failed"
            else:
                return
        self._notify(task)

    def _handle_preview(self, frame: PreviewFrame) -> None:
        task = self._task_for_prompt(frame.prompt_id)
        if task is None:
            return
        with self._lock:
            task.preview = frame.data
            task.preview_type = frame.image_type
        if self.on_preview:
            self.on_preview(task, frame)

    def _set_state(self, task: Task, state: str, **fields: Any) -> None:
        with self._lock:
            task.state = state
            for key, value in fields.items():
                setattr(task, key, value)
            if state in ("done", "failed", "canceled"):
                task.finished_at = time.time()
        self._notify(task)

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> threading.Thread:
        self._thread = threading.Thread(target=self.run, daemon=True, name="TaskRunner")
        self._thread.start()
        return self._thread

    def wait(self, timeout: float | None = None) -> None:
        self._done.wait(timeout)

    def cancel(self) -> None:
        self._cancel.set()
        self.client.interrupt()

    def run(self) -> None:
        stream = ComfyEventStream(self.ws_url, self.client.client_id,
                                  on_event=self._handle_event, on_preview=self._handle_preview)
        stream.start()
        self._stream = stream
        try:
            for task in self.tasks:
                if self._cancel.is_set():
                    self._set_state(task, "canceled")
                    continue
                self._run_one(task)
                self._previous = task if task.state == "done" and task.image else None
                if task.state == "done" and task.image:
                    self._last_done = task
        finally:
            stream.stop()
            self._done.set()

    def _expand_denoise(self, task: Task) -> float:
        setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        base = float(setting.get("denoise", 0.35))
        progress = max(0.0, min(1.0, task.expand_step / float(
            max(1, task.expand_steps))))
        if setting.get("sequence_mode"):
            denoise = 0.82 + 0.10 * progress
            limit = 0.94
        else:
            denoise = max(base, 0.65) + 0.20 * progress
            limit = 0.85
        return max(0.15, min(limit, denoise))

    def _chain_image(self, client: ComfyClient, task: Task) -> str:
        setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        if not setting.get("enabled") or not self._previous or not self._previous.image:
            return ""
        return self._upload_output_image(client, task, self._previous.image, "chain")

    def _upload_output_image(self, client: ComfyClient, task: Task, image: str,
                             kind: str) -> str:
        source = PurePosixPath(str(image).replace("\\", "/"))
        try:
            data = client.view(source.name,
                               str(source.parent) if str(source.parent) != "." else "")
            folder = Path(tempfile.gettempdir()) / "comfyui_generator_chain"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("%s_%s.png" % (task.id, kind))
            path.write_bytes(data)
            return client.upload_image(path, subfolder="anime_story_chain")
        except Exception as exc:
            self.log("Task %s %s image upload skipped: %s" % (task.label, kind, exc))
            return ""

    def _pose_controlnet_name(self) -> str:
        if self._pose_controlnet_cache is not None:
            return self._pose_controlnet_cache
        setting = (self.cfg.get("settings") or {}).get("pose") or {}
        name = str(setting.get("controlnet") or "").strip()
        if not name:
            try:
                info = self.client.object_info("ControlNetLoader")
                spec = (((info.get("ControlNetLoader") or {}).get("input") or {})
                        .get("required") or {}).get("control_net_name")
                names = []
                if isinstance(spec, (list, tuple)) and spec:
                    if isinstance(spec[0], list):
                        names = [str(item) for item in spec[0]]
                    elif spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                        names = [str(item) for item in (spec[1].get("options") or [])]
                candidates = [item for item in names if "openpose" in item.lower()
                              or "pose" in item.lower()]
                name = (candidates or [""])[0]
            except Exception as exc:
                self.log("OpenPose ControlNet list unavailable: %s" % exc)
                name = ""
        self._pose_controlnet_cache = name
        return name

    def _attach_pose(self, task: Task, shot: dict[str, Any],
                     people: tuple[str, ...]) -> None:
        setting = (self.cfg.get("settings") or {}).get("pose") or {}
        if not setting.get("enabled") or not pose_should_apply(shot):
            return
        controlnet = self._pose_controlnet_name()
        if not controlnet:
            if not self._pose_missing_logged:
                self._pose_missing_logged = True
                self.log("OpenPose enabled but no ControlNet model was found; pose skipped")
            return
        preset = pose_preset_for_shot(shot, str(setting.get("preset") or "auto"))
        settings = self.cfg.get("settings") or {}
        width = int(settings.get("width", 1024))
        height = int(settings.get("height", 1344))
        references = setting.get("reference") or {}
        reference = str(references.get("pair" if len(people) > 1 else people[0])
                        or "").strip()
        if not reference and len(people) > 1:
            builtin = builtin_pose_reference(preset)
            if builtin is not None:
                reference = str(builtin)
        image = ""
        label = "pose " + preset
        if reference:
            source = Path(reference)
            if source.is_file():
                key = ("ref", str(source.resolve()), source.stat().st_mtime_ns)
                image = self._pose_image_cache.get(key, "")
                if not image:
                    try:
                        folder = Path(tempfile.gettempdir()) / "comfyui_generator_pose"
                        upload_path = folder / ("ref_%s_%s" % (
                            "_".join(people), source.name))
                        upload_path.parent.mkdir(parents=True, exist_ok=True)
                        upload_path.write_bytes(source.read_bytes())
                        image = self.client.upload_image(
                            upload_path, subfolder="anime_story_pose")
                    except Exception as exc:
                        self.log("Task %s pose reference skipped: %s" % (
                            task.label, exc))
                if image:
                    self._pose_image_cache[key] = image
                    label = "pose ref " + source.name
            else:
                self.log("Task %s pose reference not found: %s" % (
                    task.label, source))
        if not image:
            adjust = setting.get("adjust") or {}
            custom = setting.get("custom") or {}
            json_source = builtin_pose_json(preset)
            if json_source is not None:
                key = ("json", str(json_source), json_source.stat().st_mtime_ns,
                       width, height, people, repr(adjust))
                image = self._pose_image_cache.get(key, "")
                if not image:
                    folder = Path(tempfile.gettempdir()) / "comfyui_generator_pose"
                    destination = folder / ("%s_%s_%dx%d.png" % (
                        preset, "_".join(people), width, height))
                    try:
                        path = generate_pose_json_skeleton(
                            preset, width, height, people=people,
                            destination=destination, adjust=adjust)
                        image = self.client.upload_image(
                            path, subfolder="anime_story_pose")
                        label = "pose json " + json_source.name
                    except Exception as exc:
                        self.log("Task %s pose JSON skipped: %s" % (
                            task.label, exc))
                        return
                    self._pose_image_cache[key] = image
            else:
                key = (preset, width, height, people, repr(adjust), repr(custom))
                image = self._pose_image_cache.get(key, "")
                if not image:
                    folder = Path(tempfile.gettempdir()) / "comfyui_generator_pose"
                    destination = folder / ("%s_%s_%dx%d.png" % (
                        preset, "_".join(people), width, height))
                    try:
                        path = generate_pose_skeleton(
                            preset, width, height, people=people,
                            destination=destination, adjust=adjust, custom=custom)
                        image = self.client.upload_image(
                            path, subfolder="anime_story_pose")
                    except Exception as exc:
                        self.log("Task %s pose skipped: %s" % (task.label, exc))
                        return
                    self._pose_image_cache[key] = image
        shot["pose_image"] = image
        shot["pose_controlnet"] = controlnet
        shot["pose_strength"] = float(setting.get("strength", 0.7))
        shot["pose_start"] = float(setting.get("start", 0.0))
        shot["pose_end"] = float(setting.get("end", 0.9))
        self.log("Task %s %s (%s)" % (task.label, label, "+".join(people)))

    def _execute_workflow(self, task: Task, shot: dict[str, Any],
                          positive: str, negative: str, prefix: str,
                          stage: str = "base", hires: bool | None = None) -> str | None:
        try:
            workflow = build_workflow(
                self.cfg, shot, positive, negative, task.seed,
                self.hires if hires is None else hires, prefix)
        except Exception as exc:
            task.error = "Workflow error: %s" % exc
            trace_event("render.workflow_error", {
                "label": task.label, "seed": task.seed, "error": repr(exc),
            })
            self.log("Task %s failed: %s" % (task.label, exc))
            return None
        trace_event("render.workflow", {
            "label": task.label,
            "shot_id": task.shot_id,
            "seed": task.seed,
            "workflow": workflow,
        })
        self._set_state(task, "submitted", stage=stage, step=0, total=0)
        try:
            prompt_id = self.client.queue_prompt(workflow)
        except ComfyError as exc:
            task.error = str(exc)
            self.log("Task %s rejected: %s" % (task.label, exc))
            return None
        with self._lock:
            task.prompt_id = prompt_id
            task.state = "running"
            task.started_at = time.time()
        self.log("Task %s submitted %s (seed %d, %s)" % (
            task.label, stage, task.seed, prompt_id))

        deadline = time.time() + self.task_timeout
        while time.time() < deadline:
            if self._cancel.is_set():
                self.client.interrupt()
                self._set_state(task, "canceled")
                return None
            try:
                history = self.client.history(prompt_id)
            except ComfyError:
                time.sleep(self.poll_interval)
                continue
            entry = history.get(prompt_id)
            if not entry:
                time.sleep(self.poll_interval)
                continue
            status = entry.get("status") or {}
            state = status.get("status_str")
            if state == "success":
                images = _saved_images(entry)
                return images[0] if images else None
            if state == "error":
                task.error = str(status)[:2000]
                self.log("Task %s failed: %s" % (task.label, status))
                return None
            time.sleep(self.poll_interval)
        task.error = "Timed out waiting for ComfyUI"
        self.log("Task %s timed out" % task.label)
        return None


    def _run_one(self, task: Task) -> None:
        with self._lock:
            self._current = task
        client = self.client
        shot = dict(task.shot)
        init_image = ""
        if task.kind == "expand":
            if task.kind == "expand":
                base = str(task.shot.get("base_shot_id") or "")
                prev = self._previous
                prev_base = ""
                if prev is not None:
                    prev_base = str((prev.shot or {}).get("base_shot_id")
                                    or (prev.shot or {}).get("id") or "")
                if (not prev or prev_base != base
                        or prev.variant != task.variant):
                    self._set_state(
                        task, "failed",
                        error="Previous image from the same shot is unavailable")
                    self.log("Expand %s skipped: same-shot previous image unavailable"
                             % task.label)
                    return
            init_image = self._chain_image(client, task)
            if not init_image:
                self._set_state(task, "failed", error="Previous image unavailable")
                self.log("%s %s skipped: previous image unavailable" % (
                    task.kind, task.label))
                return
            shot["init_image"] = init_image
            shot["init_denoise"] = self._expand_denoise(task)
            self.log("Expand %s: step %d/%d, denoise %.2f" % (
                task.label, task.expand_step, task.expand_steps,
                shot["init_denoise"]))
        img2img_setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        if cross_shot_allowed(self._last_done, task, img2img_setting):
            cross_image = self._upload_output_image(
                client, task, str(self._last_done.image), "cross")
            if cross_image:
                shot["init_image"] = cross_image
                shot["init_denoise"] = float(
                    img2img_setting.get("cross_shot_denoise", 0.35))
                self.log(
                    "Task %s cross-shot init from %s, denoise %.2f" % (
                        task.label, self._last_done.label,
                        shot["init_denoise"]))
        prefix = "%s/%s" % ((self.cfg.get("prefix") or "anime_story").rstrip("/"), task.prefix)
        if task.kind != "expand" and is_double_shot(shot):
            self._attach_pose(task, shot, ("girl", "boy"))
        positive, negative = compose_prompts(self.cfg, shot)
        trace_event("render.prompt", {
            "label": task.label,
            "shot_id": task.shot_id,
            "seed": task.seed,
            "positive": positive,
            "negative": negative,
            "shot": shot,
        })
        self.log("Task %s prompt ready (%d/%d chars)" % (
            task.label, len(positive), len(negative)))
        image = self._execute_workflow(
            task, shot, positive, negative, prefix, stage="base")
        if (not image and not self._cancel.is_set()
                and task.error and "Timed out" not in task.error):
            self.log("Task %s retrying once after workflow error" % task.label)
            task.error = ""
            image = self._execute_workflow(
                task, shot, positive, negative, prefix, stage="base")
        if self._cancel.is_set():
            return
        if image:
            self._set_state(task, "done", image=image, stage="",
                            step=task.total or task.step)
            trace_event("render.done", {
                "label": task.label, "shot_id": task.shot_id,
                "seed": task.seed, "image": image,
            })
            self.log("Task %s done: %s" % (task.label, image))
            return
        error = task.error or "ComfyUI returned no image"
        self._set_state(task, "failed", error=error)
        trace_event("render.failed", {
            "label": task.label, "shot_id": task.shot_id,
            "seed": task.seed, "error": error,
        })
        self.log("Task %s failed: %s" % (task.label, error))


def _saved_images(entry: dict[str, Any]) -> list[str]:
    images: list[str] = []
    for node_out in (entry.get("outputs") or {}).values():
        for image in node_out.get("images") or []:
            subfolder = image.get("subfolder") or ""
            filename = image.get("filename") or ""
            if filename:
                images.append("%s/%s" % (subfolder, filename) if subfolder else filename)
    return images
