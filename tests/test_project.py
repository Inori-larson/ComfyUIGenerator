import json
from pathlib import Path

from comfyui_generator.core.project import (
    clear_trash, delete_from_trash,     list_trash, list_projects,
    load_project,
    load_profile,
    clear_story_partial,
    load_session,
    load_story_partial,
    move_to_trash,
    new_project,
    restore_from_trash,
    save_profile,
    save_project,
    save_session,
    save_story_partial,
    configure_projects_dir,
    migrate_project_filenames,
    project_file,
)


TEMPLATE = {
    "model": "WAI\\waiIllustriousSDXL_v170.safetensors",
    "loader": "checkpoint",
    "character": {"tags": "yixuan, solo"},
    "style": {"positive": "masterpiece", "negative": "bad"},
    "settings": {"width": 832, "height": 1216, "steps": 30, "base_seed": 123},
    "shots": [{"id": "01", "name": "old", "prompt": "old shot"}],
}


def test_project_filename_includes_name_suffix(tmp_path):
    configure_projects_dir(tmp_path, tmp_path / "story", tmp_path / "single")
    project = new_project("demo_kimi-k3", "a cat", TEMPLATE)
    path = save_project(project, tmp_path)
    assert path.name == "demo_kimi-k3_%s.json" % project["id"]
    assert path.is_file()


def test_save_project_removes_legacy_id_file(tmp_path):
    configure_projects_dir(tmp_path, tmp_path / "story", tmp_path / "single")
    project = new_project("demo", "a cat", TEMPLATE)
    legacy = tmp_path / "story" / ("%s.json" % project["id"])
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    path = save_project(project, tmp_path)
    assert path.name.startswith("demo_")
    assert not legacy.exists()


def test_migrate_project_filenames(tmp_path):
    configure_projects_dir(tmp_path, tmp_path / "story", tmp_path / "single")
    project = new_project("named_kimi", "a cat", TEMPLATE)
    legacy = tmp_path / "story" / ("%s.json" % project["id"])
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    changes = migrate_project_filenames(tmp_path)
    assert changes
    assert not legacy.exists()
    assert project_file(tmp_path, project).is_file()


def test_new_project_clears_shots_and_adds_meta():
    project = new_project("demo", "a cat", TEMPLATE, "preset.json")
    assert project["shots"] == []
    assert project["name"] == "demo"
    assert project["premise"] == "a cat"
    assert project["template"] == "preset.json"
    assert project["version"] == 1
    assert project["mode"] == "story"
    assert "id" in project
    single = new_project("one", "a cat", TEMPLATE, mode="single")
    assert single["mode"] == "single"


def test_save_load_list(tmp_path):
    project = new_project("demo", "a cat", TEMPLATE)
    project["shots"] = [{"id": "01", "name": "a", "prompt": "b"}]
    path = save_project(project, tmp_path)
    assert path.is_file()
    loaded = load_project(path)
    assert loaded["shots"] == [{
        **project["shots"][0], "ready": True}]
    items = list_projects(tmp_path)
    assert len(items) == 1
    assert items[0]["name"] == "demo"
    assert items[0]["shots"] == 1


def test_save_normalizes_missing_or_null_ready_to_true(tmp_path):
    project = new_project("demo", "a cat", TEMPLATE)
    project["shots"] = [
        {"id": "01", "prompt": "a"},
        {"id": "02", "prompt": "b", "ready": None},
        {"id": "03", "prompt": "c", "ready": False},
    ]
    loaded = load_project(save_project(project, tmp_path))
    assert loaded["shots"][0]["ready"] is True
    assert loaded["shots"][1]["ready"] is True
    assert loaded["shots"][2]["ready"] is False


def test_load_project_defaults_missing_ready_to_true(tmp_path):
    path = tmp_path / "projects" / "old.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"shots": [{"id": "01", "prompt": "x"}]}), encoding="utf-8")
    loaded = load_project(path)
    assert loaded["shots"][0]["ready"] is True


def test_save_load_preserves_ready_and_findings(tmp_path):
    project = new_project("demo", "a cat", TEMPLATE)
    project["shots"] = [{
        "id": "01", "name": "a", "prompt": "b", "ready": False,
        "findings": [{"kind": "male_nude", "message": "缺少 nude male"}],
    }]
    loaded = load_project(save_project(project, tmp_path))
    assert loaded["shots"][0]["ready"] is False
    assert loaded["shots"][0]["findings"] == project["shots"][0]["findings"]


def test_session_roundtrip_and_missing_file(tmp_path):
    assert load_session(tmp_path) == {}
    data = {
        "mode": "story",
        "activation": {"en": "yixuan", "zh": "仪玄"},
        "loras": {"character": {"hero.safetensors": {
            "checked": True, "strength": 0.75}}},
    }
    save_session(data, tmp_path)
    assert load_session(tmp_path) == data


def test_partial_story_roundtrip_and_clear(tmp_path):
    assert load_story_partial(tmp_path) == {}
    save_story_partial({"premise": "story", "shots": [{"id": "01"}]}, tmp_path)
    data = load_story_partial(tmp_path)
    assert data["premise"] == "story"
    assert data["shots"] == [{"id": "01"}]
    assert data["updated"]
    clear_story_partial(tmp_path)
    assert load_story_partial(tmp_path) == {}


def test_corrupt_session_is_ignored(tmp_path):
    (tmp_path / "ui_session.json").write_text("{bad", encoding="utf-8")
    assert load_session(tmp_path) == {}


def test_list_projects_newest_first(tmp_path):
    folder = tmp_path / "projects"
    folder.mkdir()
    for name, updated in (("old", "2026-01-01T10:00:00"),
                          ("new", "2026-10-28T19:00:00"),
                          ("middle", "2026-05-01T10:00:00")):
        (folder / ("%s.json" % name)).write_text(json.dumps({
            "id": name, "name": name, "updated": updated, "shots": [],
        }), encoding="utf-8")
    assert [item["name"] for item in list_projects(tmp_path)] == [
        "new", "middle", "old"]


def test_profile_strips_story_and_seed(tmp_path):
    path = save_profile("demo/name", {
        "name": "demo", "premise": "x", "shots": [1], "prefix": "p",
        "settings": {"width": 832, "base_seed": 999},
    }, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "shots" not in data
    assert "premise" not in data
    assert data["settings"]["width"] == 832
    assert "base_seed" not in data["settings"]
    assert load_profile("demo/name", tmp_path)["name"] == "demo"


def test_trash_move_and_restore(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    image = output / "shot.png"
    image.write_bytes(b"png")
    trash = move_to_trash(image, "proj1", tmp_path)
    assert not image.exists()
    assert trash.is_file()
    assert trash.parent.name == "trash"
    restored = restore_from_trash(trash, output)
    assert restored.is_file()
    assert restored.read_bytes() == b"png"


def test_trash_collision(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    image = output / "shot.png"
    image.write_bytes(b"1")
    first = move_to_trash(image, "p", tmp_path)
    image.write_bytes(b"2")
    second = move_to_trash(image, "p", tmp_path)
    assert first != second
    assert second.name.startswith("shot_2")


def test_trash_index_restore_and_clear(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    image = output / "shot.png"
    image.write_bytes(b"png")
    trash = move_to_trash(image, "p", tmp_path)
    assert list_trash(tmp_path, "p") == [trash]
    restored = restore_from_trash(trash, root=tmp_path, project_id="p")
    assert Path(restored).resolve() == image.resolve()
    assert list_trash(tmp_path, "p") == []

    image.write_bytes(b"png2")
    trash2 = move_to_trash(image, "p", tmp_path)
    delete_from_trash(trash2, tmp_path, "p")
    assert not trash2.exists()
    assert list_trash(tmp_path, "p") == []

    image.write_bytes(b"png3")
    move_to_trash(image, "p", tmp_path)
    clear_trash(tmp_path, "p")
    assert list_trash(tmp_path, "p") == []
