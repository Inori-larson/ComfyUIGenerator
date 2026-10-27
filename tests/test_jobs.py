from comfyui_generator.core.jobs import build_tasks


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
