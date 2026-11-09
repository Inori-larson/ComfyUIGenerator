"""Project / profile persistence and trash handling."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_VERSION = 1
SESSION_FILE = "ui_session.json"
PARTIAL_STORY_FILE = "story_partial.json"
PLOT_HISTORY_FILE = "plot_history.json"
PLOT_HISTORY_LIMIT = 50
_CONFIGURED_ROOT: Path | None = None
_CONFIGURED_PROJECTS: Path | None = None
_CONFIGURED_SINGLE_PROJECTS: Path | None = None


def configure_projects_dir(root: Path, projects: Path,
                           single_projects: Path | None = None) -> None:
    global _CONFIGURED_ROOT, _CONFIGURED_PROJECTS, _CONFIGURED_SINGLE_PROJECTS
    _CONFIGURED_ROOT = Path(root)
    _CONFIGURED_PROJECTS = Path(projects)
    _CONFIGURED_SINGLE_PROJECTS = (
        Path(single_projects) if single_projects is not None else Path(projects))


def new_project(name: str, premise: str, template: dict[str, Any],
                template_path: str = "", mode: str = "story") -> dict[str, Any]:
    project = dict(template)
    project.pop("shots", None)
    project["version"] = PROJECT_VERSION
    project["id"] = uuid.uuid4().hex[:12]
    project["name"] = name or time.strftime("story_%Y%m%d_%H%M%S")
    project["mode"] = mode
    project["premise"] = premise
    project["template"] = template_path
    project["created"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    project["updated"] = project["created"]
    project["shots"] = []
    project["outputs"] = []
    return project


def projects_dir(root: Path, mode: str = "") -> Path:
    path = Path(root)
    if (_CONFIGURED_ROOT is not None and _CONFIGURED_PROJECTS is not None
            and path == _CONFIGURED_ROOT):
        if (mode == "single" and _CONFIGURED_SINGLE_PROJECTS is not None):
            path = _CONFIGURED_SINGLE_PROJECTS
        else:
            path = _CONFIGURED_PROJECTS
    else:
        path = path / ("single" if mode == "single" else "projects")
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_file(root: Path, project: dict[str, Any]) -> Path:
    return projects_dir(root, str(project.get("mode") or "")) / (
        "%s.json" % project["id"])


def shot_is_ready(shot: Any) -> bool:
    if not isinstance(shot, dict):
        return True
    value = shot.get("ready")
    return "ready" not in shot or value is not False


def _normalize_loaded_project(data: dict[str, Any]) -> dict[str, Any]:
    for shot in data.get("shots") or []:
        if isinstance(shot, dict):
            shot["ready"] = shot_is_ready(shot)
    return data


def save_project(project: dict[str, Any], root: Path) -> Path:
    _normalize_loaded_project(project)
    project["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = project_file(root, project)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_loaded_project(data)


def session_file(root: Path) -> Path:
    return root / SESSION_FILE


def save_session(data: dict[str, Any], root: Path) -> Path:
    path = session_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_session(root: Path) -> dict[str, Any]:
    path = session_file(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def partial_story_file(root: Path) -> Path:
    path = root / "cache" / PARTIAL_STORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_story_partial(data: dict[str, Any], root: Path) -> Path:
    path = partial_story_file(root)
    data = dict(data)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_story_partial(root: Path) -> dict[str, Any]:
    path = partial_story_file(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def clear_story_partial(root: Path) -> None:
    path = partial_story_file(root)
    if path.is_file():
        path.unlink()


def plot_history_file(root: Path) -> Path:
    path = root / "cache" / PLOT_HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_plot_history(root: Path) -> list[dict[str, Any]]:
    path = plot_history_file(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def add_plot_history(root: Path, plot: str,
                     *, max_items: int = PLOT_HISTORY_LIMIT) -> list[dict[str, Any]]:
    plot = str(plot or "").strip()
    if not plot:
        return load_plot_history(root)
    items = [item for item in load_plot_history(root)
             if str(item.get("plot", "")).strip() != plot]
    items.insert(0, {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "plot": plot,
    })
    del items[max_items:]
    path = plot_history_file(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return items


def list_projects(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for mode in ("story", "single"):
        for path in sorted(projects_dir(root, mode).glob("*.json")):
            if path in seen:
                continue
            seen.add(path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append({
                "id": data.get("id", path.stem),
                "name": data.get("name", path.stem),
                "mode": data.get("mode", ""),
                "updated": data.get("updated", ""),
                "shots": len(data.get("shots") or []),
                "path": str(path),
            })
    items.sort(key=lambda item: item.get("updated", ""), reverse=True)
    return items


def delete_project(project: dict[str, Any], root: Path) -> None:
    path = project_file(root, project)
    if path.is_file():
        path.unlink()
    folder = projects_dir(root, str(project.get("mode") or "")) / project["id"]
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- profiles

def profiles_dir(root: Path) -> Path:
    path = root / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_profile(name: str, data: dict[str, Any], root: Path) -> Path:
    payload = dict(data)
    for key in ("story", "premise", "shots", "outputs", "prefix", "id", "created", "updated"):
        payload.pop(key, None)
    settings = payload.get("settings")
    if isinstance(settings, dict):
        settings = dict(settings)
        settings.pop("base_seed", None)
        payload["settings"] = settings
    path = profiles_dir(root) / ("%s.json" % _safe_name(name))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_profile(name: str, root: Path) -> dict[str, Any]:
    path = Path(name)
    if not path.is_file():
        path = profiles_dir(root) / ("%s.json" % _safe_name(name))
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles(root: Path) -> list[str]:
    return sorted(path.stem for path in profiles_dir(root).glob("*.json"))


# ---------------------------------------------------------------- trash

def _safe_name(name: str) -> str:
    keep = "-_.() "
    return "".join(ch for ch in str(name) if ch.isalnum() or ch in keep).strip() or "item"


def trash_dir(root: Path, project_id: str) -> Path:
    path = projects_dir(root) / project_id / "trash"
    path.mkdir(parents=True, exist_ok=True)
    return path


TRASH_INDEX = "index.json"


def _trash_index_path(root: Path, project_id: str) -> Path:
    return trash_dir(root, project_id) / TRASH_INDEX


def _load_index(root: Path, project_id: str) -> dict[str, str]:
    path = _trash_index_path(root, project_id)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_index(root: Path, project_id: str, index: dict[str, str]) -> None:
    path = _trash_index_path(root, project_id)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def move_to_trash(path: str | Path, project_id: str, root: Path) -> Path:
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(src)
    dest_dir = trash_dir(root, project_id)
    dest = dest_dir / src.name
    counter = 2
    while dest.exists():
        dest = dest_dir / ("%s_%d%s" % (src.stem, counter, src.suffix))
        counter += 1
    shutil.move(str(src), str(dest))
    index = _load_index(root, project_id)
    index[dest.name] = str(src.resolve())
    _save_index(root, project_id, index)
    return dest


def trash_original(path: str | Path, project_id: str, root: Path) -> str:
    return _load_index(root, project_id).get(Path(path).name, "")


def list_trash(root: Path, project_id: str) -> list[Path]:
    folder = trash_dir(root, project_id)
    return sorted(p for p in folder.iterdir() if p.is_file() and p.name != TRASH_INDEX)


def restore_from_trash(path: str | Path, target_dir: str | Path | None = None,
                       root: Path | None = None, project_id: str | None = None) -> Path:
    src = Path(path)
    target: Path | None = None
    if target_dir is not None:
        target = Path(target_dir) / src.name
    elif root is not None and project_id is not None:
        original = _load_index(root, project_id).get(src.name)
        if original:
            target = Path(original)
    if target is None:
        raise ValueError("No restore target for %s" % src)
    if target.exists():
        target = target.with_name("%s_restored%s" % (target.stem, target.suffix))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    if root is not None and project_id is not None:
        index = _load_index(root, project_id)
        index.pop(src.name, None)
        _save_index(root, project_id, index)
    return target


def delete_from_trash(path: str | Path, root: Path, project_id: str) -> None:
    src = Path(path)
    if src.is_file():
        src.unlink()
    index = _load_index(root, project_id)
    index.pop(src.name, None)
    _save_index(root, project_id, index)


def clear_trash(root: Path, project_id: str) -> None:
    for item in list_trash(root, project_id):
        item.unlink()
    _save_index(root, project_id, {})
