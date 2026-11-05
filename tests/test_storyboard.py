import json

import pytest

from comfyui_generator.core.storyboard import (
    ACT_PLAN_SYSTEM,
    OUTLINE_SYSTEM,
    STORY_SYSTEM,
    _clothing_key,
    _half_off_tags,
    _script_has_half_off,
    _script_resets_to_full,
    _global_story_state,
    _action_audit_messages,
    _intimacy_regressions,
    _intimacy_stage,
    _pacing_audit_messages,
    _phase_backtracks,
    _story_progress_ledger,
    enforce_final_wardrobe,
    enforce_weighted_core,
    enforce_premise_masturbation_layers,
    ensure_clothing_layers,
    ensure_final_afterglow,
    ensure_layered_breast_contact,
    ensure_layered_masturbation,
    ensure_outerwear_occlusion,
    wardrobe_weight_policy,
    stabilize_clothing_sequence,
    repair_clothing_sequence,
    repair_clothing_sequence_ai,
    repair_story_continuity_ai,
    _with_outline_progress,
    SCRIPT_SYSTEM,
    TAG_SYSTEM,
    apply_character_state,
    apply_focus_weights,
    apply_story_state,
    build_outline_messages,
    character_prompt_groups,
    build_script_messages,
    build_tag_messages,
    character_states_for_beats,
    clothing_states_for_beats,
    extract_premise_beats,
    filter_locked_appearance,
    normalize_acts,
    normalize_cast,
    normalize_shot_casts,
    renumber_shots,
    sync_clothing_state_to_prompt,
    repair_missing_actions_ai,
    repair_story_pacing_ai,
    repetitive_shot_groups,
    normalize_character_profiles,
    normalize_outline,
    parse_character_profiles,
    update_clothing_details,
    present_character_profiles,
    normalize_scripts,
    normalize_tagged,
    premise_from_json,
    scene_states_for_beats,
    shots_from_json,
    slugify,
    strip_male_profile_details,
    StoryboardOptions,
    _finalize_shot_prompt,
)


def test_tagged_shots_use_the_generated_script_as_outline():
    script = "身份外貌：仪玄。服装：黑色西装。场景：卧室。"
    scripts = normalize_scripts({"shots": [{
        "id": "01", "name": "a", "script": script,
    }]}, 1, "fallback")
    tagged = normalize_tagged({"shots": [
        {"id": "01", "prompt": "1girl, standing"}]}, scripts)
    assert tagged[0]["outline"] == script


def test_normalize_scripts_falls_back_to_structured_fields():
    scripts = normalize_scripts({"shots": [{
        "id": "11",
        "cast": "1girl 1boy",
        "beat": "男主停在门口",
        "clothing": "军装半脱",
        "pose": "女主拉裙摆遮腿",
        "nsfw": "私处半露",
    }]}, 1, "fallback")
    assert scripts[0]["id"] == "01"
    assert "男主停在门口" in scripts[0]["script"]
    assert "军装半脱" in scripts[0]["script"]


def test_tag_prompt_requires_fluid_interactions():
    assert "pussy juice" in TAG_SYSTEM
    assert "cum in mouth" in TAG_SYSTEM
    assert "cum swallowing" in TAG_SYSTEM
    assert "cum on body" in TAG_SYSTEM
    assert "creampie" in TAG_SYSTEM
    assert "squirt" in TAG_SYSTEM
    assert "男方射精方式" in SCRIPT_SYSTEM
    assert "男方射精方式" in STORY_SYSTEM


def test_prompts_do_not_depend_on_reference_tags():
    for prompt in (OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "参考标签" not in prompt
    assert "最多 100" in TAG_SYSTEM
    assert "禁止 camera" in TAG_SYSTEM
    assert "不生成质量" in TAG_SYSTEM
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "撕破连裤袜" in prompt


def test_prompt_templates_share_priority_and_avoid_foreign_examples():
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM,
                   TAG_SYSTEM, ACT_PLAN_SYSTEM):
        assert "统一优先级" in prompt
    assert "yixuan" not in TAG_SYSTEM
    assert "black blazer" not in TAG_SYSTEM


def test_prompt_templates_require_pose_diversity():
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM,
                   TAG_SYSTEM, ACT_PLAN_SYSTEM):
        assert "5-7 种不同姿势" in prompt
        assert "展示女主正面" in prompt


def test_story_templates_require_requested_act_coverage():
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM,
                   ACT_PLAN_SYSTEM):
        assert "男主对女主口交" in prompt
        assert "吞精" in prompt
        assert "不能循环前戏" in prompt
        assert "不得再加入陌生男人" in prompt
        assert "第一次射精后不得再次完整重复" in prompt
        assert "连续事后、整理、走路不得无新信息地堆叠" in prompt
        assert "扩展当前动作的微节拍" in prompt
    assert "每幕 title 必须概括" in ACT_PLAN_SYSTEM


def test_scene_instructions_allow_natural_detail_expansion():
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "自然扩展" in prompt
        assert "不要每镜随机换一套" in prompt
    messages = build_script_messages("story", 1, "", [], 1, ["one"])
    assert "环境细节" in messages[1]["content"]


def test_script_messages_include_progress_and_single_beat_rule():
    messages = build_script_messages(
        "story", 1, "", [], 1, ["one"],
        story_state="剧情进度账本：当前阶段=插入")
    assert "剧情进度账本" in messages[1]["content"]
    system = messages[0]["content"]
    assert "每镜只能有一个主行为节拍" in system
    assert "插入后不得无过渡切回自慰" in system


def test_strip_appearance_instructions_only_when_character_lora_is_active():
    outline = build_outline_messages("story", 2, "", [], 2, 1, strip_appearance=True)
    script = build_script_messages("story", 2, "", [], 2, ["one", "two"],
                                   strip_appearance=True)
    tags = build_tag_messages([{"id": "01", "name": "a", "script": "x"}],
                              strip_appearance=True)
    for messages in (outline, script):
        assert "不要生成或补充角色外貌和身体特征" in messages[1]["content"]
    assert "不要输出角色外貌和身体特征" in tags[1]["content"]
    plain = build_outline_messages("story", 2, "", [], 2, 1)
    assert "不要生成或补充角色外貌和身体特征" not in plain[1]["content"]






def test_erotic_clothing_categories_are_recognized():
    assert _clothing_key("black fishnet tights") == "fishnet"
    assert _clothing_key("lace babydoll") == "lingerie"
    assert _clothing_key("black stiletto heels") == "heels"
    assert _clothing_key("garter belt") == "garter"
    assert _clothing_key("puritan collar") == "collar"
    assert _clothing_key("black catsuit") == "bodysuit"
    assert _clothing_key("black lace panties") == "panties"
    assert _clothing_key("sheer lace underwear") == "underwear"
    assert _clothing_key("white sneakers") == "shoes"
    assert _clothing_key("black boxer briefs") == "underwear"
    assert _clothing_key("grey sweatpants") == "pants"
    assert _clothing_key("black waistcoat") == "vest"
    assert _clothing_key("silver bracelet") == ""
    assert _clothing_key("black bracers") == ""
    assert _clothing_key("black dress shoes") == "shoes"
    assert _clothing_key("black suit pants") == "pants"
    assert _clothing_key("black lace gloves") == "gloves"
    assert _clothing_key("黑裙") == "dress"
    assert _clothing_key("长靴") == "boots"
    assert _clothing_key("collarbone") == ""
    assert _clothing_key("gym") == ""
    assert _clothing_key("school") == ""
    assert _clothing_key("sports") == ""
    assert _clothing_key("wedding") == ""
    assert _clothing_key("shirtless") == ""


def test_extended_scene_patterns():
    states = scene_states_for_beats(["在更衣室", "走到阳台", "在书房"])
    assert states[0][0] == "dressing room"
    assert states[1][0] == "balcony"
    assert states[2][0] == "study"


def test_removed_garment_damage_tag_does_not_survive_nudity():
    result = apply_story_state(
        "torn pantyhose, panties aside, black panties",
        {"black panties"})
    tags = [tag.strip() for tag in result.split(",")]
    assert "torn pantyhose" not in tags
    assert "panties aside" in tags
    assert "black panties" in tags


def test_torn_clothing_state_is_not_erased_by_clothing_machine():
    result = apply_story_state(
        "torn pantyhose, ripped panties, panties aside, black blazer",
        {"black pantyhose", "black panties"},
    )
    assert "torn pantyhose" in result
    assert "ripped panties" in result
    assert "panties aside" in result
    assert "black pantyhose" in result
    assert "black panties" in result


def test_half_off_script_words_cover_chinese_variants():
    for script in (
            "连裤袜半褪在大腿上，内裤歪到一边",
            "黑色丝袜堆在小腿和脚踝",
            "内裤挂在一条腿上",
            "她把连裤袜拉上来"):
        assert _script_has_half_off(script)


def test_half_off_tags_support_ankles_and_calves():
    result = _half_off_tags([
        "(black pantyhose:1.2)",
        "(black pantyhose around ankles:1.2)",
    ])
    assert "(black pantyhose:1.2)" not in result
    assert "(black pantyhose around ankles:1.2)" in result
    assert "pantyhose around ankles" in result
    assert "lower legs covered" in result


def test_finalize_keeps_carried_half_off_without_current_half_off_script():
    shot = {
        "prompt": "1girl, (black pantyhose:1.2), (black pantyhose around ankles:1.2)",
        "script": "她继续看着你，没有说话。",
        "clothing_details": {"char_01": "pantyhose half-off"},
    }
    _finalize_shot_prompt(shot, "(black pantyhose:1.2)")
    assert "(black pantyhose:1.2)" not in shot["prompt"]
    assert "around ankles" in shot["prompt"]


def test_finalize_clears_half_off_when_script_explicitly_redresses():
    shot = {
        "prompt": "1girl, (black pantyhose:1.2), (black pantyhose around ankles:1.2)",
        "script": "她整理好衣服，连裤袜仍完整穿着。",
        "clothing_details": {"char_01": "pantyhose half-off"},
    }
    _finalize_shot_prompt(shot, "(black pantyhose:1.2)")
    assert _script_resets_to_full("连裤袜仍完整穿着")
    assert "around ankles" not in shot["prompt"]


def test_finalize_keeps_carried_damage_without_current_damage_script():
    shot = {
        "prompt": "1girl, black pantyhose, torn pantyhose",
        "script": "她靠在门边休息，呼吸逐渐平稳。",
        "clothing_details": {"char_01": "torn pantyhose"},
    }
    _finalize_shot_prompt(shot, "black pantyhose")
    assert "torn pantyhose" in shot["prompt"]


def test_sync_clothing_state_keeps_torn_and_restores_base():
    premise = "角色：女主\n初始服装：black pantyhose, black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    worn = "black pantyhose, black lace panties, black bra"
    shots = [{
        "prompt": ("1girl, black bra pulled down, breasts out, "
                   "black lace panties, black pantyhose"),
        "character_states": {key: worn},
        "clothing_details": {key: "torn pantyhose"},
    }]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "torn pantyhose" in shots[0]["prompt"]
    assert "black bra" in shots[0]["prompt"]
    assert "black bra pulled down" not in shots[0]["prompt"]


def test_ai_clothing_state_updates_generic_sync():
    premise = "角色：女主\n初始服装：black pantyhose, black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key

    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [{
                "id": "01", "valid": False,
                "prompt": "1girl, black bra, black pantyhose, torn pantyhose",
                "clothing_state": "torn pantyhose",
            }]}

    shots = [{
        "id": "01",
        "prompt": "1girl, black bra pulled down, breasts out",
        "character_states": {key: "black bra, black pantyhose"},
        "clothing_details": {key: ""},
    }]
    repair_clothing_sequence_ai(Fake(), "m", shots, profiles)
    json.dumps(shots[0]["clothing_details"])
    sync_clothing_state_to_prompt(shots, profiles)
    assert "black bra pulled down" not in shots[0]["prompt"]
    assert "breasts out" not in shots[0]["prompt"]
    assert "black bra" in shots[0]["prompt"]
    assert "torn pantyhose" in shots[0]["prompt"]


def test_ai_off_body_state_removes_unkeyed_cape():
    premise = "角色：少女\n初始服装：military uniform, red cape, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key

    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [{
                "id": "01", "valid": True,
                "clothing_state": "cape removed, military uniform removed",
            }]}

    shots = [{
        "id": "01",
        "prompt": ("1girl, red cape, military uniform, cape on seat, "
                   "black bra"),
        "character_states": {key: "red cape, military uniform, black bra"},
        "clothing_details": {key: ""},
    }]
    repair_clothing_sequence_ai(Fake(), "m", shots, profiles)
    assert "cape removed" in shots[0]["clothing_details"][key]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "red cape" not in shots[0]["prompt"]
    assert "cape on seat" not in shots[0]["prompt"]
    assert "cape removed" not in shots[0]["prompt"]
    assert "uniform" not in shots[0]["prompt"]
    assert "black bra" in shots[0]["prompt"]
    assert "red cape" not in shots[0]["character_states"][key]
    assert "uniform" not in shots[0]["character_states"][key]


def test_male_off_body_state_does_not_strip_female_clothing():
    premise = "角色：少女\n初始服装：white gloves, military uniform"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [{
        "id": "01",
        "prompt": ("1girl, white gloves, military uniform, "
                   "white gloves slipped off male wrist"),
        "character_states": {key: "white gloves, military uniform"},
        "clothing_details": {key: ""},
    }]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "white gloves" in shots[0]["prompt"]
    assert "military uniform" in shots[0]["prompt"]


def test_removed_cape_stays_removed_for_later_shots():
    premise = "角色：少女\n初始服装：military uniform, red cape, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, red cape, military uniform, black bra",
            "character_states": {key: "red cape, military uniform, black bra"},
            "clothing_details": {key: ""},
        },
        {
            "id": "02",
            "prompt": "1girl, red cape, cape removed, black bra",
            "character_states": {key: "red cape, military uniform, black bra"},
            "clothing_details": {key: ""},
        },
        {
            "id": "03",
            "prompt": "1girl, red cape, military uniform, black bra",
            "character_states": {key: "red cape, military uniform, black bra"},
            "clothing_details": {key: ""},
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "red cape" not in shots[1]["prompt"]
    assert "red cape" not in shots[2]["prompt"]
    assert "red cape" not in shots[2]["character_states"][key]
    assert "military uniform" in shots[2]["prompt"]


def test_ai_none_state_clears_stale_clothing_details():
    premise = "角色：女主\n初始服装：black pantyhose, black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key

    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [{
                "id": "01", "valid": True, "clothing_state": "none",
            }]}

    shots = [{
        "id": "01",
        "prompt": "1girl, black bra pulled down, breasts out",
        "character_states": {key: "black bra, black pantyhose"},
        "clothing_details": {key: "bra pull"},
    }]
    repair_clothing_sequence_ai(Fake(), "m", shots, profiles)
    sync_clothing_state_to_prompt(shots, profiles)
    assert "bra pull" not in shots[0]["prompt"]
    assert "breasts out" not in shots[0]["prompt"]
    assert "black bra" in shots[0]["prompt"]


def test_sync_uses_displaced_state_as_single_source_for_base():
    premise = ("角色：少女\n初始服装：black pantyhose, black lace panties, "
               "black bra")
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [{
        "prompt": ("1girl, black pantyhose, torn pantyhose, "
                   "black lace panties, panties around one thigh, black bra"),
        "character_states": {key: "black pantyhose, black lace panties, black bra"},
        "clothing_details": {key: "torn pantyhose, panties around one thigh"},
    }]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "black pantyhose" not in shots[0]["prompt"]
    assert "torn pantyhose" in shots[0]["prompt"]
    assert "black lace panties" not in shots[0]["prompt"]
    assert "panties around one thigh" in shots[0]["prompt"]
    assert "black bra" in shots[0]["prompt"]
    assert "black pantyhose" not in shots[0]["character_states"][key]
    assert "black lace panties" not in shots[0]["character_states"][key]
    assert "black bra" in shots[0]["character_states"][key]


def test_sync_restores_intimate_half_off_only_with_explicit_cue():
    premise = ("角色：少女\n初始服装：black pantyhose, black lace panties, "
               "black bra")
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": ("1girl, black pantyhose, pantyhose pulled aside, "
                       "black lace panties, panties aside, black bra"),
            "character_states": {key: "black pantyhose, black lace panties, black bra"},
            "clothing_details": {key: "pantyhose pulled aside, panties aside"},
            "script": "她把内裤拨到一侧继续自慰",
        },
        {
            "id": "02",
            "prompt": ("1girl, black pantyhose, pantyhose pulled aside, "
                       "black lace panties, black bra"),
            "character_states": {key: "black pantyhose, black lace panties, black bra"},
            "clothing_details": {key: "pantyhose pulled aside, panties aside"},
            "script": "她把内裤拉回整理好",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "panties aside" not in shots[1]["prompt"]
    assert "black lace panties" in shots[1]["prompt"]
    assert "pantyhose pulled aside" in shots[1]["prompt"]
    assert "black pantyhose" in shots[1]["prompt"]


def test_sync_restores_removed_intimate_with_explicit_cue():
    premise = "角色：少女\n初始服装：black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, black lace panties removed, panties on seat, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: "panties removed, panties on seat"},
            "script": "她把内裤脱下放在座椅上",
        },
        {
            "id": "02",
            "prompt": "1girl, black lace panties, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: "panties removed, panties on seat"},
            "script": "她把内裤穿回",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "black lace panties" in shots[1]["prompt"]
    assert "panties removed" not in shots[1]["prompt"]
    assert "panties on seat" not in shots[1]["prompt"]


def test_sync_does_not_restore_negated_cue():
    premise = "角色：少女\n初始服装：black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, black lace panties, panties aside, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: "panties aside"},
            "script": "她把内裤拨到一侧",
        },
        {
            "id": "02",
            "prompt": "1girl, black lace panties, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: "panties aside"},
            "script": "内裤仍被拨开未整理",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "panties aside" in shots[1]["prompt"]
    assert "black lace panties" in shots[1]["prompt"]


def test_wardrobe_weight_policy_keeps_weighted_and_removes_plain():
    premise = (
        "角色：少女\n"
        "初始服装：uniform, red cape, (black bra:1.2), "
        "black pantyhose(1.2), black platform heels")
    policy = wardrobe_weight_policy(premise)
    assert "带权重服装是保留核心" in policy
    assert "(black bra:1.2)" in policy
    assert "uniform" in policy
    assert "最后一镜前全部脱完" in policy


def test_wardrobe_weight_policy_ignores_unweighted_wardrobe():
    assert wardrobe_weight_policy("初始服装：uniform, belt, shoes") == ""


def test_sync_damage_supersedes_half_off_on_same_key():
    premise = ("角色：少女\n初始服装：black pantyhose, black lace panties, "
               "black bra")
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [{
        "id": "01",
        "prompt": ("1girl, black pantyhose, torn pantyhose, "
                   "pantyhose pulled aside, black lace panties, "
                   "panties aside, black bra"),
        "character_states": {key: "black pantyhose, black lace panties, black bra"},
        "clothing_details": {
            key: "torn pantyhose, pantyhose pulled aside, panties aside"},
        "script": "裤袜被撕破，内裤拨到一侧，从破洞继续自慰",
    }]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "torn pantyhose" in shots[0]["prompt"]
    assert "pantyhose pulled aside" not in shots[0]["prompt"]
    assert "panties aside" in shots[0]["prompt"]
    assert "pantyhose pulled aside" not in shots[0]["clothing_details"][key]


def test_sync_does_not_restore_regular_clothing():
    premise = "角色：少女\n初始服装：military uniform, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, military uniform removed, clothes on floor",
            "character_states": {key: "military uniform, black bra"},
            "clothing_details": {key: "military uniform removed"},
            "script": "她脱下军装",
        },
        {
            "id": "02",
            "prompt": "1girl, military uniform, black bra",
            "character_states": {key: "military uniform, black bra"},
            "clothing_details": {key: "military uniform removed"},
            "script": "她拉回军装",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "military uniform" not in shots[1]["prompt"]
    assert "black bra" in shots[1]["prompt"]


def test_sync_does_not_restore_damaged_clothing():
    premise = "角色：少女\n初始服装：black pantyhose, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, black pantyhose, torn pantyhose, black bra",
            "character_states": {key: "black pantyhose, black bra"},
            "clothing_details": {key: "torn pantyhose"},
            "script": "连裤袜被撕破",
        },
        {
            "id": "02",
            "prompt": "1girl, black pantyhose, black bra",
            "character_states": {key: "black pantyhose, black bra"},
            "clothing_details": {key: "torn pantyhose"},
            "script": "她把连裤袜拉回穿好",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "black pantyhose" not in shots[1]["prompt"]
    assert "torn pantyhose" in shots[1]["prompt"]


def test_sync_does_not_jump_from_half_off_to_worn_without_cue():
    premise = "角色：少女\n初始服装：black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [
        {
            "id": "01",
            "prompt": "1girl, black lace panties, panties around ankles, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: "panties around ankles"},
            "script": "内裤褪到脚踝",
        },
        {
            "id": "02",
            "prompt": "1girl, black lace panties, black bra",
            "character_states": {key: "black lace panties, black bra"},
            "clothing_details": {key: ""},
            "script": "她继续自慰",
        },
    ]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "black lace panties" not in shots[1]["prompt"]
    assert "panties around ankles" in shots[1]["prompt"]


def test_sync_clothing_state_removes_unrequested_and_male_tags():
    premise = "角色：女主\n初始服装：black pantyhose, black lace panties, black bra"
    profiles = parse_character_profiles(premise)
    key = profiles[0].key
    shots = [{
        "prompt": ("1girl, 1boy, black skirt, hand on male collar, "
                   "male face partially visible, male face visible, "
                   "male face out of frame, black pantyhose"),
        "character_states": {key: "black pantyhose"},
        "clothing_details": {key: ""},
    }]
    sync_clothing_state_to_prompt(shots, profiles)
    assert "skirt" not in shots[0]["prompt"]
    assert "collar" not in shots[0]["prompt"]
    assert "male face partially visible" not in shots[0]["prompt"]
    assert "male face visible" not in shots[0]["prompt"]
    assert "male face out of frame" in shots[0]["prompt"]


def test_clothing_details_use_current_state_and_dedupe_synonyms():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]
    states = {profile.key: {"black pantyhose"}}
    details = update_clothing_details(
        [profile], states, [profile],
        "pantyhose around ankles, half-off pantyhose",
        {profile.key: {"half-off pantyhose", "pantyhose pulled down"}},
        script="连裤袜堆在脚踝",
    )
    assert details[profile.key] == {
        "pantyhose around ankles", "half-off pantyhose"}


def test_clothing_sequence_keeps_damage_until_repaired():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]
    shots = [
        {"id": "01", "prompt": "1girl, (black pantyhose:1.2), torn pantyhose",
         "script": "她把连裤袜撕破"},
        {"id": "02", "prompt": "1girl, (black pantyhose:1.2)",
         "script": "她继续看着你"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "torn black pantyhose" in shots[1]["prompt"]
    assert "intact" not in shots[1]["prompt"]


def test_clothing_sequence_removes_invented_clothing_without_change():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]
    shots = [{"id": "01", "prompt": "1girl, white shirt, black pantyhose",
              "script": "她站着"}]
    stabilize_clothing_sequence(shots, [profile])
    assert "white shirt" not in shots[0]["prompt"]
    assert "black pantyhose" in shots[0]["prompt"]


def test_clothing_sequence_allows_and_carries_explicit_outfit_change():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]
    shots = [
        {"id": "01", "prompt": "1girl, white shirt, black pantyhose",
         "script": "她换上新衬衫"},
        {"id": "02", "prompt": "1girl, white shirt, black pantyhose",
         "script": "她继续看着你"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "white shirt" in shots[0]["prompt"]
    assert "white shirt" in shots[1]["prompt"]


def test_clothing_sequence_keeps_panties_present_when_ai_omits_them():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]
    shots = [
        {"id": "01", "prompt": "1girl, panties aside", "script": "她把内裤拨到一边"},
        {"id": "02", "prompt": "1girl, black pantyhose", "script": "她继续"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "panties aside" in shots[1]["prompt"]


def test_clothing_sequence_does_not_revert_aside_state_without_reset():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]
    shots = [
        {"id": "01", "prompt": "1girl, panties aside", "script": "她把内裤拨到一边"},
        {"id": "02", "prompt": "1girl, lace panties", "script": "她继续"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "panties aside" in shots[1]["prompt"]
    assert "lace panties" not in shots[1]["prompt"]


def test_clothing_sequence_allows_state_reset_when_script_says_so():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]
    shots = [
        {"id": "01", "prompt": "1girl, panties aside", "script": "她把内裤拨到一边"},
        {"id": "02", "prompt": "1girl, lace panties", "script": "她把内裤拉正"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "lace panties" in shots[1]["prompt"]
    assert "panties aside" not in shots[1]["prompt"]


def test_repair_clothing_sequence_asks_ai_to_fix_missing_panties():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]

    class Fake:
        def __init__(self):
            self.calls = []

        def chat_json(self, model, messages, **kwargs):
            self.calls.append(messages)
            return {"prompt": "1girl, black pantyhose, panties aside"}

    shots = [
        {"id": "01", "prompt": "1girl, panties aside", "script": "她继续"},
        {"id": "02", "prompt": "1girl, black pantyhose", "script": "她继续"},
    ]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls
    assert "上一镜仍穿着、这一镜漏掉了" in client.calls[0][1]["content"]
    assert "panties aside" in shots[1]["prompt"]


def test_repair_clothing_sequence_uses_prompt_state_not_user_wardrobe():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black dress")[0]

    class Fake:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"prompt": "should not be used"}

    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose", "script": "她站着"},
        {"id": "02", "prompt": "1girl, black pantyhose", "script": "她继续"},
    ]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls == 0


def test_repair_clothing_sequence_flags_prompt_contradictions():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]

    class Fake:
        def __init__(self):
            self.calls = []

        def chat_json(self, model, messages, **kwargs):
            self.calls.append(messages)
            return {"prompt": "1girl, black pantyhose"}

    shots = [{
        "id": "01",
        "prompt": "1girl, completely nude, black pantyhose, pantyhose removed",
        "script": "她站着",
    }]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls
    feedback = client.calls[0][1]["content"]
    assert "全裸" in feedback
    assert "同时写了脱下和在穿" in feedback


def test_repair_clothing_sequence_does_not_programmatically_append():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]

    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"prompt": "1girl, black pantyhose"}

    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose, lace panties",
         "script": "她站着"},
        {"id": "02", "prompt": "1girl, black pantyhose", "script": "她继续"},
    ]
    repair_clothing_sequence(Fake(), "model", shots, [profile])
    assert "lace panties" not in shots[1]["prompt"]


def test_clothing_key_does_not_treat_top_light_as_top():
    assert _clothing_key("strong top light") == ""
    assert _clothing_key("top-down lighting") == ""
    assert _clothing_key("tube top") == "top"


def test_repair_clothing_sequence_flags_unannounced_new_clothing():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]

    class Fake:
        def __init__(self):
            self.calls = []

        def chat_json(self, model, messages, **kwargs):
            self.calls.append(messages)
            return {"prompt": "1girl, black pantyhose"}

    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose", "script": "她站着"},
        {"id": "02", "prompt": "1girl, black pantyhose, white shirt",
         "script": "她继续"},
    ]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls
    assert "上一镜没有这件服装" in client.calls[0][1]["content"]
    assert "white shirt" not in shots[1]["prompt"]


def test_repair_topless_checks_all_upper_garments():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black bra")[0]

    class Fake:
        def __init__(self):
            self.calls = []

        def chat_json(self, model, messages, **kwargs):
            self.calls.append(messages)
            return {"prompt": "1girl, topless"}

    shots = [{"id": "01", "prompt": "1girl, topless, black shirt, black bra",
              "script": "她站着"}]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls
    assert "同时出现上身服装" in client.calls[0][1]["content"]


def test_repair_bottomless_checks_all_lower_garments():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black panties")[0]

    class Fake:
        def __init__(self):
            self.calls = []

        def chat_json(self, model, messages, **kwargs):
            self.calls.append(messages)
            return {"prompt": "1girl, bottomless"}

    shots = [{"id": "01", "prompt": "1girl, bottomless, black skirt, black panties",
              "script": "她站着"}]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls
    assert "同时出现下身服装" in client.calls[0][1]["content"]


def test_ai_clothing_validation_keeps_valid_prompts():
    class Fake:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"shots": [
                {"id": "01", "valid": True, "issues": [], "prompt": "p1"},
                {"id": "02", "valid": True, "issues": [], "prompt": "p2"},
            ]}

    shots = [{"id": "01", "prompt": "p1", "script": "s1"},
             {"id": "02", "prompt": "p2", "script": "s2"}]
    client = Fake()
    repair_clothing_sequence_ai(client, "m", shots, [])
    assert client.calls == 1
    assert [shot["prompt"] for shot in shots] == ["p1", "p2"]


def test_ai_clothing_validation_applies_rewrite_only_when_invalid():
    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [
                {"id": "01", "valid": True, "issues": [], "prompt": "p1"},
                {"id": "02", "valid": False,
                 "issues": ["上一镜的 skirt 漏了"],
                 "prompt": "p2 fixed"},
            ]}

    shots = [{"id": "01", "prompt": "p1", "script": "s1"},
             {"id": "02", "prompt": "p2", "script": "s2"}]
    repair_clothing_sequence_ai(Fake(), "m", shots, [])
    assert shots[0]["prompt"] == "p1"
    assert shots[1]["prompt"] == "p2 fixed"


def test_ai_clothing_validation_carries_state_between_chunks():
    class Fake:
        def __init__(self):
            self.messages = []

        def chat_json(self, model, messages, **kwargs):
            self.messages.append(messages[1]["content"])
            return {"shots": [
                {"id": "01", "valid": True,
                 "clothing_state": "panties aside, torn pantyhose"},
            ]}

    shots = [{"id": "01", "prompt": "p1", "script": "s1"},
             {"id": "02", "prompt": "p2", "script": "s2"}]
    client = Fake()
    repair_clothing_sequence_ai(client, "m", shots, [], chunk=1)
    assert shots[0]["clothing_state"] == "panties aside, torn pantyhose"
    assert "panties aside, torn pantyhose" in client.messages[1]


def test_ai_story_validation_keeps_valid_shots():
    class Fake:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"shots": [
                {"id": "01", "valid": True, "issues": [],
                 "script": "s1", "prompt": "p1"},
                {"id": "02", "valid": True, "issues": [],
                 "script": "s2", "prompt": "p2"},
            ]}

    shots = [{"id": "01", "script": "s1", "prompt": "p1"},
             {"id": "02", "script": "s2", "prompt": "p2"}]
    client = Fake()
    repair_story_continuity_ai(client, "m", shots)
    assert client.calls == 1
    assert [shot["script"] for shot in shots] == ["s1", "s2"]


def test_ai_story_validation_rewrites_repeated_shot():
    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [
                {"id": "01", "valid": True, "issues": [],
                 "script": "s1", "prompt": "p1"},
                {"id": "02", "valid": False,
                 "issues": ["重复 shot 01 的前戏"],
                 "script": "new beat", "prompt": "new prompt"},
            ]}

    shots = [{"id": "01", "script": "s1", "prompt": "p1"},
             {"id": "02", "script": "s2", "prompt": "p2"}]
    repair_story_continuity_ai(Fake(), "m", shots)
    assert shots[0]["script"] == "s1"
    assert shots[1]["script"] == "new beat"
    assert shots[1]["outline"] == "new beat"
    assert shots[1]["prompt"] == "new prompt"


def test_ai_story_validation_passes_history_to_later_chunks():
    class Fake:
        def __init__(self):
            self.messages = []

        def chat_json(self, model, messages, **kwargs):
            self.messages.append(messages[1]["content"])
            return {"shots": []}

    shots = [{"id": "%02d" % i, "script": "s%d" % i, "prompt": "p%d" % i}
             for i in range(1, 18)]
    client = Fake()
    repair_story_continuity_ai(client, "m", shots, chunk=8)
    assert len(client.messages) == 3
    assert '"id": "01"' in client.messages[1]


def test_ai_clothing_validation_chunks_long_sequences():
    class Fake:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"shots": []}

    shots = [{"id": "%02d" % i, "prompt": "p%d" % i, "script": ""}
             for i in range(1, 10)]
    client = Fake()
    repair_clothing_sequence_ai(client, "m", shots, [], chunk=8)
    assert client.calls == 2


def test_repair_clothing_sequence_does_not_call_ai_when_valid():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose, lace panties")[0]

    class Fake:
        def __init__(self):
            self.calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"prompt": "should not be used"}

    shots = [{"id": "01", "prompt": "1girl, black pantyhose, lace panties",
              "script": "她站着"}]
    client = Fake()
    repair_clothing_sequence(client, "model", shots, [profile])
    assert client.calls == 0
    assert "should not be used" not in shots[0]["prompt"]


def test_clothing_sequence_allows_explicit_repair():
    profile = parse_character_profiles(
        "角色：女主：black hair\n初始服装：女主：black pantyhose")[0]
    shots = [
        {"id": "01", "prompt": "1girl, torn pantyhose",
         "script": "她撕破连裤袜"},
        {"id": "02", "prompt": "1girl, black pantyhose",
         "script": "她换上新的连裤袜"},
    ]
    stabilize_clothing_sequence(shots, [profile])
    assert "torn" not in shots[1]["prompt"]


def test_empty_carried_clothing_does_not_reset_to_initial_outfit():
    premise = "初始服装：black blazer, black pantyhose, black platform heels"
    states = clothing_states_for_beats(
        premise, ["全裸", "继续全裸"], initial_worn=[])
    assert states == [set(), set()]


def test_upper_body_nudity_is_not_treated_as_full_nude():
    premise = "初始服装：black leotard, black pantyhose, black platform heels, hairclip"
    states = clothing_states_for_beats(premise, [
        "上半身完全裸露，下半身仍着 black pantyhose 与 black platform heels",
    ])
    assert "black pantyhose" in states[0]
    assert "black platform heels" in states[0]


def test_clothing_state_never_redresses_removed_items():
    premise = ("初始服装：black blazer, black pantyhose, black platform heels, hairclip")
    states = clothing_states_for_beats(premise, [
        "脱下高跟鞋和丝袜",
        "只穿着高跟鞋和丝袜",
        "全裸",
    ])
    assert states[0] == {"black blazer", "hairclip"}
    assert states[1] == states[0]
    assert states[2] == {"hairclip"}


def test_new_clothing_aliases_are_removed_on_full_nude():
    assert _clothing_key("back-seamed legwear") == "legwear"
    assert _clothing_key("black tight top") == "top"
    assert _clothing_key("black lace lingerie") == "lingerie"
    result = apply_story_state(
        "back-seamed legwear, black tight top, black lace lingerie, completely nude",
        {"hairclip"})
    tags = [tag.strip() for tag in result.split(",")]
    for item in ("back-seamed legwear", "black tight top", "black lace lingerie"):
        assert item not in tags
    assert "completely nude" in tags





def test_clothing_states_remove_and_restore_exact_items():
    premise = ("初始服装：black blazer, frilled black leotard, black pantyhose, "
               "black platform heels, hairclip")
    beats = [
        "01. 完整穿着 black blazer, leotard, black pantyhose, heels",
        "02. 脱下 black blazer",
        "03. 只剩 black pantyhose 与 black platform heels",
        "04. 全裸",
    ]
    states = clothing_states_for_beats(premise, beats)
    assert "black blazer" in states[0]
    assert "black blazer" not in states[1]
    assert states[2] == {"black pantyhose", "black platform heels", "hairclip"}
    assert "black pantyhose" not in states[3]
    assert "hairclip" in states[3]


def test_clothing_state_only_clause_does_not_readd_removed_item():
    premise = ("初始服装：black blazer, frilled black leotard, black pantyhose, "
               "black platform heels, hairclip")
    states = clothing_states_for_beats(premise, [
        "脱下 black blazer，脱去西装，只剩 leotard、黑丝、高跟鞋与饰品"])
    assert "black blazer" not in states[0]
    assert "frilled black leotard" in states[0]


def test_clothing_state_keeps_one_side_removal_until_full_nude():
    premise = ("初始服装：black pantyhose, black platform heels, hairclip")
    states = clothing_states_for_beats(premise, [
        "脱掉一侧高跟鞋与黑丝，另一脚还挂着丝袜",
        "全部脱去，全裸",
    ])
    assert "black pantyhose" in states[0]
    assert "black platform heels" in states[0]
    assert "black pantyhose" not in states[1]


def test_scene_states_keep_scene_until_plot_moves():
    assert scene_states_for_beats([
        "在房间里", "坐到沙发上", "继续坐在沙发上", "走到床边"])
    assert scene_states_for_beats(["在房间里"])[0] == ["room", "indoors"]
    assert scene_states_for_beats(["在房间里", "坐到沙发上"])[1][:2] == [
        "living room", "sofa"]


def test_apply_story_state_only_replaces_clothing_and_keeps_model_tags():
    result = apply_story_state(
        "black blazer, frilled black leotard, black pantyhose, black platform heels, "
        "white background, simple background, 3d, upper body covered, undressing, "
        "clothes pull, pussy, nipples, room, sofa",
        {"black pantyhose", "hairclip"},
    )
    tags = [tag.strip() for tag in result.split(",")]
    assert "black blazer" not in tags
    assert "frilled black leotard" not in tags
    assert "black platform heels" not in tags
    assert "black pantyhose" in tags
    assert "white background" in tags
    assert "3d" in tags
    assert "undressing" in tags
    assert "clothes pull" in tags
    assert "pussy" in tags
    assert "room" in tags
    assert "sofa" in tags


def test_apply_story_state_does_not_add_body_or_scene_tags():
    result = apply_story_state(
        "lying on side, legs spread, pussy, pussy juice",
        {"hairclip", "puritan collar"},
    )
    tags = [tag.strip() for tag in result.split(",")]
    assert "topless" not in tags
    assert "completely nude" not in tags
    assert "sitting" not in tags
    assert "bedroom" not in tags
    assert "pussy" in tags
    assert "lying on side" in tags


def test_generic_office_outfit_state():
    premise = ("初始服装：white office shirt, black pencil skirt, black stockings, "
               "black heels, glasses")
    beats = [
        "01. 坐在办公室，穿着白衬衫、黑裙、黑丝",
        "02. 脱下 white office shirt",
        "03. 掀起 black pencil skirt",
        "04. 全部脱去，全裸",
    ]
    states = clothing_states_for_beats(premise, beats)
    assert "white office shirt" in states[0]
    assert "white office shirt" not in states[1]
    assert "black pencil skirt" in states[2]
    assert "black stockings" in states[2]
    assert "glasses" in states[3]
    assert "black pencil skirt" not in states[3]


def test_generic_scene_office_bathroom_beach():
    states = scene_states_for_beats([
        "在办公室桌边", "走进浴室", "来到海边沙滩"])
    assert states[0][0] == "office"
    assert states[1][0] == "bathroom"
    assert states[2][0] == "beach"


def test_beach_scene_recognizes_sea_breeze_sand_and_rocks():
    states = scene_states_for_beats([
        "海风吹过沙地，她躲在礁石后",
        "开阔海面上有浪花",
    ])
    assert states[0][0] == "beach"
    assert states[1][0] == "beach"


def test_story_progress_ledger_uses_structured_phases():
    shots = [
        {"id": "01", "phase": "自慰", "outline": "她独自自慰"},
        {"id": "02", "phase": "初遇", "outline": "他出现"},
        {"id": "03", "phase": "插入", "outline": "他开始插入"},
    ]
    ledger = _story_progress_ledger(shots)
    assert "自慰" in ledger
    assert "初遇" in ledger
    assert "插入" in ledger
    assert "同一镜只能有一个主节拍" in ledger
    assert "不得无理由重复" in ledger


def test_story_progress_ledger_warns_on_long_repeated_phase():
    shots = [
        {"id": "%02d" % index, "phase": "同一阶段", "outline": "继续"}
        for index in range(1, 16)
    ]
    ledger = _story_progress_ledger(shots)
    assert "连续 15 镜" in ledger
    assert "必须推进到新事件" in ledger


def test_act_plan_uses_configurable_max_act_shots():
    from comfyui_generator.core.storyboard import build_premise_act_plan_messages
    messages = build_premise_act_plan_messages(
        "剧情", 50, max_act_shots=10)
    content = messages[1]["content"]
    assert "5 幕" in content
    assert "每幕最多 10 格" in content


def test_premise_act_plan_messages_reject_instruction_fragments():
    from comfyui_generator.core.storyboard import build_premise_act_plan_messages
    messages = build_premise_act_plan_messages("写一个 50 镜的故事", 50)
    content = messages[1]["content"]
    assert "只规划真正的剧情阶段" in content
    assert "写作要求" in content


def test_global_story_state_contains_progress_ledger():
    state = _global_story_state("story", [
        {"id": "01", "phase": "自慰", "outline": "她自慰"},
        {"id": "02", "phase": "初遇", "outline": "他出现"},
    ])
    assert "剧情进度账本" in state
    assert "当前阶段" in state


def test_outline_progress_appends_completed_stages():
    state = _with_outline_progress("全局状态表：剧情开始", [
        {"id": "01", "phase": "自慰", "outline": "她自慰"},
        {"id": "02", "phase": "初遇", "outline": "他出现"},
    ])
    assert "全局状态表：剧情开始" in state
    assert "已完成阶段" in state
    assert "自慰" in state


def test_generic_maid_outfit_and_hospital_scene():
    premise = "初始服装：maid outfit, white apron, black stockings, black heels"
    states = clothing_states_for_beats(premise, [
        "01. 在医院病房穿着女仆装",
        "02. 脱下 maid outfit",
    ])
    assert "maid outfit" in states[0]
    assert "maid outfit" not in states[1]
    assert scene_states_for_beats(["医院病房"])[0][0] == "hospital"


def test_extract_premise_beats_keeps_exact_numbered_lines():
    premise = "【第01–02格】\n01. 第一镜动作\n02. 第二镜动作\n说明行"
    assert extract_premise_beats(premise) == ["第一镜动作", "第二镜动作"]


def test_shots_from_json_accepts_export_object_and_keeps_outline():
    raw = {"version": 1, "shots": [
        {"id": "01", "name": "a", "prompt": "black hair, smile",
         "prompt_zh": "黑发，微笑", "outline": "第一镜大纲"},
        {"prompt": "nude"},
    ]}
    shots = shots_from_json(raw)
    assert shots[0]["outline"] == "第一镜大纲"
    assert shots[0]["prompt_zh"] == "黑发，微笑"
    assert shots[1]["id"] == "02"
    assert shots[1]["prompt"] == "nude"


def test_shots_from_json_accepts_array_and_rejects_empty():
    assert shots_from_json([{"prompt": "wide shot"}])[0]["prompt"] == "wide shot"
    with pytest.raises(ValueError):
        shots_from_json([])


def test_shots_from_json_accepts_storyboard_alias_and_field_aliases():
    raw = {"premise": "a story", "storyboard": [
        {"shot": 1, "caption": "wide shot", "中文": "全景", "大纲": "第一镜"}]}
    shot = shots_from_json(raw)[0]
    assert shot["id"] == "01"
    assert shot["prompt"] == "wide shot"
    assert shot["prompt_zh"] == "全景"
    assert shot["outline"] == "第一镜"
    assert premise_from_json(raw) == "a story"


def test_shots_from_json_accepts_mapping_and_string_list():
    mapping = {"02": {"caption": "close-up"}, "01": "wide shot"}
    shots = shots_from_json(mapping)
    assert [shot["id"] for shot in shots] == ["02", "01"]
    assert shots[0]["prompt"] == "close-up"
    assert shots[1]["prompt"] == "wide shot"
    assert shots_from_json(["wide shot", "close-up"])[1]["prompt"] == "close-up"


def test_shots_from_json_accepts_nested_data():
    raw = {"data": {"frames": [{"prompt": "nude, bed"}]}}
    assert shots_from_json(raw)[0]["prompt"] == "nude, bed"


def test_storyboard_options_defaults():
    opts = StoryboardOptions(model="test-model")
    assert opts.shots == 6
    assert opts.chunk == 12
    assert opts.setting == ""
    opts.log("noop")


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {"shots": [
            {"name": "next", "prompt": "medium shot, walking"},
            {"name": "last", "prompt": "close-up, smiling"},
        ]}


def test_generic_character_profiles_parse_female_and_male():
    premise = (
        "角色：女主：silver hair, red eyes；男主：black hair, golden eyes\n"
        "初始服装：女主：black dress, black panties；男主：white shirt, black trousers")
    profiles = parse_character_profiles(premise)
    assert [profile.name for profile in profiles] == ["女主", "男主"]
    assert [profile.gender for profile in profiles] == ["girl", "boy"]
    assert "silver hair" in profiles[0].appearance
    assert "black hair" in profiles[1].appearance
    assert profiles[0].initial_clothing == ["black dress", "black panties"]
    assert profiles[1].initial_clothing == ["white shirt", "black trousers"]

    combined = parse_character_profiles(
        "角色：女主：silver hair；男主：black hair\n"
        "初始服装：black dress, white shirt, black trousers")
    assert combined[0].initial_clothing == [
        "black dress", "white shirt", "black trousers"]
    assert combined[1].initial_clothing == []

    multiline = parse_character_profiles(
        "角色：\n女主：silver hair\n男主：black hair\n"
        "初始服装：\n女主：black dress\n男主：white shirt, black trousers\n"
        "大场景：卧室")
    assert [profile.name for profile in multiline] == ["女主", "男主"]
    assert multiline[0].initial_clothing == ["black dress"]
    assert multiline[1].initial_clothing == ["white shirt", "black trousers"]

    named = parse_character_profiles(
        "角色：\n角色A：silver hair\n角色B：black hair\n"
        "初始服装：\n角色A：black dress\n角色B：white shirt\n")
    assert [profile.name for profile in named] == ["角色A", "角色B"]

    chinese = parse_character_profiles(
        "角色：男主：黑发、金瞳\n初始服装：男主：白衬衫、黑西裤")
    assert chinese[0].appearance == ["黑发", "金瞳"]
    assert chinese[0].initial_clothing == ["白衬衫", "黑西裤"]
    chinese_states = character_states_for_beats(
        chinese, ["男主脱下白衬衫"])
    assert "白衬衫" not in chinese_states[0][chinese[0].key]
    assert "黑西裤" in chinese_states[0][chinese[0].key]

    dress = parse_character_profiles("初始服装：black dress")[0]
    dress_states = character_states_for_beats([dress], ["脱下黑裙"])
    assert "black dress" not in dress_states[0][dress.key]

    comma_split = parse_character_profiles(
        "角色：女主：silver hair, red eyes，男主：black hair\n"
        "初始服装：女主：black dress, black panties，男主：white shirt")
    assert [profile.name for profile in comma_split] == ["女主", "男主"]
    assert comma_split[0].initial_clothing == ["black dress", "black panties"]
    assert comma_split[1].initial_clothing == ["white shirt"]

    dot_split = parse_character_profiles(
        "角色：女主：silver hair、男主：black hair\n"
        "初始服装：女主：black dress、男主：white shirt")
    assert [profile.name for profile in dot_split] == ["女主", "男主"]
    assert dot_split[0].initial_clothing == ["black dress"]
    assert dot_split[1].initial_clothing == ["white shirt"]

    mixed = parse_character_profiles(
        "角色：silver hair\n初始服装：女主：black dress")
    assert len(mixed) == 1
    assert mixed[0].name == "女主"
    assert mixed[0].appearance == ["silver hair"]
    assert mixed[0].initial_clothing == ["black dress"]


def test_strip_appearance_keeps_new_male_but_not_lora_character_appearance():
    profiles = normalize_character_profiles([
        {"name": "yixuan", "gender": "girl",
         "appearance": "silver hair, red eyes", "initial_clothing": "black dress"},
        {"name": "男主", "gender": "boy",
         "appearance": "black hair, golden eyes",
         "initial_clothing": "white shirt, black trousers"},
    ], "角色：yixuan\n初始服装：black dress", strip_appearance=True)
    assert profiles[0].appearance == ["yixuan"]
    assert "silver hair" not in profiles[0].appearance
    assert "red eyes" not in profiles[0].appearance
    assert profiles[0].initial_clothing == ["black dress"]
    assert profiles[1].appearance == ["black hair", "golden eyes"]

    reordered = normalize_character_profiles([
        {"name": "男主", "gender": "boy",
         "appearance": "black hair", "initial_clothing": "white shirt"},
        {"name": "女主", "gender": "girl",
         "appearance": "silver hair", "initial_clothing": "black dress"},
    ], "角色：yixuan\n初始服装：black dress", strip_appearance=True)
    assert reordered[0].gender == "girl"
    assert reordered[0].initial_clothing == ["black dress"]
    assert reordered[1].gender == "boy"
    assert reordered[1].initial_clothing == ["white shirt"]

    merged = normalize_character_profiles([
        {"name": "女主", "gender": "girl",
         "appearance": "silver hair, red eyes",
         "initial_clothing": "black dress"},
    ], "角色：yixuan\n初始服装：black dress")
    assert "yixuan" in merged[0].appearance
    assert "silver hair" in merged[0].appearance
    assert "red eyes" in merged[0].appearance


def test_explicit_appearance_and_body_are_locked_against_model_changes():
    premise = (
        "角色：女主：old hair\n"
        "外貌身材：silver hair, red eyes, long hair, tall, large breasts\n"
        "初始服装：女主：black dress")
    profiles = parse_character_profiles(premise)
    assert profiles[0].appearance_locked is True
    assert profiles[0].appearance == [
        "silver hair", "red eyes", "long hair", "tall", "large breasts"]
    normalized = normalize_character_profiles([{
        "name": "女主", "gender": "girl",
        "appearance": "black hair, blue eyes, short hair",
        "initial_clothing": "black dress",
    }], premise)
    assert normalized[0].appearance == profiles[0].appearance
    assert filter_locked_appearance(
        ["white hair", "blue eyes", "smile"], ["silver hair", "red eyes"]
    ) == ["smile"]
    assert filter_locked_appearance(
        ["small breasts", "short", "dark skin", "smile"],
        ["large breasts", "tall", "pale skin"],
    ) == ["smile"]


def test_per_character_appearance_section():
    premise = (
        "角色：女主：yixuan；男主：male\n"
        "外貌身材：女主：silver hair, red eyes；男主：black hair, golden eyes, tall\n"
        "初始服装：女主：black dress；男主：white shirt")
    profiles = parse_character_profiles(premise)
    assert profiles[0].appearance == ["silver hair", "red eyes"]
    assert profiles[0].appearance_locked is True
    assert profiles[1].appearance == ["black hair", "golden eyes", "tall"]
    assert profiles[1].appearance_locked is True


def test_partial_clothing_state_is_carried_to_next_shot():
    profile = parse_character_profiles(
        "角色：男主：black hair\n初始服装：男主：white shirt, black trousers")[0]
    states = {profile.key: {"white shirt", "black trousers"}}
    details = update_clothing_details(
        [profile], states, [profile], "open_shirt, shirt_pull, smile", {})
    assert "open_shirt" in details[profile.key]
    assert "shirt_pull" in details[profile.key]
    prompt = apply_character_state(
        "1boy, standing", [profile], states, [profile], details)
    assert "open_shirt" in prompt
    assert "shirt_pull" in prompt


def test_shared_clothing_details_do_not_leak_to_male():
    profiles = parse_character_profiles(
        "角色：女主：red hair；男主：black hair\n"
        "初始服装：女主：white shirt；男主：white shirt")
    girl, boy = profiles
    states = {girl.key: {"white shirt"}, boy.key: {"white shirt"}}
    details = update_clothing_details(
        profiles, states, [girl, boy], "open_shirt, smile",
        {boy.key: {"open_shirt"}})
    assert "open_shirt" in details[girl.key]
    assert "open_shirt" not in details[boy.key]


def test_generic_character_states_keep_male_and_female_independent():
    premise = (
        "角色：女主：silver hair；男主：black hair\n"
        "初始服装：女主：black dress, black panties；男主：white shirt, black trousers")
    profiles = parse_character_profiles(premise)
    girl, boy = profiles
    states = character_states_for_beats(profiles, [
        "男主脱下白衬衫",
        "女主全裸",
        "男主也全裸",
        "男主重新穿上白衬衫",
    ])
    assert "white shirt" not in states[0][boy.key]
    assert "black trousers" in states[0][boy.key]
    assert "black dress" in states[0][girl.key]
    assert states[1][girl.key] == {"black dress", "black panties"}
    assert "black trousers" in states[1][boy.key]
    assert states[2][boy.key] == set()
    assert states[3][boy.key] == set()

    limited = character_states_for_beats(profiles, [
        "女主脱到只剩 black panties，男主还穿着 white shirt 和 black trousers"])
    assert limited[0][girl.key] == {"black panties"}
    assert limited[0][boy.key] == {"white shirt", "black trousers"}

    solo = character_states_for_beats(profiles, ["全裸"], presence=[[girl]])
    assert solo[0][girl.key] == set()
    assert solo[0][boy.key] == {"white shirt", "black trousers"}

    absent = character_states_for_beats(
        profiles, ["男主脱下 white shirt"], presence=[[girl]])
    assert absent[0][girl.key] == {"black dress", "black panties"}
    assert absent[0][boy.key] == {"white shirt", "black trousers"}

    absent_nude = character_states_for_beats(
        profiles, ["男主全裸"], presence=[[girl]])
    assert absent_nude[0][girl.key] == {"black dress", "black panties"}
    assert absent_nude[0][boy.key] == {"white shirt", "black trousers"}

    carried_nude = {girl.key: set(), boy.key: {"white shirt", "black trousers"}}
    no_redress = character_states_for_beats(
        profiles, ["女主只穿 black dress"], initial_states=carried_nude)
    assert no_redress[0][girl.key] == set()

    shared = parse_character_profiles(
        "角色：女主：silver hair；男主：black hair\n"
        "初始服装：女主：white shirt；男主：white shirt")
    shared_states = character_states_for_beats(
        shared, ["男主脱下 white shirt"], presence=[[shared[0]]])
    assert "white shirt" in shared_states[0][shared[0].key]

    english = parse_character_profiles(
        "角色：男主：black hair\n初始服装：男主：white shirt, black trousers")
    english_states = character_states_for_beats(
        english, ["takes off white shirt"])
    assert "white shirt" not in english_states[0][english[0].key]
    assert "black trousers" in english_states[0][english[0].key]
    english_only = character_states_for_beats(
        english, ["only wearing white shirt"])
    assert english_only[0][english[0].key] == {"white shirt"}


def test_generic_character_prompt_locks_appearance_and_present_clothing():
    premise = (
        "角色：女主：silver hair, red eyes；男主：black hair, golden eyes\n"
        "初始服装：女主：black dress；男主：white shirt, black trousers")
    profiles = parse_character_profiles(premise)
    girl, boy = profiles
    states = character_states_for_beats(profiles, ["两人站着", "男主全裸"])
    both = present_character_profiles(
        profiles, {"cast": "1girl 1boy", "outline": "两人站着"}, "两人站着")
    prompt = apply_character_state(
        "1girl, 1boy, standing, white shirt, black trousers, black dress",
        profiles, states[0], both)
    assert "silver hair" in prompt
    assert "black hair" in prompt
    assert "white shirt" in prompt
    assert "black dress" in prompt

    solo = present_character_profiles(
        profiles, {"cast": "1girl solo", "outline": "她坐下"}, "她坐下")
    prompt = apply_character_state(
        "1girl, solo, sitting, black dress", profiles, states[0], solo)
    assert "silver hair" in prompt
    assert "black hair" not in prompt
    assert "white shirt" not in prompt

    remembered = present_character_profiles(
        profiles, {"cast": "1girl solo", "outline": "她想起男主"}, "她想起男主")
    assert [profile.name for profile in remembered] == ["女主"]

    nudes = present_character_profiles(
        profiles, {"cast": "1girl 1boy", "outline": "男主全裸"}, "男主全裸")
    prompt = apply_character_state(
        "1girl, 1boy, nude, white shirt, black trousers", profiles,
        states[1], nudes)
    assert "black hair" in prompt
    assert "white shirt" not in prompt
    assert "black trousers" not in prompt

    prompt = apply_character_state(
        "1girl, 1boy, blonde hair, blue eyes, black hair, golden eyes",
        profiles, states[0], [boy])
    assert "blonde hair" not in prompt
    assert "blue eyes" not in prompt
    assert "black hair" in prompt
    assert "golden eyes" in prompt


def test_character_prompt_groups_isolate_gender_tags():
    profiles = parse_character_profiles(
        "角色：女主：red hair, long hair, red eyes；"
        "男主：short black hair, black eyes, average build\n"
        "初始服装：女主：white shirt, black pantyhose；男主：blue jeans")
    girl, boy = profiles
    states = {
        girl.key: {"white shirt", "black pantyhose"},
        boy.key: {"blue jeans"},
    }
    details = {girl.key: {"torn pantyhose", "bra pull"}, boy.key: set()}
    groups = character_prompt_groups(
        profiles, states, details,
        "1girl, 1boy, red hair, long hair, short black hair, white shirt, "
        "torn pantyhose, blue jeans, cowgirl, bedroom",
        [girl, boy])
    female = next(group for group in groups if group["gender"] == "girl")
    male = next(group for group in groups if group["gender"] == "boy")
    assert "red hair" in female["prompt"]
    assert "torn pantyhose" in female["prompt"]
    assert "white shirt" in female["prompt"]
    assert "short black hair" not in female["prompt"]
    assert "blue jeans" not in female["prompt"]
    assert "short black hair" in male["prompt"]
    assert "blue jeans" in male["prompt"]
    assert "red hair" not in male["prompt"]
    assert "long hair" not in male["prompt"]
    assert "white shirt" not in male["prompt"]
    assert "torn pantyhose" not in male["prompt"]


def test_character_prompt_groups_keep_shared_clothing_on_both():
    profiles = parse_character_profiles(
        "角色：女主：red hair；男主：black hair\n"
        "初始服装：女主：white shirt；男主：white shirt")
    girl, boy = profiles
    states = {girl.key: {"white shirt"}, boy.key: {"white shirt"}}
    groups = character_prompt_groups(
        profiles, states, {girl.key: set(), boy.key: set()},
        "1girl, 1boy, red hair, black hair, white shirt", [girl, boy])
    female = next(group for group in groups if group["gender"] == "girl")
    male = next(group for group in groups if group["gender"] == "boy")
    assert "white shirt" in female["prompt"]
    assert "white shirt" in male["prompt"]


def test_unknown_clothing_is_removed_on_nude_but_accessories_survive():
    profile = parse_character_profiles(
        "角色：男主：black hair\n初始服装：男主：nurse, flower brooch")[0]
    states = character_states_for_beats([profile], ["男主全裸"])
    assert "nurse" not in states[0][profile.key]
    assert "flower brooch" in states[0][profile.key]
    prompt = apply_character_state(
        "1boy, nurse, flower brooch, completely nude", [profile],
        states[0], [profile])
    assert "nurse" not in prompt
    assert "flower brooch" in prompt
    assert "completely nude" in prompt

    only = character_states_for_beats([profile], ["only wearing nurse"])
    assert "nurse" in only[0][profile.key]
    assert "flower brooch" in only[0][profile.key]

    removed_unknown = character_states_for_beats([profile], ["takes off nurse"])
    assert "nurse" not in removed_unknown[0][profile.key]
    assert "flower brooch" in removed_unknown[0][profile.key]

    bra = parse_character_profiles("初始服装：black bra")[0]
    bra_states = character_states_for_beats([bra], ["takes off bracers"])
    assert "black bra" in bra_states[0][bra.key]

    accessory = parse_character_profiles(
        "初始服装：earring, hairclip, black dress")[0]
    accessory_states = character_states_for_beats(
        [accessory], ["takes off earring", "全裸"])
    assert "earring" not in accessory_states[1][accessory.key]
    assert "hairclip" in accessory_states[1][accessory.key]


def test_appearance_lock_keeps_eye_expression_and_removes_wrong_color():
    profile = parse_character_profiles(
        "角色：少女\n外貌：purple eyes")[0]
    prompt = apply_character_state(
        "1girl, half-closed eyes, unfocused eyes, blue eyes, purple eyes",
        [profile], {profile.key: set()}, [profile])
    assert "half-closed eyes" in prompt
    assert "unfocused eyes" in prompt
    assert "blue eyes" not in prompt
    assert "purple eyes" in prompt


def test_appearance_lock_removes_conflicting_hair_style():
    profile = parse_character_profiles(
        "角色：男主：short black hair, golden eyes")[0]
    prompt = apply_character_state(
        "1boy, long hair, short hair, blue eyes", [profile],
        {profile.key: set()}, [profile])
    assert "long hair" not in prompt
    assert "short hair" in prompt
    assert "blue eyes" not in prompt
    assert "golden eyes" in prompt


def test_full_story_pipeline_uses_locked_male_character_state():
    from comfyui_generator.core import storyboard

    class MalePipelineFake:
        def chat_json(self, model, messages, **kwargs):
            schema = kwargs.get("schema") or {}
            required = schema.get("required") or []
            if "story" in required:
                return {
                    "story": "她回家，和男主做爱，两人最后全裸。",
                    "characters": [
                        {"name": "女主", "gender": "girl",
                         "appearance": "silver hair, red eyes",
                         "initial_clothing": "black dress"},
                        {"name": "男主", "gender": "boy",
                         "appearance": "black hair, golden eyes",
                         "initial_clothing": "white shirt, black trousers"},
                    ],
                }
            if required == ["acts"]:
                return {"acts": [{
                    "id": "01", "title": "第一幕", "summary": "她与男主",
                    "cast": "1girl 1boy", "clothing": "black dress; white shirt",
                    "scene": "bedroom", "nsfw": "undress",
                }]}
            if schema is storyboard.OUTLINE_SCHEMA:
                return {"shots": [
                    {"id": "01", "name": "a", "cast": "1girl 1boy",
                     "phase": "开场",
                     "outline": "两人站在卧室，女主穿着黑裙，男主穿着白衬衫和黑西裤"},
                    {"id": "02", "name": "b", "cast": "1girl 1boy",
                     "outline": "女主脱下黑裙，全裸，男主还穿着白衬衫和黑西裤"},
                    {"id": "03", "name": "c", "cast": "1girl 1boy",
                     "outline": "男主全裸，女主也全裸"},
                ]}
            if schema is storyboard.TAG_SCHEMA:
                return {"shots": [
                    {"id": "01", "prompt": "1girl, 1boy, standing"},
                    {"id": "02", "prompt": "1girl, 1boy, completely nude"},
                    {"id": "03", "prompt": "1girl, 1boy, completely nude"},
                ]}
            raise AssertionError(schema)

    shots = storyboard.generate_storyboard(
        MalePipelineFake(),
        "角色：女主：silver hair, red eyes；男主：black hair, golden eyes\n"
        "初始服装：女主：black dress；男主：white shirt, black trousers\n"
        "剧情：她回家，和男主做爱",
        storyboard.StoryboardOptions(model="test", shots=3, chunk=3,
                                     full_story=True))
    assert len(shots) == 3
    assert shots[0]["phase"] == "第一幕"
    for shot in shots:
        assert "silver hair" in shot["prompt"]
        assert "black hair" not in shot["prompt"]
    assert "white shirt" not in shots[0]["prompt"]
    assert "white shirt" not in shots[1]["prompt"]
    assert "white shirt" not in shots[2]["prompt"]
    assert "nude male" not in shots[0]["prompt"]
    assert "nude male" not in shots[1]["prompt"]
    assert "black dress" not in shots[1]["prompt"]
    assert "completely nude" in shots[1]["prompt"]
    assert "completely nude" in shots[2]["prompt"]


def test_full_story_pipeline_writes_story_acts_outlines_and_tags():
    from comfyui_generator.core import storyboard

    class PipelineFake:
        def __init__(self):
            self.kinds = []

        def chat_json(self, model, messages, **kwargs):
            schema = kwargs.get("schema") or {}
            required = schema.get("required") or []
            if "story" in required:
                self.kinds.append("story")
                return {"story": "她回家，慢慢脱衣，最后做爱。",
                        "characters": [{"name": "女主", "gender": "girl",
                                        "appearance": "",
                                        "initial_clothing":
                                            "black blazer, black pantyhose"}]}
            if required == ["acts"]:
                self.kinds.append("acts")
                return {"acts": [{
                    "id": "01", "title": "第一幕", "summary": "她回家并慢慢脱衣",
                    "cast": "1girl solo", "clothing": "black blazer to leotard",
                    "scene": "bedroom", "nsfw": "slow undress",
                }]}
            if schema is storyboard.OUTLINE_SCHEMA:
                self.kinds.append("outline")
                return {"shots": [
                    {"id": "01", "name": "a", "cast": "1girl solo",
                     "outline": "她站在卧室，慢慢脱下外套"},
                    {"id": "02", "name": "b", "cast": "1girl solo",
                     "outline": "她坐在床边，黑丝还穿着"},
                ]}
            if schema is storyboard.TAG_SCHEMA:
                self.kinds.append("tag")
                return {"shots": [
                    {"id": "01", "prompt": "1girl, solo, standing, undressing"},
                    {"id": "02", "prompt": "1girl, solo, sitting on bed, black pantyhose"},
                ]}
            raise AssertionError(schema)

    fake = PipelineFake()
    shots = storyboard.generate_storyboard(
        fake, "角色：她\n初始服装：black blazer, black pantyhose\n"
              "大场景：卧室\n剧情：\n她回家，慢慢脱衣，最后做爱",
        storyboard.StoryboardOptions(model="test", shots=2, chunk=2,
                                     full_story=True))
    assert fake.kinds == ["story", "acts", "outline", "tag"]
    assert len(shots) == 2
    assert shots[0]["prompt"].startswith("1girl, solo, standing, undressing")
    assert "black pantyhose" in shots[0]["prompt"]
    assert "black pantyhose" in shots[1]["prompt"]


def test_generate_bounds_output_tokens_and_timeout():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    generate_storyboard(client, "01. one\n02. two",
                        StoryboardOptions(model="test-model", shots=2, chunk=2))
    kwargs = client.calls[0][1]
    assert 1536 <= kwargs["num_predict"] <= 16384
    assert kwargs["timeout"] == 240.0


def test_generate_writes_partial_checkpoint_after_each_chunk():
    from comfyui_generator.core.storyboard import generate_storyboard
    snapshots = []
    client = FakeClient()
    generate_storyboard(
        client, "01. one\n02. two",
        StoryboardOptions(model="test-model", shots=2, chunk=2,
                          on_partial=lambda shots: snapshots.append(len(shots))))
    assert snapshots == [2]


def test_generate_with_initial_shot_keeps_it():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "anchor", "prompt": "wide shot, standing"}]
    options = StoryboardOptions(model="test-model", shots=3)
    shots = generate_storyboard(client, "a walk", options, initial_shots=initial)
    assert len(shots) == 3
    assert shots[0] == initial[0]
    assert [shot["id"] for shot in shots] == ["01", "02", "03"]
    assert len(client.calls) == 6
    assert "本次生成镜头数：2" in client.calls[1][0][1]["content"]


def test_generate_passes_exact_numbered_beats_for_chunk():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    premise = "01. first action\n02. second action"
    shots = generate_storyboard(client, premise, StoryboardOptions(model="test-model", shots=2))
    assert len(shots) == 2
    user = client.calls[0][0][1]["content"]
    assert "硬性剧情条目" in user
    assert "1. first action" in user
    assert "2. second action" in user


def test_long_story_is_split_into_acts_and_keeps_global_ids():
    from comfyui_generator.core.storyboard import generate_storyboard

    class LongFake:
        def __init__(self):
            self.act_calls = 0

        def chat_json(self, model, messages, **kwargs):
            schema = kwargs.get("schema") or {}
            if (schema.get("required") or []) == ["acts"]:
                self.act_calls += 1
                return {"acts": [
                    {"id": "01", "title": "独处",
                     "summary": "她回家后独处自慰",
                     "cast": "1girl solo", "clothing": "",
                     "scene": "beach", "nsfw": "masturbation"},
                    {"id": "02", "title": "发现与插入",
                     "summary": "男主发现她并进入",
                     "cast": "1girl 1boy", "clothing": "",
                     "scene": "beach", "nsfw": "sex"},
                ]}
            return {"shots": [
                {"id": "%02d" % index, "name": "s%02d" % index,
                 "script": "脚本", "prompt": "1girl, solo",
                 "outline": "镜头", "cast": "1girl solo"}
                for index in range(1, 7)
            ]}

    client = LongFake()
    shots = generate_storyboard(
        client, "剧情：她回家，自慰，被我看到，做爱",
        StoryboardOptions(model="test-model", shots=31, chunk=3,
                          log=lambda _message: None))
    assert client.act_calls == 1
    assert len(shots) == 31
    assert shots[0]["id"] == "01"
    assert shots[-1]["id"] == "31"


def test_generate_with_initial_and_no_extra_shots_does_not_call_model():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "only", "prompt": "wide shot"}]
    shots = generate_storyboard(client, "x", StoryboardOptions(model="test-model", shots=1),
                                initial_shots=initial)
    assert shots == initial
    assert client.calls == []


def test_only_moonlight_does_not_strip_clothing():
    profile = parse_character_profiles(
        "角色：女主：yixuan\n"
        "初始服装：uniform, black pantyhose")[0]
    state = character_states_for_beats([profile], ["只剩月光"])[0][profile.key]
    assert state == {"uniform", "black pantyhose"}


def test_full_nude_only_clears_clothing_near_the_end():
    profile = parse_character_profiles(
        "角色：女主：yixuan\n初始服装：uniform, black pantyhose")[0]
    early = character_states_for_beats(
        [profile], ["继续", "全裸", "继续", "继续"])[1][profile.key]
    late = character_states_for_beats(
        [profile], ["继续", "继续", "全裸", "继续"])[2][profile.key]
    assert early == {"uniform", "black pantyhose"}
    assert late == set()


def test_male_profile_details_are_stripped():
    profiles = parse_character_profiles(
        "角色：女主：silver hair；男主：black hair\n"
        "初始服装：女主：black dress；男主：white shirt, black pants")
    strip_male_profile_details(profiles)
    girl, boy = profiles
    assert girl.initial_clothing == ["black dress"]
    assert girl.appearance == ["silver hair"]
    assert boy.appearance == []
    assert boy.initial_clothing == []


def test_clothing_weight_suffix_is_normalized():
    profile = parse_character_profiles(
        "角色：女主：yixuan\n"
        "初始服装：black pantyhose(1.2), bra(1.2)")[0]
    assert profile.initial_clothing == [
        "(black pantyhose:1.2)", "(bra:1.2)"]


def test_clothing_weight_colon_is_not_parsed_as_character_entries():
    profiles = parse_character_profiles(
        "初始服装：black pantyhose:1.2,black panties:1.2, black bra:1.2")
    assert len(profiles) == 1
    assert profiles[0].initial_clothing == [
        "(black pantyhose:1.2)", "(black panties:1.2)", "(black bra:1.2)"]


def test_parenthesized_weight_is_not_parsed_as_character_entries():
    profiles = parse_character_profiles(
        "初始服装：(black pantyhose:1.2),(black panties:1.2), "
        "(black bra:1.2),(lace:1.1)")
    assert len(profiles) == 1
    assert profiles[0].initial_clothing == [
        "(black pantyhose:1.2)", "(black panties:1.2)",
        "(black bra:1.2)", "(lace:1.1)"]


def test_upper_body_only_removal_keeps_lower_body_clothing():
    profile = parse_character_profiles(
        "角色：女主：yixuan\n"
        "初始服装：black bra, black panties, black pantyhose, "
        "purple skirt, red vest")[0]
    state = character_states_for_beats(
        [profile], ["上半身只剩黑色蕾丝胸罩"])[0][profile.key]
    assert "black bra" in state
    assert "black panties" in state
    assert "black pantyhose" in state
    assert "purple skirt" in state
    assert "red vest" not in state


def test_partial_clothing_removal_keeps_item_but_full_removal_drops_it():
    profile = parse_character_profiles(
        "角色：女主：yixuan\n"
        "初始服装：black lace bra, black pantyhose")[0]
    partial = character_states_for_beats(
        [profile], ["解开胸罩背扣，肩带滑落"])[0][profile.key]
    assert "black lace bra" in partial
    full = character_states_for_beats(
        [profile], ["脱下胸罩"])[0][profile.key]
    assert "black lace bra" not in full


def test_finalize_dedupes_weighted_clothes():
    shot = {
        "prompt": "1girl, 1boy, sex, (black bra:1.2), black_bra, "
                  "(black pantyhose:1.2), black_pantyhose",
        "clothing": "black bra, black pantyhose",
    }
    _finalize_shot_prompt(shot, "black bra, black pantyhose")
    prompt = shot["prompt"]
    tags = [tag.strip() for tag in prompt.split(",")]
    assert "(black bra:1.2)" in tags
    assert "black_bra" not in tags
    assert "(black pantyhose:1.2)" in tags
    assert "black_pantyhose" not in tags


def test_half_off_clothing_combines_with_base_item():
    shot = {
        "prompt": "1girl, 1boy, (black pantyhose:1.2), pantyhose pulled down, "
                  "black_bra, bra pull, torn pantyhose",
        "script": "她把连裤袜褪到膝盖，胸罩半脱。",
        "clothing": "black pantyhose, black bra",
    }
    _finalize_shot_prompt(shot, "black pantyhose, black bra")
    prompt = shot["prompt"]
    tags = [tag.strip() for tag in prompt.split(",")]
    assert "(black pantyhose:1.2)" not in tags
    assert any("black pantyhose around thighs" in tag for tag in tags)
    assert "upper thighs bare" in tags
    assert "thighs exposed" in tags
    assert "one leg out" not in tags


def test_half_off_is_removed_when_script_does_not_describe_it():
    shot = {
        "prompt": "1girl, (black pantyhose:1.2), pantyhose pulled down",
        "script": "她穿着完整的连裤袜站在沙滩上。",
        "clothing": "black pantyhose",
    }
    _finalize_shot_prompt(shot, "black pantyhose")
    prompt = shot["prompt"]
    assert "pantyhose pulled down" not in prompt
    assert "around thighs" not in prompt
    assert "(black pantyhose:1.2)" in prompt


def test_half_off_tag_is_not_duplicated_on_repeated_finalize():
    shot = {
        "prompt": "1girl, (black pantyhose:1.2), pantyhose pulled down",
        "script": "她把连裤袜褪到膝盖。",
        "clothing": "black pantyhose",
    }
    _finalize_shot_prompt(shot, "black pantyhose")
    _finalize_shot_prompt(shot, "black pantyhose")
    prompt = shot["prompt"]
    assert "around thighs around thighs" not in prompt
    assert prompt.count("around thighs") == 1


def test_cast_normalization_handles_nonstandard_forms():
    assert normalize_cast("1girl 1boy", "") == "1girl 1boy"
    assert normalize_cast("ren yamashiro + 我", "她看着他") == "1girl 1boy"
    assert normalize_cast("", "我看着她") == "1girl 1boy"
    assert normalize_cast("", "她独自坐着") == "1girl solo"
    assert normalize_cast("1boy solo", "") == "1boy solo"


def test_cast_normalization_prefers_explicit_solo_script():
    script = "角色/cast：少女（1girl solo）；服装：black bra；动作：自慰；无男性参与。"
    assert normalize_cast("1girl 1boy", script) == "1girl solo"


def test_final_wardrobe_removes_unweighted_but_keeps_weighted():
    premise = (
        "角色：女主\n"
        "初始服装：uniform, red cape, white gloves, black platform heels, "
        "(black bra:1.2), (black lace panties:1.2), (black pantyhose:1.2)")
    profiles = parse_character_profiles(premise)
    shot = {
        "id": "50",
        "prompt": ("1girl, uniform, red cape, white gloves, black platform heels, "
                   "skirt around thighs, (black bra:1.2), "
                   "(black lace panties:1.2), torn pantyhose, cum on face"),
        "character_states": {
            profiles[0].key: ("uniform, red cape, white gloves, black platform heels, "
                              "skirt around thighs, (black bra:1.2), "
                              "(black lace panties:1.2), torn pantyhose")},
        "clothing_details": {
            profiles[0].key: "cape removed, red cape on sofa, skirt around thighs, "
                             "torn pantyhose"},
    }
    enforce_final_wardrobe([shot], profiles)
    assert "uniform" not in shot["prompt"]
    assert "red cape" not in shot["prompt"]
    assert "white gloves" not in shot["prompt"]
    assert "black platform heels" not in shot["prompt"]
    assert "skirt" not in shot["prompt"]
    assert "(black bra:1.2)" in shot["prompt"]
    assert "(black lace panties:1.2)" in shot["prompt"]
    assert "torn pantyhose" in shot["prompt"]
    assert "uniform" not in shot["character_states"][profiles[0].key]
    assert "red cape" not in shot["clothing_details"][profiles[0].key]


def test_final_climax_gets_afterglow_and_script():
    shots = [{
        "id": "50",
        "phase": "正面冲刺顶点",
        "prompt": "1girl, 1boy, cum on stomach, orgasm",
        "script": "男主体外射精，女主到达顶点。",
    }]
    ensure_final_afterglow(shots)
    assert "afterglow" in shots[0]["prompt"]
    assert "after sex" in shots[0]["prompt"]
    assert "事后余韵" in shots[0]["phase"]
    assert "事后余韵" in shots[0]["script"]


def test_premise_layered_masturbation_fills_missing_inside_contact():
    premise = "剧情：先隔着裤袜和内裤自慰，然后手伸进内裤里摸阴唇自慰"
    shots = [
        {"id": "06", "script": "她隔着内裤揉按自慰",
         "prompt": "1girl, solo, rubbing through panties"},
        {"id": "07", "script": "她把裤袜拉低，继续隔着内裤自慰",
         "prompt": "1girl, solo, pantyhose pulled down, through panties"},
        {"id": "08", "script": "她高潮了",
         "prompt": "1girl, solo, orgasm"},
    ]
    enforce_premise_masturbation_layers(shots, premise)
    assert "hand inside panties" in shots[1]["prompt"]
    assert "hand inside pantyhose" in shots[1]["prompt"]
    assert "fingers on labia" in shots[1]["prompt"]
    assert "through panties" not in shots[1]["prompt"]
    assert "直接接触阴唇" in shots[1]["script"]


def test_layered_masturbation_adds_inside_layers_and_labia():
    shots = [{
        "id": "06",
        "script": "她把手伸进黑色裤袜和内裤里，指尖直接摸阴唇自慰",
        "prompt": "1girl, solo, hand between legs, rubbing through pantyhose",
    }]
    ensure_layered_masturbation(shots)
    prompt = shots[0]["prompt"]
    assert "hand inside pantyhose" in prompt
    assert "hand inside panties" in prompt
    assert "fingers on labia" in prompt
    assert "直接接触阴唇" in shots[0]["script"]


def test_layer_action_keeps_base_clothing_when_hand_is_inside():
    prompt = ("1girl, military uniform, black bra, black lace panties, "
              "black pantyhose, hand under clothes, hand inside bra, "
              "hand inside panties, hand inside pantyhose, fingers on labia")
    worn = {
        "military uniform", "black bra", "black lace panties",
        "black pantyhose"}
    result = apply_story_state(prompt, worn, worn)
    for tag in ("military uniform", "black bra", "black lace panties",
                "black pantyhose", "hand under clothes", "hand inside bra",
                "hand inside panties", "hand inside pantyhose",
                "fingers on labia"):
        assert tag in result


def test_outerwear_closed_hides_innerwear_but_keeps_hand_action():
    shots = [{
        "id": "01",
        "prompt": ("1girl, military uniform, military skirt, black bra, "
                   "black lace panties, black pantyhose, hand under clothes, "
                   "hand inside bra, hand inside panties, fingers on labia"),
    }]
    ensure_outerwear_occlusion(shots)
    prompt = shots[0]["prompt"]
    assert "black bra" not in prompt
    assert "black lace panties" not in prompt
    assert "hand under clothes" in prompt
    assert "hand inside bra" in prompt
    assert "hand inside panties" in prompt


def test_outerwear_open_allows_innerwear_visibility():
    shots = [{
        "id": "10",
        "prompt": ("1girl, military uniform, military skirt, open shirt, "
                   "black bra, black lace panties"),
    }]
    ensure_outerwear_occlusion(shots)
    assert "black bra" in shots[0]["prompt"]
    assert "black lace panties" not in shots[0]["prompt"]
    open_skirt = [{
        "id": "11",
        "prompt": ("1girl, military uniform, military skirt, skirt lifted, "
                   "black bra, black lace panties"),
    }]
    ensure_outerwear_occlusion(open_skirt)
    assert "black lace panties" in open_skirt[0]["prompt"]


def test_sheer_blouse_allows_bra_visible_through_layer():
    shots = [{
        "id": "12",
        "prompt": "1girl, sheer blouse, black bra, black lace panties",
    }]
    ensure_clothing_layers(shots)
    prompt = shots[0]["prompt"]
    assert "bra visible through shirt" in prompt
    ensure_outerwear_occlusion(shots)
    assert "black bra" in shots[0]["prompt"]
    assert "bra visible through shirt" in shots[0]["prompt"]


def test_sheer_pantyhose_shows_panties_underneath():
    shots = [{
        "id": "06",
        "prompt": ("1girl, military skirt, sheer pantyhose, "
                   "black lace panties"),
    }]
    ensure_clothing_layers(shots)
    prompt = shots[0]["prompt"]
    assert "panties visible through pantyhose" in prompt
    assert "sheer pantyhose" in prompt
    ensure_outerwear_occlusion(shots)
    assert "black lace panties" in shots[0]["prompt"]


def test_layered_breast_contact_adds_under_outerwear_tags():
    shots = [{
        "id": "03",
        "script": "她从军装外衣下伸手进去，探进胸罩里摸乳房",
        "prompt": "1girl, military uniform, black bra, sitting",
    }]
    ensure_layered_breast_contact(shots)
    prompt = shots[0]["prompt"]
    assert "hand under clothes" in prompt
    assert "hand inside bra" in prompt
    assert "breast grab" in prompt
    assert "从外衣下伸入胸罩" in shots[0]["script"]


def test_layered_masturbation_does_not_add_inside_for_through_clothes():
    shots = [{
        "id": "02",
        "script": "她隔着裤袜和内裤轻轻揉阴唇",
        "prompt": "1girl, solo, rubbing through pantyhose, through panties",
    }]
    ensure_layered_masturbation(shots)
    prompt = shots[0]["prompt"]
    assert "hand inside pantyhose" not in prompt
    assert "hand inside panties" not in prompt
    assert "fingers on labia" in prompt


def test_weighted_clothing_allows_half_off_but_not_removal():
    premise = (
        "角色：女主\n"
        "初始服装：uniform, white gloves, (black bra:1.2), "
        "(black lace panties:1.2), (torn pantyhose:1.2), "
        "(black platform heels:1.2)")
    profiles = parse_character_profiles(premise)
    shot = {
        "id": "47",
        "prompt": ("1girl, 1boy, uniform, white gloves, bra removed, "
                   "panties aside, pantyhose pulled down, barefoot, "
                   "right black platform heel on floor, sex"),
        "cast": "1girl 1boy",
        "character_states": {},
        "clothing_details": {},
    }
    enforce_weighted_core([shot], profiles)
    assert "(black bra:1.2)" in shot["prompt"]
    assert "(black platform heels:1.2)" in shot["prompt"]
    assert "bra removed" not in shot["prompt"]
    assert "barefoot" not in shot["prompt"]
    assert "panties aside" in shot["prompt"]
    assert "pantyhose pulled down" in shot["prompt"]


def test_weighted_clothing_keeps_half_off_without_adding_base():
    premise = (
        "角色：女主\n"
        "初始服装：(black bra:1.2), (black lace panties:1.2), "
        "(black platform heels:1.2)")
    profiles = parse_character_profiles(premise)
    shot = {
        "id": "20",
        "prompt": "1girl, 1boy, bra pull, panties aside, one heel off",
        "cast": "1girl 1boy",
    }
    enforce_weighted_core([shot], profiles)
    assert shot["prompt"].count("(black bra:1.2)") == 0
    assert shot["prompt"].count("(black platform heels:1.2)") == 0
    assert "bra pull" in shot["prompt"]
    assert "one heel off" in shot["prompt"]


def test_intimacy_stage_detects_post_sex_regression():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, vaginal sex, penis in pussy"},
        {"id": "02", "prompt": "1girl, 1boy, afterglow, cum on face"},
        {"id": "03", "prompt": "1girl, 1boy, standing, masturbation"},
        {"id": "04", "prompt": "1girl, 1boy, fellatio"},
    ]
    assert _intimacy_stage(shots[0]) == 3
    assert _intimacy_stage(shots[1]) == 4
    regressions = _intimacy_regressions(shots)
    assert [item["id"] for item in regressions] == ["03", "04"]


def test_focus_tags_get_weight_but_plain_tags_do_not():
    shots = [{
        "prompt": "1girl, hand between legs, panties aside, night, close-up",
        "focus_tags": ["hand between legs", "panties aside"],
    }]
    apply_focus_weights(shots)
    assert "(hand between legs:1.2)" in shots[0]["prompt"]
    assert "(panties aside:1.2)" in shots[0]["prompt"]
    assert "1girl," in shots[0]["prompt"]
    assert "night," in shots[0]["prompt"]


def test_normalize_tagged_keeps_focus_tags():
    scripts = [{"id": "01", "name": "a", "script": "她自慰",
                "cast": "1girl solo", "phase": "自慰"}]
    shots = normalize_tagged({"shots": [{
        "id": "01", "prompt": "1girl, masturbation",
        "focus": ["masturbation"],
    }]}, scripts)
    assert shots[0]["focus_tags"] == ["masturbation"]


def test_normalize_tagged_falls_back_phase_from_outline():
    scripts = [{
        "id": "01", "name": "a", "script": "她坐在车里",
        "cast": "1girl solo", "phase": "", "outline": "前戏：车内等待",
    }]
    shots = normalize_tagged({"shots": [{"id": "01", "prompt": "1girl"}]}, scripts)
    assert shots[0]["phase"] == "前戏：车内等待"


def test_shots_from_json_keeps_phase_and_beat():
    shot = shots_from_json({"shots": [{
        "id": "01", "prompt": "1girl, solo", "phase": "前戏",
        "beat": "车内等待", "outline": "等待",
    }]})[0]
    assert shot["phase"] == "前戏"
    assert shot["beat"] == "车内等待"


def test_normalize_shot_casts_uses_script_presence():
    shots = [
        {"id": "01", "cast": "1girl solo", "script": "她独自坐着"},
        {"id": "02", "cast": "1girl solo", "script": "陌生男人走到她面前"},
    ]
    normalize_shot_casts(shots)
    assert shots[0]["cast"] == "1girl solo"
    assert shots[1]["cast"] == "1girl 1boy"


def test_renumber_shots_fills_gaps_and_removes_duplicates():
    shots = [{"id": "01"}, {"id": "02"}, {"id": "04"}, {"id": "04"}]
    renumber_shots(shots)
    assert [shot["id"] for shot in shots] == ["01", "02", "03", "04"]


def test_repair_missing_actions_updates_phase_from_label():
    class FakeClient:
        def chat_json(self, model, messages, **kwargs):
            return {"actions": [{
                "id": "sex",
                "label": "sex",
                "shot_id": "02",
                "script": "they have vaginal sex",
                "prompt": "1girl, 1boy, vaginal sex, penis in pussy",
            }]}

    shots = [
        {"id": "01", "phase": "自慰", "prompt": "1girl, masturbation"},
        {"id": "02", "phase": "自慰", "prompt": "1girl, 1boy, standing"},
        {"id": "03", "phase": "余韵", "prompt": "1girl, 1boy, afterglow"},
    ]
    repair_missing_actions_ai(FakeClient(), "model", shots, "story")
    assert shots[1]["phase"] == "sex"
    assert "vaginal sex" in shots[1]["prompt"]


def test_repair_missing_actions_uses_ai_action_ledger():
    premise = "补上女主自慰，补上口交（男、女都要有），补上呑精镜头"

    class FakeClient:
        def chat_json(self, model, messages, **kwargs):
            return {"actions": [{
                "id": "male_oral_female",
                "label": "男主对女主口交",
                "shot_id": "03",
                "cast": "1girl 1boy",
                "script": "男人跪在女主腿间，用舌头舔弄她的阴部。",
                "prompt": ("1boy, 1girl, cunnilingus, licking pussy, "
                           "male between female legs, pussy juice"),
            }]}

    shots = [
        {"id": "01", "script": "她自慰", "prompt": "1girl, masturbation"},
        {"id": "02", "script": "她给男主口交并吞精",
         "prompt": "1girl, 1boy, fellatio, cum swallowing"},
        {"id": "03", "script": "男主站在她面前", "prompt": "1girl, 1boy"},
        {"id": "04", "script": "男主插入",
         "prompt": "1girl, 1boy, penis in pussy"},
    ]
    repair_missing_actions_ai(FakeClient(), "model", shots, premise)
    assert "cunnilingus" in shots[2]["prompt"]


def test_action_audit_mentions_clothing_destruction_requirements():
    messages = _action_audit_messages("撕开裤袜", [])
    assert "服装破坏" in messages[0]["content"]
    assert "pulled aside" in messages[0]["content"]


def test_phase_backtracks_detects_non_contiguous_stage_return():
    shots = [
        {"id": "01", "phase": "自慰"},
        {"id": "02", "phase": "自慰"},
        {"id": "03", "phase": "口交"},
        {"id": "04", "phase": "自慰"},
    ]
    backtracks = _phase_backtracks(shots)
    assert backtracks == [{"phase": "自慰", "first": "01", "again": "04"}]


def test_repetitive_shot_groups_catches_near_duplicate_below_old_threshold():
    shots = [
        {"id": "01", "script": "male standing outside car leaning in commanding"},
        {"id": "02", "script": "male standing outside car leaning in watching"},
        {"id": "03", "script": "completely different action"},
    ]
    assert ["01", "02"] in repetitive_shot_groups(shots)


def test_repetitive_shot_groups_detects_near_duplicates():
    shots = [
        {"id": "01", "script": "男人把她抱起来，双腿M字悬空，插入。"},
        {"id": "02", "script": "男人把她抱起来，双腿M字悬空，插入。"},
        {"id": "03", "script": "她独自坐在长椅上喘息。"},
    ]
    groups = repetitive_shot_groups(shots)
    assert ["01", "02"] in groups


def test_pacing_audit_payload_is_trimmed_for_long_batches():
    shots = [{
        "id": "%02d" % i,
        "phase": "自慰",
        "script": "长" * 2000,
        "prompt": "tag, " * 500,
    } for i in range(1, 51)]
    messages = _pacing_audit_messages(shots, "剧情", [], [])
    payload = messages[1]["content"]
    assert len(payload) < 60000
    assert "长" * 2000 not in payload


def test_repair_story_pacing_rewrites_duplicate_as_variation():
    shots = [
        {"id": "01", "phase": "口交", "script": "她跪着吞吐，头部前后移动。",
         "prompt": "1girl, 1boy, fellatio"},
        {"id": "02", "phase": "口交", "script": "她跪着吞吐，头部前后移动。",
         "prompt": "1girl, 1boy, fellatio"},
    ]

    class Fake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [{
                "id": "02", "valid": False,
                "script": "她放慢吞吐，只含住前端，舌尖绕弄，唾液拉丝，眼神上抬。",
                "prompt": "1girl, 1boy, licking tip, tongue, saliva, eye contact",
            }]}

    repair_story_pacing_ai(Fake(), "m", shots, "口交")
    assert shots[1]["script"] != shots[0]["script"]
    assert "licking tip" in shots[1]["prompt"]


def test_outline_output_does_not_require_name_and_keeps_structured_fields():
    outline = normalize_outline({"shots": [{
        "id": "01", "cast": "1girl solo", "phase": "前戏",
        "beat": "她开始试探", "clothing": "black pantyhose",
        "scene": "beach", "camera": "medium shot", "nsfw": "mild",
        "outline": "她坐在沙滩巾上开始试探",
    }]}, 1, "story")
    assert outline[0]["name"] == "story_01"
    assert outline[0]["phase"] == "前戏"
    assert outline[0]["clothing"] == "black pantyhose"


def test_act_plan_uses_ai_start_end_and_beats():
    acts = normalize_acts({"acts": [
        {"id": "01", "title": "前戏", "start": 1, "end": 15,
         "beats": ["试探", "第一次触碰"], "summary": "前戏",
         "cast": "1girl solo", "clothing": "", "scene": "beach",
         "nsfw": "mild"},
        {"id": "02", "title": "事后", "start": 16, "end": 20,
         "beats": ["余韵"], "summary": "事后",
         "cast": "1girl solo", "clothing": "", "scene": "beach",
         "nsfw": "afterglow"},
    ]}, 20, "story")
    assert acts[0]["start"] == 1
    assert acts[0]["end"] == 15
    assert acts[0]["beats"] == ["试探", "第一次触碰"]
    assert acts[1]["start"] == 16


def test_normalize_acts_fills_gaps_and_covers_total():
    acts = normalize_acts({"acts": [
        {"title": "A", "start": 1, "end": 37, "summary": "a"},
        {"title": "B", "start": 39, "end": 50, "summary": "b"},
    ]}, 50, "story")
    assert acts[0]["start"] == 1
    assert acts[0]["end"] == 37
    assert acts[1]["start"] == 38
    assert acts[1]["end"] == 50
    assert acts[-1]["end"] == 50
