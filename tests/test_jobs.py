from comfyui_generator.core.jobs import (
    TaskRunner, bridge_count, build_tasks, shot_difference,
)


SHOTS = [
    {"id": "01", "name": "a", "prompt": "wide"},
    {"id": "02", "name": "b", "prompt": "close", "seed": 5},
]


def test_increment_seeds_and_variant_labels():
    tasks = build_tasks({}, SHOTS, variants=2, seed_mode="increment", base_seed=100)
    assert [task.seed for task in tasks] == [100, 101, 5, 6]
    assert [task.variant for task in tasks] == [1, 2, 1, 2]
    assert tasks[0].label == "01_a_v01"
    assert tasks[2].label == "02_b_v01"


def test_single_variant_has_no_suffix():
    tasks = build_tasks({}, SHOTS, variants=1, seed_mode="increment", base_seed=100)
    assert tasks[0].label == "01_a"


def test_fixed_seed():
    tasks = build_tasks({}, [SHOTS[0]], variants=3, seed_mode="fixed", base_seed=777)
    assert {task.seed for task in tasks} == {777}


def test_random_seed_bounds():
    tasks = build_tasks({}, [SHOTS[0]], variants=4, seed_mode="random", base_seed=1)
    assert len(tasks) == 4
    assert all(0 <= task.seed <= 2 ** 31 - 1 for task in tasks)


def test_task_summary_fields():
    task = build_tasks({}, [SHOTS[0]], 1, "increment", 1)[0]
    summary = task.summary()
    assert summary["state"] == "pending"
    assert summary["label"] == "01_a"
    assert summary["seed"] == 1


def test_img2img_denoise_rises_for_sex_phase():
    runner = TaskRunner(
        None, {"settings": {"img2img": {"denoise": 0.35}}}, [], "")
    assert runner._img2img_denoise({"phase": "story"}) == 0.35
    assert runner._img2img_denoise({"phase": "sex"}) == 0.5


def test_build_tasks_inserts_bridge_tasks_between_shots():
    tasks = build_tasks({}, SHOTS, 1, "increment", 100, bridges=2)
    assert [task.kind for task in tasks] == [
        "keyframe", "bridge", "bridge", "keyframe"]
    assert tasks[1].bridge_source == "01"
    assert tasks[1].bridge_target == "02"
    assert tasks[2].bridge_step == 2
    assert tasks[1].bridge_delta > 0.5
    assert "sex" not in tasks[1].shot["prompt"]


def test_auto_bridge_count_is_derived_from_difference():
    tasks = build_tasks({}, SHOTS, 1, "increment", 100, auto_bridges=True)
    bridge_tasks = [task for task in tasks if task.kind == "bridge"]
    assert len(bridge_tasks) == 4
    assert [task.kind for task in tasks] == [
        "keyframe"] + ["bridge"] * 4 + ["keyframe"]


def test_bridge_count_and_difference_follow_shot_change():
    same = {"prompt": "1girl, sofa", "cast": "1girl solo", "scene": "living room"}
    changed = {"prompt": "1girl, 1boy, bed, nude", "cast": "1girl 1boy",
               "scene": "bedroom", "phase": "sex"}
    assert shot_difference(same, same) == 0.0
    assert shot_difference(same, changed) > 0.5
    assert bridge_count(0.0, 4) == 1
    assert bridge_count(0.5, 4) == 3
    assert bridge_count(1.0, 4) == 4
    assert bridge_count(1.0, 0) == 0


def test_bridge_denoise_uses_difference():
    runner = TaskRunner(
        None, {"settings": {"img2img": {"denoise": 0.35}}}, [], "")
    low = build_tasks({}, SHOTS, 1, "increment", 100, bridges=4)[1]
    low.bridge_delta = 0.1
    high = build_tasks({}, SHOTS, 1, "increment", 100, bridges=4)[1]
    high.bridge_delta = 0.8
    assert runner._bridge_denoise(high) > runner._bridge_denoise(low)
    assert runner._bridge_denoise(high) >= 0.6
