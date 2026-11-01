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


def test_expansion_replaces_old_hand_and_expression_tags():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, red_eyes, red_hair, arms_up, grabbing_own_breast, "
                  "open_mouth, half-closed_eyes, looking_at_viewer, bedroom",
    }
    result = apply_expansion_delta(
        shot["prompt"], [],
        ["hand_resting_on_hip", "arm_under_head", "calm_expression"],
        shot, None)
    assert "hand_resting_on_hip" in result
    assert "arm_under_head" in result
    assert "calm_expression" in result
    assert "red_eyes" in result
    assert "red_hair" in result
    assert "arms_up" not in result
    assert "grabbing_own_breast" not in result
    assert "open_mouth" not in result
    assert "half-closed_eyes" not in result
    assert "looking_at_viewer" not in result
    assert "bedroom" in result


def test_expansion_replaces_penetration_depth_and_pullout():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, deep penetration, penis in pussy, cum, bedroom",
    }
    shallow = apply_expansion_delta(
        shot["prompt"], [], ["shallow penetration"], shot, None)
    assert "shallow penetration" in shallow
    assert "deep penetration" not in shallow
    assert "penis in pussy" not in shallow
    assert "cum" in shallow

    pulled = apply_expansion_delta(
        shallow, [], ["penis pullout", "after sex"], shot, None)
    assert "penis pullout" in pulled
    assert "after sex" in pulled
    assert "shallow penetration" not in pulled
    assert "penis in pussy" not in pulled


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


def test_sanitize_expansion_allows_nudity_and_sex_already_in_next_shot():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, cowgirl_position"}
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, 1boy, completely nude, penetration, thrusting",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, completely nude, penetration, thrusting", shot, next_shot)
    assert "completely nude" in prompt
    assert "penetration" in prompt
    assert "thrusting" in prompt


def test_sanitize_expansion_blocks_actions_missing_from_next_shot():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, lying"}
    next_shot = {"id": "02", "name": "b", "prompt": "1girl, 1boy, lying, smile"}
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, lying, deep penetration, cum, penis pullout, "
        "completely nude, tears", shot, next_shot)
    assert "deep penetration" not in prompt
    assert "cum" not in prompt
    assert "penis pullout" not in prompt
    assert "completely nude" not in prompt
    assert "smile" not in prompt


def test_sanitize_expansion_blocks_non_sex_future_states():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, warrior, standing, sword_sheathed",
    }
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, warrior, standing, sword_sheathed, smile",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, warrior, standing, sword_sheathed, blood_on_face, "
        "holding_gun, broken_window, hand_on_cheek",
        shot, next_shot)
    assert "blood_on_face" not in prompt
    assert "holding_gun" not in prompt
    assert "broken_window" not in prompt
    assert "sword_sheathed" in prompt
    assert "hand_on_cheek" in prompt


def test_sanitize_expansion_allows_future_states_present_in_next_shot():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, warrior, standing, sword_sheathed",
    }
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, warrior, standing, sword_sheathed, "
                  "blood_on_face, broken_window",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, warrior, standing, blood_on_face, broken_window, "
        "sword_sheathed", shot, next_shot)
    assert "blood_on_face" in prompt
    assert "broken_window" in prompt
    assert "sword_sheathed" in prompt


def test_sanitize_expansion_keeps_solo_scene_to_one_person():
    shot = {"id": "01", "name": "a", "prompt": "1girl, solo, lying, on table"}
    prompt = sanitize_expansion_prompt(
        "1girl, solo, lying, on table, legs wrapped around waist, "
        "legs wrapped around thighs, arms around neck, kissing, 1boy, "
        "hand_on_table, pussy",
        shot, None)
    assert "legs wrapped around waist" not in prompt
    assert "legs wrapped around thighs" not in prompt
    assert "arms around neck" not in prompt
    assert "kissing" not in prompt
    assert "1boy" not in prompt
    assert "hand_on_table" in prompt
    assert "pussy" in prompt


def test_sanitize_expansion_allows_partner_actions_for_double_shot():
    shot = {
        "id": "01", "name": "a",
        "prompt": "1girl, 1boy, lying, legs wrapped around waist, kissing",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, lying, legs wrapped around waist, kissing",
        shot, None)
    assert "legs wrapped around waist" in prompt
    assert "kissing" in prompt


def test_sanitize_expansion_does_not_exceed_next_shot_depth_or_pullout():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, lying"}
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, 1boy, lying, shallow penetration",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, lying, shallow penetration, deep penetration, "
        "penis pullout", shot, next_shot)
    assert "shallow penetration" in prompt
    assert "deep penetration" not in prompt
    assert "penis pullout" not in prompt


def test_sanitize_expansion_allows_pullout_when_next_shot_has_after_sex():
    shot = {"id": "01", "name": "a", "prompt": "1girl, 1boy, lying"}
    next_shot = {
        "id": "02", "name": "b",
        "prompt": "1girl, 1boy, lying, after sex, cum on body",
    }
    prompt = sanitize_expansion_prompt(
        "1girl, 1boy, lying, penis pullout, cum on body", shot, next_shot)
    assert "penis pullout" in prompt
    assert "cum on body" in prompt


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


def test_sequence_mode_can_reset_final_state_on_first_step():
    class FakeClient:
        def chat_json(self, model, messages, **kwargs):
            return {"expansions": [{
                "id": "01",
                "steps": [
                    {"remove": ["cum", "deep penetration"],
                     "add": ["cum on body", "shallow penetration",
                             "calm expression"]},
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
    assert "cum" not in prompts[0]
    assert "cum on body" not in prompts[0]
    assert "deep penetration" not in prompts[0]
    assert "shallow penetration" not in prompts[0]
    assert "moderate penetration" in prompts[1]


def test_sequence_does_not_reset_state_already_present_in_previous_shot():
    class FakeClient:
        def chat_json(self, model, messages, **kwargs):
            return {"expansions": [
                {"id": "01", "steps": [
                    {"remove": ["cum", "deep penetration"],
                     "add": ["shallow penetration", "calm expression"]},
                ]},
                {"id": "02", "steps": [
                    {"remove": ["cum", "deep penetration"],
                     "add": ["shallow penetration", "calm expression"]},
                ]},
            ]}

    shots = [
        {"id": "01", "prompt": "1girl, cum, deep penetration, bedroom"},
        {"id": "02", "prompt": "1girl, cum, deep penetration, bedroom"},
    ]
    result = generate_expansions(
        FakeClient(), "model", shots, 1, sequence=True, chunk=6)
    assert result["01"][0].count("cum") == 0
    assert "cum" in result["02"][0]
    assert "deep penetration" in result["02"][0]
    assert "shallow penetration" not in result["02"][0]


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
