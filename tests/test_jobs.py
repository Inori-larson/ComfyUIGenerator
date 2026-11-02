from comfyui_generator.core.expand import apply_expansion_delta, sanitize_expansion_prompt
from comfyui_generator.core.expand_ai import (
    build_expansion_messages, generate_expansions,
)
from comfyui_generator.core.jobs import (
    TaskRunner, build_tasks, cross_shot_allowed,
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


def test_variants_and_expansions_get_unique_increment_seeds():
    shots = [{
        "id": "01", "name": "a", "prompt": "p",
        "ai_expansions": ["e1", "e2"],
    }]
    tasks = build_tasks({}, shots, variants=3, seed_mode="increment",
                        base_seed=100, expansions=2)
    seeds = [task.seed for task in tasks]
    assert len(seeds) == 9
    assert len(set(seeds)) == 9
    assert seeds == list(range(100, 109))


def test_fixed_seed():
    tasks = build_tasks({}, [SHOTS[0]], variants=3, seed_mode="fixed", base_seed=777)
    assert {task.seed for task in tasks} == {777}


def test_random_seed_bounds():
    tasks = build_tasks({}, [SHOTS[0]], variants=4, seed_mode="random", base_seed=1)
    assert len(tasks) == 4
    assert all(0 <= task.seed <= 2 ** 31 - 1 for task in tasks)


def _cross_tasks():
    shots = [
        {"id": "01", "name": "a", "prompt": "1girl, bedroom", "scene": "bedroom"},
        {"id": "02", "name": "b", "prompt": "1girl, bedroom", "scene": "bedroom"},
    ]
    prev, curr = build_tasks({}, shots, 1, "fixed", 1)
    prev.image = "one.png"
    prev.state = "done"
    return prev, curr


def test_cross_shot_requires_enabled_switch():
    prev, curr = _cross_tasks()
    assert cross_shot_allowed(prev, curr, {"enabled": True, "cross_shot": True})
    assert not cross_shot_allowed(prev, curr, {"enabled": True})
    assert not cross_shot_allowed(prev, curr, {"enabled": False, "cross_shot": True})


def test_cross_shot_skips_same_shot_and_double_shot():
    prev, curr = _cross_tasks()
    same = build_tasks({}, [SHOTS[0]], 1, "fixed", 1)[0]
    same.image = "one.png"
    same.state = "done"
    assert not cross_shot_allowed(same, same, {"enabled": True, "cross_shot": True})
    double = build_tasks({}, [{
        "id": "02", "name": "b", "prompt": "1girl, 1boy, bedroom",
        "scene": "bedroom",
    }], 1, "fixed", 1)[0]
    assert not cross_shot_allowed(prev, double, {"enabled": True, "cross_shot": True})
    curr.shot["scene"] = "kitchen"
    assert not cross_shot_allowed(prev, curr, {"enabled": True, "cross_shot": True})
    curr.shot["scene"] = "bedroom, night"
    assert cross_shot_allowed(prev, curr, {"enabled": True, "cross_shot": True})
    curr.shot["scene"] = "bedroom"
    curr.shot["init_image"] = "manual.png"
    assert not cross_shot_allowed(prev, curr, {"enabled": True, "cross_shot": True})


def test_task_summary_fields():
    task = build_tasks({}, [SHOTS[0]], 1, "increment", 1)[0]
    summary = task.summary()
    assert summary["state"] == "pending"
    assert summary["label"] == "01_a"
    assert summary["seed"] == 1


def test_keyframe_prompt_overrides_only_keyframe_task():
    shot = {
        "id": "01", "name": "a", "prompt": "final state",
        "keyframe_prompt": "start state",
        "ai_expansions": ["next state"],
    }
    tasks = build_tasks({}, [shot], 1, "fixed", 1, expansions=1)
    assert tasks[0].kind == "keyframe"
    assert tasks[0].shot["prompt"] == "start state"
    assert tasks[1].kind == "expand"
    assert tasks[1].shot["prompt"] == "next state"


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


def test_single_expansion_denoise_stays_low_and_rises():
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


def test_sequence_expansion_uses_stronger_denoise():
    shot = {"id": "01", "name": "a", "prompt": "shot",
            "ai_expansions": ["a", "b", "c"]}
    tasks = build_tasks({}, [shot], 1, "increment", 100, expansions=3)
    expand = [task for task in tasks if task.kind == "expand"]
    runner = TaskRunner(
        None, {"settings": {"img2img": {
            "denoise": 0.35, "sequence_mode": True}}}, [], "")
    values = [runner._expand_denoise(task) for task in expand]
    assert 0.82 <= values[0] <= 0.86
    assert values[-1] <= 0.92
    assert values[0] < values[-1]


def test_expansion_delta_applies_ai_remove_and_add_without_semantic_rewrite():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, red_eyes, red_hair, arms_up, bedroom",
    }
    result = apply_expansion_delta(
        shot["prompt"], ["arms_up"],
        ["hand_resting_on_hip", "calm_expression"],
        shot, None)
    assert "hand_resting_on_hip" in result
    assert "calm_expression" in result
    assert "red_eyes" in result
    assert "red_hair" in result
    assert "arms_up" not in result
    assert "bedroom" in result


def test_expansion_keeps_ai_state_unless_ai_explicitly_removes_it():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, deep penetration, penis in pussy, cum, bedroom",
    }
    shallow = apply_expansion_delta(
        shot["prompt"], [], ["shallow penetration"], shot, None)
    assert "shallow penetration" in shallow
    assert "deep penetration" in shallow
    assert "penis in pussy" in shallow
    assert "cum" in shallow

    pulled = apply_expansion_delta(
        shallow, ["deep penetration", "penis in pussy"],
        ["penis pullout", "after sex"], shot, None)
    assert "penis pullout" in pulled
    assert "after sex" in pulled
    assert "deep penetration" not in pulled
    assert "penis in pussy" not in pulled


def test_sanitize_expansion_only_dedupes_and_preserves_ai_tags():
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
        "panties aside, penetration, thrusting, completely nude, white_shirt",
        shot, next_shot)
    tags = [tag.strip() for tag in prompt.split(",")]
    for expected in (
            "white_shirt", "black_pantyhose", "panties", "panties aside",
            "penetration", "thrusting", "completely nude"):
        assert expected in tags
    assert tags.count("white_shirt") == 1


def test_sanitize_expansion_preserves_unknown_actions_and_scene_details():
    shot = {"id": "01", "prompt": "1girl, warrior, standing, sword_sheathed"}
    next_shot = {"id": "02", "prompt": "1girl, warrior, standing, smile"}
    prompt = sanitize_expansion_prompt(
        "1girl, warrior, standing, sword_sheathed, blood_on_face, "
        "holding_gun, broken_window, hand_on_cheek",
        shot, next_shot)
    for expected in (
            "blood_on_face", "holding_gun", "broken_window", "hand_on_cheek"):
        assert expected in prompt


def test_sanitize_expansion_preserves_partner_actions_in_solo_shot():
    shot = {"id": "01", "name": "a", "prompt": "1girl, solo, lying, on table"}
    prompt = sanitize_expansion_prompt(
        "1girl, solo, lying, on table, legs wrapped around waist, "
        "arms around neck, kissing, 1boy, hand_on_table, pussy",
        shot, None)
    for expected in (
            "legs wrapped around waist", "arms around neck", "kissing",
            "1boy", "hand_on_table", "pussy"):
        assert expected in prompt


def test_build_expansion_messages_includes_next_shot_and_count():
    shots = [
        {"id": "01", "prompt": "p1"},
        {"id": "02", "prompt": "p2"},
    ]
    messages = build_expansion_messages(shots, 4)
    user = messages[-1]["content"]
    assert '"state_count": 4' in user
    assert '"next"' in user and '"prompt": "p2"' in user
    assert '"mode": "continuation"' in user


def test_build_expansion_messages_can_request_sequence_mode():
    messages = build_expansion_messages(
        [{"id": "01", "prompt": "p1"}], 5, sequence=True)
    assert '"mode": "sequence"' in messages[-1]["content"]


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


def test_sequence_mode_uses_ai_deltas_without_hardcoded_reset():
    class FakeClient:
        def chat_json(self, model, messages, **kwargs):
            return {"expansions": [{
                "id": "01",
                "steps": [
                    {"remove": ["cum", "deep penetration"],
                     "add": ["cum on body", "shallow penetration"]},
                    {"remove": ["shallow penetration"],
                     "add": ["moderate penetration", "arm under head"]},
                    {"remove": ["moderate penetration"],
                     "add": ["deeper penetration", "parted lips"]},
                ],
            }]}

    shots = [{
        "id": "01",
        "prompt": "1girl, cum, cum on body, deep penetration, bedroom",
    }]
    result = generate_expansions(
        FakeClient(), "model", shots, 2, sequence=True)
    prompts = result["01"]
    assert len(prompts) == 3
    assert "deep penetration" not in prompts[0]
    assert "shallow penetration" in prompts[0]
    assert "moderate penetration" in prompts[1]
    assert "deeper penetration" in prompts[2]


def test_apply_delta_removes_only_explicit_ai_remove():
    shot = {"id": "01", "prompt": "1girl, cum, deep penetration"}
    kept = apply_expansion_delta(
        "1girl, cum, deep penetration", [],
        ["cum on thighs", "shallow penetration"], shot, None)
    assert "cum" in kept
    assert "deep penetration" in kept
    assert "cum on thighs" in kept
    assert "shallow penetration" in kept

    removed = apply_expansion_delta(
        "1girl, cum, deep penetration", ["cum", "deep penetration"],
        ["cum on thighs", "shallow penetration"], shot, None)
    tags = [tag.strip() for tag in removed.split(",")]
    assert "cum" not in tags
    assert "deep penetration" not in tags
    assert "cum on thighs" in tags


def test_sanitize_expansion_preserves_damage_and_intact_tags_from_ai():
    shot = {"id": "01", "prompt": "1girl, crotchless pantyhose, torn shirt"}
    prompt = sanitize_expansion_prompt(
        "1girl, crotchless pantyhose, torn shirt, pantyhose intact",
        shot, None)
    assert "crotchless pantyhose" in prompt
    assert "torn shirt" in prompt
    assert "pantyhose intact" in prompt


def test_apply_delta_does_not_replace_old_limb_pose_without_remove():
    shot = {"prompt": "1girl, lying, on back, spread legs, arms up, vaginal sex"}
    kept = apply_expansion_delta(
        shot["prompt"], [],
        ["legs wrapped around his waist", "hands on his shoulders"],
        shot, None)
    assert "legs wrapped around his waist" in kept
    assert "hands on his shoulders" in kept
    assert "spread legs" in kept
    assert "arms up" in kept
    assert "lying" in kept
    assert "vaginal sex" in kept

    replaced = apply_expansion_delta(
        shot["prompt"], ["spread legs", "arms up"],
        ["legs wrapped around his waist", "hands on his shoulders"],
        shot, None)
    assert "spread legs" not in replaced
    assert "arms up" not in replaced
