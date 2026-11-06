import json

import pytest

from comfyui_generator.core.storyboard import (
    ACT_PLAN_SCHEMA,
    ACT_PLAN_SYSTEM,
    OUTLINE_SCHEMA,
    OUTLINE_SYSTEM,
    SCRIPT_SCHEMA,
    SCRIPT_SYSTEM,
    STORY_SCHEMA,
    STORY_SYSTEM,
    TAG_SCHEMA,
    TAG_SYSTEM,
    CharacterProfile,
    StoryboardOptions,
    build_act_plan_messages,
    build_outline_messages,
    build_premise_act_plan_messages,
    build_script_messages,
    build_story_messages,
    build_tag_messages,
    character_bible_text,
    extract_premise_beats,
    finalize_generated_story,
    generate_storyboard,
    normalize_acts,
    normalize_character_profiles,
    normalize_outline,
    normalize_scripts,
    normalize_shot_casts,
    normalize_tagged,
    parse_character_profiles,
    plan_story_spine,
    plan_storyboard_outline,
    premise_from_json,
    raw_prompt,
    renumber_shots,
    run_all_reviews,
    shots_from_json,
    slugify,
    strip_male_profile_details,
    wardrobe_weight_policy,
)
from comfyui_generator.core.mechanical import normalize_prompt_text
from comfyui_generator.core.ai_review import (
    REVIEW_STAGE_LABELS,
    review_stage_ai,
)

PROMPT_CONVERSION_FLASH_MODEL = "volcengine/deepseek-v4.1-flash"


def make_options(**kwargs):
    values = {
        "model": "test-model",
        "log": lambda _msg: None,
    }
    values.update(kwargs)
    return StoryboardOptions(**values)


# ----------------------------------------------------------------- text helpers

def test_raw_prompt_strips_labels_and_whitespace():
    assert raw_prompt("prompt: 1girl, smile") == "1girl, smile"
    assert raw_prompt("tags：\n1girl, smile") == "1girl, smile"
    assert raw_prompt("  1girl, smile. ") == "1girl, smile"


def test_slugify_lowercases_and_collapses():
    assert slugify("Hello,  World!") == "hello_world"
    assert slugify("", "fb") == "fb"


def test_extract_premise_beats_keeps_numbered_lines():
    text = "1. first beat\n2. second beat\nno number\n3. third"
    assert extract_premise_beats(text) == [
        "first beat", "second beat", "third"]


# ------------------------------------------------------------------- json import

def test_shots_from_json_reads_array_and_fields():
    data = {"shots": [
        {"id": "01", "prompt": "1girl, smile", "cast": "1girl solo",
         "script": "中文脚本"},
        {"id": "02", "prompt": "1girl, sitting"},
    ]}
    shots = shots_from_json(data)
    assert [s["id"] for s in shots] == ["01", "02"]
    assert shots[0]["cast"] == "1girl solo"
    assert shots[0]["script"] == "中文脚本"


def test_shots_from_json_reads_plain_strings():
    shots = shots_from_json(["1girl, smile", "1girl, sitting"])
    assert shots[0]["prompt"] == "1girl, smile"
    assert shots[0]["id"] == "01"


def test_shots_from_json_raises_when_empty():
    with pytest.raises(ValueError):
        shots_from_json({"shots": []})


def test_premise_from_json_reads_common_keys():
    assert premise_from_json({"premise": "abc"}) == "abc"
    assert premise_from_json({"data": {"story": "xyz"}}) == "xyz"
    assert premise_from_json({}) == ""


# ------------------------------------------------------------- character profiles

PREMISE = (
    "外貌身材：blonde hair, purple eyes, long hair\n"
    "初始服装：(black pantyhose:1.2), black skirt, white coat\n"
    "剧情：\n夜晚教室\n"
)


def test_parse_character_profiles_locks_appearance():
    profiles = parse_character_profiles(PREMISE)
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.name == "main"
    assert "blonde hair" in profile.appearance
    assert "purple eyes" in profile.appearance
    assert "(black pantyhose:1.2)" in profile.initial_clothing
    assert "black skirt" in profile.initial_clothing
    assert profile.appearance_locked is True


def test_character_bible_text_mentions_lock_rules():
    profile = CharacterProfile(
        key="char_01", name="hero", gender="girl",
        appearance=["purple eyes"], initial_clothing=["black skirt"])
    text = character_bible_text([profile])
    assert "角色锁定表" in text
    assert "purple eyes" in text


def test_normalize_character_profiles_merges_ai_details():
    merge_premise = (
        "初始服装：(black pantyhose:1.2), black skirt, white coat\n"
        "剧情：夜晚教室\n"
    )
    raw = [{
        "name": "main", "gender": "girl",
        "appearance": "blonde hair, purple eyes, smile",
        "initial_clothing": "(black pantyhose:1.2), black skirt",
    }]
    profiles = normalize_character_profiles(raw, merge_premise)
    girl = next(p for p in profiles if p.name == "main")
    assert "smile" in girl.appearance
    assert "(black pantyhose:1.2)" in girl.initial_clothing


def test_strip_male_profile_details_clears_boy_data():
    profiles = [
        CharacterProfile(key="char_01", name="boy", gender="boy",
                         appearance=["handsome"], initial_clothing=["shirt"]),
        CharacterProfile(key="char_02", name="girl", gender="girl",
                         appearance=["purple eyes"]),
    ]
    strip_male_profile_details(profiles)
    assert profiles[0].appearance == []
    assert profiles[0].initial_clothing == []
    assert profiles[1].appearance == ["purple eyes"]


# ------------------------------------------------------------------- normalize

def _outline_raw():
    return {"shots": [
        {"id": "01", "cast": "1girl solo", "outline": "第一个大纲"},
        {"id": "02", "cast": "1girl solo", "outline": "第二个大纲"},
    ]}


def test_normalize_outline_keeps_fields_and_ids():
    shots = normalize_outline(_outline_raw(), 2, "story", start=1)
    assert [s["id"] for s in shots] == ["01", "02"]
    assert shots[0]["outline"] == "第一个大纲"
    assert shots[0]["cast"] == "1girl solo"


def test_normalize_outline_dedupes_names():
    shots = normalize_outline(
        {"shots": [
            {"name": "a", "outline": "x"},
            {"name": "a", "outline": "y"}]},
        2, "story", start=1)
    assert shots[0]["name"] == "a"
    assert shots[1]["name"] == "a_2"


def test_normalize_scripts_reads_script_text():
    raw = {"shots": [
        {"id": "01", "cast": "1girl solo", "script": "脚本一"},
        {"id": "02", "cast": "1girl solo", "script": "脚本二"},
    ]}
    scripts = normalize_scripts(raw, 2, "story")
    assert scripts[0]["script"] == "脚本一"
    assert scripts[0]["cast"] == "1girl solo"


def test_normalize_scripts_falls_back_to_fields():
    raw = {"shots": [
        {"id": "01", "cast": "1girl solo", "beat": "动作节拍",
         "clothing": "black skirt"},
    ]}
    scripts = normalize_scripts(raw, 1, "story")
    joined = scripts[0]["script"]
    assert "动作节拍" in joined
    assert "black skirt" in joined


def test_normalize_tagged_matches_by_id():
    raw = {"shots": [
        {"id": "01", "prompt": "1girl, smile", "negative": "bad quality"},
        {"id": "02", "prompt": "1girl, sitting", "negative": "lowres"},
    ]}
    scripts = [
        {"id": "01", "name": "n1", "script": "脚本一"},
        {"id": "02", "name": "n2", "script": "脚本二"},
    ]
    shots = normalize_tagged(raw, scripts)
    assert shots[0]["prompt"] == "1girl, smile"
    assert shots[0]["negative"] == "bad quality"
    assert shots[0]["script"] == "脚本一"


# --------------------------------------------------------------- message builds

def test_build_story_messages_include_premise_and_count():
    messages = build_story_messages("用户剧情", 50, "夜晚")
    user = messages[1]["content"]
    assert "用户剧情" in user
    assert "50" in user
    assert "夜晚" in user
    assert messages[0]["content"] == STORY_SYSTEM


def test_build_act_plan_messages_include_story_and_limits():
    messages = build_act_plan_messages("完整剧情", "前提", 50, "夜晚")
    user = messages[1]["content"]
    assert "完整剧情" in user
    assert "50" in user


def test_build_outline_messages_include_context():
    messages = build_outline_messages(
        "剧情前提", 6, "夜晚", [], 50, start=7)
    user = messages[1]["content"]
    assert "剧情前提" in user
    assert "7-12" in user
    assert "夜晚" in user


def test_build_script_messages_include_prior_and_beats():
    messages = build_script_messages(
        "剧情", 2, "夜晚",
        [{"id": "01", "script": "上一段脚本"}], 50, ["beat a", "beat b"])
    user = messages[1]["content"]
    assert "beat a" in user
    assert "上一段脚本" in user


def test_build_tag_messages_include_scripts():
    messages = build_tag_messages(
        [{"id": "01", "name": "n", "script": "脚本内容", "outline": "节点"}],
        setting="夜晚")
    user = messages[1]["content"]
    assert "脚本内容" in user
    assert "夜晚" in user


def test_build_premise_act_plan_messages_include_premise():
    messages = build_premise_act_plan_messages("前提", 50)
    assert "前提" in messages[1]["content"]


# -------------------------------------------------------------- wardrobe policy

def test_wardrobe_weight_policy_distinguishes_weighted():
    text = "初始服装：(black pantyhose:1.2), white coat"
    policy = wardrobe_weight_policy(text)
    assert "带权重" in policy
    assert "black pantyhose" in policy
    assert "white coat" in policy


def test_wardrobe_weight_policy_empty_without_split():
    assert wardrobe_weight_policy("初始服装：white coat") == ""


# ------------------------------------------------------------- structural bookkeeping

def test_renumber_shots_assigns_sequential_ids():
    shots = [{"id": "x"}, {"id": "y"}]
    renumber_shots(shots)
    assert [s["id"] for s in shots] == ["01", "02"]


def test_normalize_shot_casts_trims_without_inference():
    shots = [{"cast": " 1girl  solo "}, {"cast": ""}]
    normalize_shot_casts(shots)
    assert shots[0]["cast"] == "1girl solo"
    assert shots[1]["cast"] == ""


def test_normalize_acts_fills_gaps():
    raw = {"acts": [
        {"title": "A", "summary": "first", "start": 1, "end": 20},
        {"title": "B", "summary": "second", "start": 25, "end": 60},
    ]}
    acts = normalize_acts(raw, 50, "story")
    assert acts[0]["start"] == 1
    assert acts[0]["end"] == 20
    assert acts[1]["start"] == 21
    assert acts[1]["end"] == 50


def test_normalize_acts_fallback_from_story():
    acts = normalize_acts({"acts": []}, 50, "完整故事")
    assert len(acts) == 1
    assert acts[0]["start"] == 1
    assert acts[0]["end"] == 50


# ------------------------------------------------------------- AI review stage

def test_review_stage_adopts_invalid_rewrite_and_negative(llm):
    shots = [
        {"id": "01", "prompt": "1girl", "script": "脚本"},
        {"id": "02", "prompt": "1girl", "script": "脚本"},
    ]
    llm.add({"shots": [
        {"id": "01", "valid": True, "issues": [], "negative": "na"},
        {"id": "02", "valid": False, "issues": ["重复"],
         "prompt": "1girl, new beat", "negative": "n2",
         "script": "新脚本"},
    ]})
    from comfyui_generator.core.ai_review import review_stage_ai
    review_stage_ai(llm, "m", "continuity", shots, "前提",
                    batch_size=10, max_passes=1)
    assert shots[0]["negative"] == "na"
    assert shots[1]["prompt"] == "1girl, new beat"
    assert shots[1]["negative"] == "n2"
    assert shots[1]["script"] == "新脚本"


def test_review_clothing_stage_records_state(llm):
    shots = [
        {"id": "01", "prompt": "1girl, intact", "script": "脚本"},
    ]
    llm.add({"shots": [
        {"id": "01", "valid": False, "issues": ["服装矛盾"],
         "prompt": "1girl, torn pantyhose", "negative": "n",
         "clothing_state": "torn pantyhose"},
    ]})
    profiles = [CharacterProfile(key="char_01", gender="girl")]
    review_stage_ai(llm, "m", "clothing", shots, "前提",
                    batch_size=10, max_passes=1, profiles=profiles)
    assert shots[0]["prompt"] == "1girl, torn pantyhose"
    assert shots[0]["clothing_state"] == "torn pantyhose"
    assert shots[0]["clothing_details"]["char_01"] == "torn pantyhose"


# ---------------------------------------------------------------- plan outline

def test_plan_storyboard_outline_loops_until_filled(llm):
    llm.add({"shots": [
        {"id": "01", "outline": "a", "cast": "1girl solo"},
        {"id": "02", "outline": "b", "cast": "1girl solo"},
    ]})
    outline = plan_storyboard_outline(
        llm, "m", "剧情", 2, chunk=6)
    assert [item["outline"] for item in outline] == ["a", "b"]


def test_plan_story_spine_parses_acts(llm):
    llm.add({"acts": [
        {"title": "A", "summary": "first", "start": 1, "end": 25},
        {"title": "B", "summary": "second", "start": 26, "end": 50},
    ]})
    spine = plan_story_spine(llm, "m", "前提", 50)
    assert [item["phase"] for item in spine] == ["A", "B"]


# --------------------------------------------------------- run_all_reviews route

def test_run_all_reviews_calls_each_stage_and_adopts_negative(llm):
    shots = [{"id": "01", "prompt": "1girl"}]

    def scripted(model, messages, **kwargs):
        content = json.loads(messages[1]["content"])
        stage = content["review_stage"]
        return {"shots": [{
            "id": "01", "valid": True, "issues": [],
            "negative": "neg for %s" % stage}]}

    llm.dispatch[()] = scripted
    run_all_reviews(llm, "m", shots, "前提", batch_size=10, max_passes=1)
    assert len(llm.calls) == 3
    assert shots[0]["negative"] == "neg for %s" % REVIEW_STAGE_LABELS["pacing"]


def test_review_loop_rewrites_until_valid(llm):
    shots = [{"id": "01", "prompt": "1girl", "negative": ""}]
    responses = [
        {"shots": [{"id": "01", "valid": False, "issues": ["x"],
                    "negative": "n1", "prompt": "1girl, fixed1"}]},
        {"shots": [{"id": "01", "valid": True, "issues": [],
                        "negative": "n2"}]},
    ]
    for response in responses:
        llm.add(response)
    from comfyui_generator.core.ai_review import review_stage_ai
    review_stage_ai(llm, "m", "continuity", shots, "前提",
                    batch_size=10, max_passes=2)
    assert shots[0]["prompt"] == "1girl, fixed1"
    assert shots[0]["negative"] == "n2"
    assert len(llm.calls) == 2


# ---------------------------------------------------------------- finalize

def test_finalize_only_mechanically_normalizes():
    shots = [
        {"id": "01", "prompt": "1girl, 1girl , smile",
         "negative": "bad,  bad"},
    ]
    finalize_generated_story(shots, "前提")
    assert shots[0]["prompt"] == "1girl, smile"
    assert shots[0]["negative"] == "bad"


def test_finalize_is_idempotent():
    shots = [{"id": "01", "prompt": "1girl, smile", "negative": "bad"}]
    before = dict(shots[0])
    finalize_generated_story(shots, "前提")
    finalize_generated_story(shots, "前提")
    assert shots[0] == before


# ------------------------------------------------------------- full entry route

def test_generate_storyboard_full_pipeline_routes_reviews(llm):
    premise = "角色：SRAMerlin\n剧情：夜晚教室故事"
    options = make_options(shots=2, full_story=True, chunk=2)

    def responder(model, messages, **kwargs):
        schema = kwargs.get("schema")
        if schema is STORY_SCHEMA:
            return {"story": "完整剧情", "characters": [
                {"name": "SRAMerlin", "gender": "girl",
                 "appearance": "purple eyes", "initial_clothing": "black skirt"}]}
        if schema is ACT_PLAN_SCHEMA:
            return {"acts": [
                {"title": "Act", "summary": "全程", "start": 1, "end": 2}]}
        if schema is OUTLINE_SCHEMA:
            return {"shots": [
                {"id": "01", "outline": "大纲一", "cast": "1girl solo"},
                {"id": "02", "outline": "大纲二", "cast": "1girl solo"}]}
        if schema is TAG_SCHEMA:
            return {"shots": [
                {"id": "01", "prompt": "1girl, a", "negative": "na"},
                {"id": "02", "prompt": "1girl, b", "negative": "nb"}]}
        if schema is None:
            return {"shots": [
                {"id": "01", "valid": True, "issues": [],
                 "negative": "na"},
                {"id": "02", "valid": True, "issues": [],
                 "negative": "nb"}]}
        raise AssertionError("unexpected schema %r" % (schema,))

    llm.dispatch[()] = responder
    result = generate_storyboard(llm, premise, options)
    assert [s["prompt"] for s in result] == ["1girl, a", "1girl, b"]
    tag_calls = [c for c in llm.calls
                 if c[2].get("schema") is TAG_SCHEMA]
    assert tag_calls[0][0] == PROMPT_CONVERSION_FLASH_MODEL
