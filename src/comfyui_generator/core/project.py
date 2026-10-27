"""Project / profile persistence and trash handling."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_VERSION = 1


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


def projects_dir(root: Path) -> Path:
    path = root / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_file(root: Path, project: dict[str, Any]) -> Path:
    return projects_dir(root) / ("%s.json" % project["id"])


def save_project(project: dict[str, Any], root: Path) -> Path:
    project["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = project_file(root, project)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(projects_dir(root).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", path.stem),
            "updated": data.get("updated", ""),
            "shots": len(data.get("shots") or []),
            "path": str(path),
        })
    return items


def delete_project(project: dict[str, Any], root: Path) -> None:
    path = project_file(root, project)
    if path.is_file():
        path.unlink()
    folder = projects_dir(root) / project["id"]
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
