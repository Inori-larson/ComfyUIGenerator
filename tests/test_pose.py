from comfyui_generator.core.pose import (
    CLASSIC_POSE_LABELS,
    POSE_PRESET_LABELS,
    builtin_pose_json,
    builtin_pose_reference,
    generate_pose_json_skeleton,
    generate_pose_skeleton,
    load_pose_presets,
    pose_keypoints,
    pose_pair_only,
    pose_preset_for_shot,
    pose_should_apply,
    save_pose_presets,
)


def test_pose_presets_follow_action_text():
    assert pose_preset_for_shot({"prompt": "cowgirl, riding"}) == "cowgirl"
    assert pose_preset_for_shot({"description": "她跨坐到我腿上"}) == "cowgirl"
    assert pose_preset_for_shot({"description": "男主从后面抱起她"}) == "rear_carry"
    assert pose_preset_for_shot({"prompt": "doggystyle, from behind"}) == "classic_doggystyle"
    assert pose_preset_for_shot({"description": "两人上下叠在一起"}) == "stacked"
    assert pose_preset_for_shot({"description": "男主在她上方"}) == "stacked"
    assert pose_preset_for_shot({"description": "男主在她下面"}) == "cowgirl"
    assert pose_preset_for_shot({"prompt": "missionary, legs up"}) == "classic_missionary"
    assert pose_preset_for_shot({"prompt": "69"}) == "classic_69"
    assert pose_preset_for_shot({"prompt": "blowjob"}) == "classic_bj_front"
    assert pose_preset_for_shot({"description": "她坐在他脸上"}) == "classic_facesitting"
    assert pose_preset_for_shot({"prompt": "milking table"}) == "classic_sex_under_table"
    assert pose_preset_for_shot({"prompt": "under table blowjob"}) == "classic_under_table_bj"
    assert pose_preset_for_shot({"prompt": "footjob"}) == "classic_footjob"
    assert pose_preset_for_shot({"prompt": "lying cunnilingus"}) == "classic_lying_cunnilingus"
    assert pose_preset_for_shot({"prompt": "front facing doggystyle"}) == "classic_front_doggy"
    assert pose_preset_for_shot({"prompt": "virtual sex, pov sex"}) == "classic_virtual_sex"
    assert pose_preset_for_shot({"description": "他前倾插入"}) == "classic_leaning_vaginal"
    assert pose_preset_for_shot({"prompt": "standing behind"}) == "classic_standing_behind"
    assert pose_preset_for_shot({"description": "舔肛"}) == "classic_rimming"
    assert pose_preset_for_shot({"prompt": "standing"}) == "standing"
    assert pose_preset_for_shot({"prompt": "smile"}) == "side_by_side"
    assert pose_preset_for_shot({"prompt": "smile"}, "spooning") == "spooning"
    assert pose_preset_for_shot({"prompt": "smile"}, "doggy") == "classic_doggystyle"
    assert pose_preset_for_shot({"prompt": "smile"}, "missionary") == "classic_missionary"
    assert pose_preset_for_shot({"prompt": "smile"}, "classic_69") == "classic_69"


def test_classic_pose_reference_assets_exist():
    assert len(CLASSIC_POSE_LABELS) == 21
    for preset in CLASSIC_POSE_LABELS:
        png = builtin_pose_reference(preset)
        js = builtin_pose_json(preset)
        path = png or js
        assert path is not None and path.is_file()
        if png:
            assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert pose_pair_only(preset)
    assert not pose_pair_only("cowgirl")


def test_generate_classic_json_pose(tmp_path):
    pair = generate_pose_json_skeleton(
        "classic_doggystyle", 256, 384,
        destination=tmp_path / "doggy.png")
    girl = generate_pose_json_skeleton(
        "classic_doggystyle", 256, 384, people=("girl",),
        destination=tmp_path / "doggy_girl.png")
    assert pair.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert girl.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert pair.stat().st_size > girl.stat().st_size


def test_pose_is_skipped_for_partial_male_framing():
    assert not pose_should_apply({"description": "男主只露出手"})
    assert not pose_should_apply({"prompt": "only his hand"})
    assert pose_should_apply({"description": "两人抱在一起"})


def test_custom_pose_keypoints_override_and_roundtrip(tmp_path):
    custom = {"cowgirl": {"girl": {"nose": [0.25, 0.35]}}}
    poses = pose_keypoints("cowgirl", custom)
    assert poses["girl"]["nose"] == (0.25, 0.35)
    base = pose_keypoints("cowgirl", None)
    assert base["girl"]["nose"] != (0.25, 0.35)

    path = tmp_path / "pose_presets.json"
    save_pose_presets(path, custom)
    assert load_pose_presets(path) == custom


def test_generate_pose_skeleton_uses_custom_keypoints(tmp_path):
    base = generate_pose_skeleton(
        "doggy", 200, 300, people=("girl", "boy"),
        destination=tmp_path / "base.png")
    custom = {
        "doggy": {
            "girl": {
                "nose": [0.15, 0.25],
                "neck": [0.20, 0.30],
                "rhip": [0.30, 0.40],
                "lhip": [0.32, 0.42],
            },
        },
    }
    edited = generate_pose_skeleton(
        "doggy", 200, 300, people=("girl", "boy"),
        destination=tmp_path / "custom.png", custom=custom)
    assert edited.read_bytes() != base.read_bytes()


def test_generate_pose_skeleton_writes_png(tmp_path):
    girl = generate_pose_skeleton(
        "cowgirl", 256, 384, people=("girl",),
        destination=tmp_path / "girl.png")
    both = generate_pose_skeleton(
        "cowgirl", 256, 384, people=("girl", "boy"),
        destination=tmp_path / "both.png")
    assert girl.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert both.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert both.stat().st_size > girl.stat().st_size
    assert set(POSE_PRESET_LABELS) >= {"cowgirl", "stacked", "spooning"}

    adjusted = generate_pose_skeleton(
        "cowgirl", 256, 384, people=("girl", "boy"),
        destination=tmp_path / "adjusted.png",
        adjust={"boy": {"dx": 0.1, "dy": -0.05, "scale": 1.2,
                        "rotation": 15}})
    assert adjusted.read_bytes() != both.read_bytes()
