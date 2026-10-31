from comfyui_generator.core.quality import (
    check_project, format_report, repair_project,
)


def _project(**overrides):
    project = {
        "character": {"tags": "silver hair", "use_ipadapter": False},
        "continuity": {
            "character": "silver hair",
            "scene": "bedroom",
            "state": "sweat",
            "negative": "different location",
            "grammar": {"auto": True, "style": "cinematic"},
        },
        "settings": {"split": {"enabled": True}},
        "shots": [{
            "id": "01", "prompt": "standing", "shot_size": "wide shot",
            "camera_angle": "eye level",
        }],
    }
    project.update(overrides)
    return project


def test_clean_project_has_no_critical():
    report = check_project(_project())
    assert report.critical == []
    assert report.warnings == []


def test_chinese_continuity_is_warned():
    project = _project()
    project["continuity"]["character"] = "银色长发"
    report = check_project(project)
    assert any("中文" in item for item in report.warnings)


def test_missing_reference_is_critical(tmp_path):
    missing = tmp_path / "missing.png"
    project = _project(character={
        "tags": "", "use_ipadapter": True,
        "ipadapter": {"reference": str(missing)},
    })
    report = check_project(project)
    assert any("角色参考图" in item for item in report.critical)


def test_double_shot_without_split_is_warned():
    project = _project(settings={"split": {"enabled": False}}, shots=[{
        "id": "01", "prompt": "1girl, 1boy", "cast": "1girl, 1boy",
        "shot_size": "wide shot", "camera_angle": "eye level",
    }])
    report = check_project(project)
    assert any("双人分步" in item for item in report.warnings)


def test_cross_gender_anatomy_is_warned():
    project = _project(shots=[{
        "id": "01", "prompt": "1girl, 1boy", "cast": "1girl, 1boy",
        "shot_size": "wide shot", "camera_angle": "eye level",
        "prompt_groups": [
            {"gender": "girl", "prompt": "1girl, nude"},
            {"gender": "boy", "prompt": "1boy, large breasts"},
        ],
    }])
    report = check_project(project)
    assert any("男主" in item and "女性" in item for item in report.warnings)


def test_format_report_never_empty():
    report = check_project(_project())
    assert format_report(report) == "未发现连续性问题。"


def test_repair_disables_missing_reference_and_enables_split(tmp_path):
    project = _project(
        character={
            "tags": "", "use_ipadapter": True,
            "ipadapter": {"reference": str(tmp_path / "missing.png")},
        },
        settings={"split": {"enabled": False}},
        shots=[{
            "id": "01", "prompt": "1girl, 1boy", "cast": "1girl, 1boy",
        }],
    )
    repaired, changes = repair_project(project)
    assert repaired["character"]["use_ipadapter"] is False
    assert repaired["settings"]["split"]["enabled"] is True
    assert any("IPAdapter" in item for item in changes)
    assert any("双人分步" in item for item in changes)
    assert repaired["shots"][0]["shot_size"]


def test_repair_removes_cross_gender_anatomy():
    project = _project(shots=[{
        "id": "01", "prompt": "1girl, 1boy", "cast": "1girl, 1boy",
        "shot_size": "wide shot", "camera_angle": "eye level",
        "prompt_groups": [
            {"gender": "girl", "prompt": "1girl, nude, penis"},
            {"gender": "boy", "prompt": "1boy, large breasts"},
        ],
    }])
    repaired, changes = repair_project(project)
    groups = repaired["shots"][0]["prompt_groups"]
    assert groups[0]["prompt"] == "1girl, nude"
    assert groups[1]["prompt"] == "1boy"
    assert any("跨性别" in item for item in changes)
