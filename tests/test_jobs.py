from comfyui_generator.core.expand import apply_expansion_delta, sanitize_expansion_prompt
from comfyui_generator.core.expand_ai import (
    build_expansion_messages, generate_expansions,
)
from comfyui_generator.core.jobs import TaskRunner, build_tasks


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


def test_expansion_tasks_use_ai_prompts():
    shots = [
        {"id": "01", "name": "a", "prompt": "cowgirl_position, riding",
         "ai_expansions": ["ai one", "ai two", "ai three"]},
        {"id": "02", "name": "b", "prompt": "doggy, bed",
         "ai_expansions": ["ai four", "ai five"]},
    ]
    tasks = build_tasks({}, shots, 1, "increment", 1, expansions=3)
    assert [task.kind for task in tasks] == [
        "keyframe", "expand", "expand", "expand",
        "keyframe", "expand", "expand"]
    expand = [task for task in tasks if task.kind == "expand"]
    assert [task.shot["prompt"] for task in expand] == [
        "ai one", "ai two", "ai three", "ai four", "ai five"]
    assert all(task.shot["base_shot_id"] == "01" for task in expand[:3])
    assert all(task.shot["base_shot_id"] == "02" for task in expand[3:])


def test_expansion_without_ai_prompts_stays_keyframe_only():
    tasks = build_tasks({}, SHOTS, 1, "increment", 1, expansions=3)
    assert [task.kind for task in tasks] == ["keyframe", "keyframe"]


def test_expansion_denoise_stays_low_and_rises():
    shot = {"id": "01", "name": "a", "prompt": "shot",
            "ai_expansions": ["a", "b", "c"]}
    tasks = build_tasks({}, [shot], 1, "increment", 100, expansions=3)
    expand = [task for task in tasks if task.kind == "expand"]
    runner = TaskRunner(
        None, {"settings": {"img2img": {"denoise": 0.35}}}, [], "")
    values = [runner._expand_denoise(task) for task in expand]
    assert 0.65 <= values[0] <= 0.74
    assert values[-1] <= 0.85
    assert values[0] < values[-1]


def test_sanitize_expansion_blocks_future_clothing_and_penetration():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, 1boy, white_shirt, black_pantyhose, panties, riding",
    }
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, 1boy, white_shirt, black_pantyhose, panties, riding, smile",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, white_shirt, black_pantyhose, panties, "
        "panties aside, penetration, thrusting, completely nude",
        shot, next_shot)
    assert "white_shirt" in prompt
    assert "black_pantyhose" in prompt
    assert "panties aside" not in prompt
    assert "penetration" not in prompt
    assert "thrusting" not in prompt
    assert "completely nude" not in prompt


def test_sanitize_expansion_allows_nudity_when_next_shot_is_nude():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, cowgirl_position"}
    next_shot = {"id": "02", "name": "b", "prompt": "1girl, 1boy, completely nude"}
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, completely nude, penetration, thrusting", shot, next_shot)
    assert "completely nude" in prompt
    assert "penetration" in prompt
    assert "thrusting" in prompt


def test_sanitize_expansion_single_has_no_next_guard():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, cowgirl_position, panties"}
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, cowgirl_position, panties, completely nude, cum",
        shot, None)
    assert "completely nude" in prompt
    assert "cum" in prompt


def test_sanitize_expansion_removes_missing_clothing_item():
    shot = {"id": "01", "name": "a",
            "prompt": "1girl, 1boy, cowgirl_position, black pantyhose"}
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, panties aside, bra pull, open shirt, black pantyhose",
        shot, None)
    assert "panties aside" not in prompt
    assert "bra pull" not in prompt
    assert "open shirt" not in prompt
    assert "black pantyhose" in prompt


def test_build_expansion_messages_includes_next_shot_and_count():
    shots = [
        {"id": "01", "prompt": "p1"},
        {"id": "02", "prompt": "p2"},
    ]
    messages = build_expansion_messages(shots, 4)
    user = messages[-1]["content"]
    assert '"expansion_count": 4' in user
    assert '"next"' in user and '"prompt": "p2"' in user


def test_generate_expansions_parses_ai_json():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"expansions": [{
                "id": "01",
                "steps": [
                    {"remove": ["park"], "add": ["tree", "shade", "walking", "smile"]},
                    {"remove": ["walking"], "add": ["sitting", "bench", "reading", "relaxed"]},
                ],
            }]}

    shots = [{"id": "01", "prompt": "1girl, park"}]
    result = generate_expansions(
        FakeClient(), "model", shots, 2, chunk=6)
    assert "1girl" in result["01"][0]
    assert "tree" in result["01"][0]
    assert "bench" in result["01"][1]
    assert result["01"][0] != result["01"][1]


def test_apply_delta_never_removes_existing_fluid():
    shot = {"id": "01", "prompt": "1girl, cum, deep penetration"}
    result = apply_expansion_delta(
        "1girl, cum, deep penetration",
        ["cum", "deep penetration"],
        ["cum on thighs", "shallow penetration"],
        shot, None,
    )
    assert "cum" in result
    assert "cum on thighs" in result
    assert "deep penetration" not in result


def test_damage_state_does_not_become_intact():
    shot = {"id": "01", "prompt": "1girl, crotchless pantyhose, torn shirt"}
    prompt = sanitize_expansion_prompt(
        "1girl, crotchless pantyhose, torn shirt, pantyhose intact",
        shot, None)
    assert "crotchless pantyhose" in prompt
    assert "torn shirt" in prompt
    assert "pantyhose intact" not in prompt


def test_apply_delta_replaces_old_limb_pose():
    shot = {"prompt": "1girl, lying, on back, spread legs, arms up, vaginal sex"}
    prompt = apply_expansion_delta(
        shot["prompt"], [],
        ["legs wrapped around his waist", "hands on his shoulders"],
        shot, None)
    assert "legs wrapped around his waist" in prompt
    assert "hands on his shoulders" in prompt
    assert "spread legs" not in prompt
    assert "arms up" not in prompt
    assert "lying" in prompt
    assert "vaginal sex" in prompt
