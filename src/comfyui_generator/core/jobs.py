"""Task model and sequential runner with live preview routing."""

from __future__ import annotations

import random
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from comfyui_generator.core.comfy import ComfyClient, ComfyError, ComfyEventStream
from comfyui_generator.core.preview import PreviewFrame
from comfyui_generator.core.workflow import build_workflow, compose_prompts, stage_for_node

AUTO_BRIDGE_MAX = 4


@dataclass
class Task:
    shot_id: str
    shot_name: str
    variant: int
    seed: int
    shot: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: str = "keyframe"
    bridge_source: str = ""
    bridge_target: str = ""
    bridge_step: int = 0
    bridge_steps: int = 0
    bridge_delta: float = 0.0
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


def _prompt_tags(text: str) -> list[str]:
    return [tag.strip() for tag in str(text or "").split(",") if tag.strip()]


def _tag_keys(text: str) -> set[str]:
    return {re.sub(r"[_\-\s]+", " ", tag.lower()).strip()
            for tag in _prompt_tags(text) if tag.strip()}


def shot_difference(source: dict[str, Any], target: dict[str, Any]) -> float:
    source_tags = _tag_keys(str(source.get("prompt") or ""))
    target_tags = _tag_keys(str(target.get("prompt") or ""))
    union = source_tags | target_tags
    tag_delta = 1.0 - (len(source_tags & target_tags) / len(union)) if union else 0.0
    cast_delta = 1.0 if (str(source.get("cast") or "").strip()
                         != str(target.get("cast") or "").strip()) else 0.0
    scene_delta = 1.0 if (str(source.get("scene") or "").strip()
                          != str(target.get("scene") or "").strip()) else 0.0
    phase_delta = 1.0 if (str(source.get("phase") or "").strip()
                          != str(target.get("phase") or "").strip()) else 0.0
    return max(0.0, min(1.0, 0.60 * tag_delta + 0.15 * cast_delta
                        + 0.15 * scene_delta + 0.10 * phase_delta))


def bridge_count(delta: float, maximum: int) -> int:
    maximum = max(0, int(maximum))
    if maximum <= 0:
        return 0
    return max(1, min(maximum, 1 + int(round(delta * maximum * 1.25))))


def _bridge_shot(source: dict[str, Any], target: dict[str, Any],
                 step: int, steps: int) -> dict[str, Any]:
    ratio = 0.35 + 0.65 * (step / float(steps)) ** 0.55
    source_tags = _prompt_tags(source.get("prompt", ""))
    target_tags = _prompt_tags(target.get("prompt", ""))
    source_keys = {tag.lower() for tag in source_tags}
    target_keys = {tag.lower() for tag in target_tags}
    common = [tag for tag in source_tags if tag.lower() in target_keys]
    source_only = [tag for tag in source_tags if tag.lower() not in target_keys]
    target_only = [tag for tag in target_tags if tag.lower() not in source_keys]
    keep_source = source_only[:max(0, round(len(source_only) * (1.0 - ratio)))]
    keep_target = target_only[:max(0, round(len(target_only) * ratio))]
    prompt = ", ".join(common + keep_source + keep_target)
    shot = dict(source)
    shot["id"] = "%s_%s_b%02d" % (source.get("id", ""), target.get("id", ""), step)
    shot["name"] = "%s_to_%s_bridge_%02d" % (
        source.get("name", "src"), target.get("name", "dst"), step)
    shot["prompt"] = prompt
    shot["prompt_zh"] = "过渡：%s → %s" % (
        source.get("prompt_zh") or source.get("prompt", ""),
        target.get("prompt_zh") or target.get("prompt", ""))
    shot["phase"] = "bridge"
    shot["bridge_source"] = source.get("id", "")
    shot["bridge_target"] = target.get("id", "")
    return shot


def build_tasks(cfg: dict[str, Any], shots: list[dict[str, Any]], variants: int,
                seed_mode: str, base_seed: int,
                bridges: int = 0, auto_bridges: bool = False) -> list[Task]:
    tasks: list[Task] = []
    variants = max(1, int(variants))
    bridges = AUTO_BRIDGE_MAX if auto_bridges else max(0, int(bridges))
    for index, shot in enumerate(shots):
        label = "%s_%s" % (shot.get("id", index), shot.get("name", "shot"))
        shot_tasks: list[Task] = []
        for variant in range(variants):
            if shot.get("seed") is not None:
                seed = int(shot["seed"]) + (variant if seed_mode != "fixed" else 0)
            elif seed_mode == "fixed":
                seed = int(base_seed)
            elif seed_mode == "random":
                seed = random.randint(0, 2 ** 31 - 1)
            else:
                seed = int(base_seed) + index * variants + variant
            suffix = label + (("_v%02d" % (variant + 1)) if variants > 1 else "")
            shot_tasks.append(Task(
                shot_id=str(shot.get("id", "")),
                shot_name=shot.get("name", ""),
                variant=variant + 1, seed=seed, shot=shot, label=suffix))
        tasks.extend(shot_tasks)
        if bridges and index + 1 < len(shots) and shot_tasks:
            target = shots[index + 1]
            delta = shot_difference(shot, target)
            count = bridge_count(delta, bridges)
            for step in range(1, count + 1):
                bridge = _bridge_shot(shot, target, step, count)
                seed = shot_tasks[-1].seed + step
                tasks.append(Task(
                    shot_id=str(bridge.get("id", "")),
                    shot_name=str(bridge.get("name", "")),
                    variant=1, seed=seed, shot=bridge,
                    kind="bridge",
                    bridge_source=str(shot.get("id", "")),
                    bridge_target=str(target.get("id", "")),
                    bridge_step=step, bridge_steps=count,
                    bridge_delta=delta,
                    label="%s_to_%s_b%02d" % (
                        shot.get("id", index), target.get("id", index + 2), step)))
    return tasks


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
        finally:
            stream.stop()
            self._done.set()

    def _img2img_denoise(self, shot: dict[str, Any],
                         previous: Task | None = None) -> float:
        setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        denoise = float(setting.get("denoise", 0.35))
        if shot.get("phase") == "sex":
            denoise = float(setting.get("sex_denoise", min(0.8, denoise + 0.15)))
        if previous:
            prev_shot = previous.shot
            prev_scene = str(prev_shot.get("scene") or "").strip()
            scene = str(shot.get("scene") or "").strip()
            if prev_scene and scene and prev_scene != scene:
                denoise += 0.15
            if (str(prev_shot.get("cast") or "").strip()
                    != str(shot.get("cast") or "").strip()):
                denoise += 0.05
        return max(0.05, min(0.95, denoise))

    def _bridge_denoise(self, task: Task) -> float:
        setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        base = float(setting.get("denoise", 0.35))
        denoise = max(base, 0.78 + 0.17 * task.bridge_delta)
        if task.bridge_steps > 1:
            denoise += 0.04 * (task.bridge_step - 1) / float(task.bridge_steps - 1)
        return max(0.05, min(0.95, denoise))

    def _chain_image(self, client: ComfyClient, task: Task) -> str:
        setting = (self.cfg.get("settings") or {}).get("img2img") or {}
        if not setting.get("enabled") or not self._previous or not self._previous.image:
            return ""
        source = PurePosixPath(str(self._previous.image).replace("\\", "/"))
        try:
            data = client.view(source.name, str(source.parent) if str(source.parent) != "." else "")
            folder = Path(tempfile.gettempdir()) / "comfyui_generator_chain"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("%s.png" % task.id)
            path.write_bytes(data)
            return client.upload_image(path, subfolder="anime_story_chain")
        except Exception as exc:
            self.log("Task %s image2image skipped: %s" % (task.label, exc))
            return ""

    def _run_one(self, task: Task) -> None:
        with self._lock:
            self._current = task
        client = self.client
        shot = dict(task.shot)
        init_image = ""
        if task.kind == "bridge":
            init_image = self._chain_image(client, task)
            if not init_image:
                self._set_state(task, "failed", error="Bridge source image unavailable")
                self.log("Bridge %s skipped: source image unavailable" % task.label)
                return
            shot["init_image"] = init_image
            shot["init_denoise"] = self._bridge_denoise(task)
            self.log("Bridge %s: difference %.2f, step %d/%d, denoise %.2f" % (
                task.label, task.bridge_delta, task.bridge_step,
                task.bridge_steps, shot["init_denoise"]))
        positive, negative = compose_prompts(self.cfg, shot)
        prefix = "%s/%s" % ((self.cfg.get("prefix") or "anime_story").rstrip("/"), task.prefix)
        try:
            workflow = build_workflow(self.cfg, shot, positive, negative,
                                      task.seed, self.hires, prefix)
        except Exception as exc:
            self._set_state(task, "failed", error="Workflow error: %s" % exc)
            self.log("Task %s failed: %s" % (task.label, exc))
            return
        self._set_state(task, "submitted", stage="base", step=0, total=0)
        try:
            prompt_id = self.client.queue_prompt(workflow)
        except ComfyError as exc:
            self._set_state(task, "failed", error=str(exc))
            self.log("Task %s rejected: %s" % (task.label, exc))
            return
        with self._lock:
            task.prompt_id = prompt_id
            task.state = "running"
            task.started_at = time.time()
        self.log("Task %s submitted (seed %d, %s)" % (task.label, task.seed, prompt_id))

        deadline = time.time() + self.task_timeout
        while time.time() < deadline:
            if self._cancel.is_set():
                self.client.interrupt()
                self._set_state(task, "canceled")
                return
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
                image = images[0] if images else None
                self._set_state(task, "done", image=image, stage="", step=task.total or task.step)
                self.log("Task %s done: %s" % (task.label, image))
                return
            if state == "error":
                self._set_state(task, "failed", error=str(status)[:2000])
                self.log("Task %s failed: %s" % (task.label, status))
                return
            time.sleep(self.poll_interval)
        self._set_state(task, "failed", error="Timed out waiting for ComfyUI")
        self.log("Task %s timed out" % task.label)


def _saved_images(entry: dict[str, Any]) -> list[str]:
    images: list[str] = []
    for node_out in (entry.get("outputs") or {}).values():
        for image in node_out.get("images") or []:
            subfolder = image.get("subfolder") or ""
            filename = image.get("filename") or ""
            if filename:
                images.append("%s/%s" % (subfolder, filename) if subfolder else filename)
    return images
