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
    PROMPT_CONVERSION_FLASH_MODEL,
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
    premise_from_json,
    raw_prompt,
    renumber_shots,
    shots_from_json,
    slugify,
    strip_male_profile_details,
    wardrobe_weight_policy,
)
from comfyui_generator.core.mechanical import normalize_prompt_text


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


def test_slugify_lowcases_and_collapses():
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

PREMISE_TWO_BEATS = (
    "角色：yixuan\n初始服装：black blazer, black pantyhose(1.2)\n"
    "剧情：\n1.女主独处\n2.男主加入做爱\n"
)


def _blueprint(total):
    return {"milestones": [
        {"index": 1, "title": "独处", "start": 1,
         "end": total - 1, "terminal": False},
        {"index": 2, "title": "做爱", "start": total,
         "end": total, "terminal": True},
    ]}


class _WaterfallClient:
    """Stateful fake for the three-stage waterfall; no text parsing."""

    def __init__(self, total):
        self.total = total
        self.calls: list[tuple] = []
        self._counts = {"outline": 0, "script": 0, "tags": 0}

    @staticmethod
    def _props(schema):
        try:
            return set(schema["properties"]["shots"]["items"]["properties"])
        except (KeyError, TypeError):
            return set()

    def chat_json(self, model, messages, **kwargs):
        from comfyui_generator.core.story_blueprint import BLUEPRINT_SCHEMA

        schema = kwargs.get("schema")
        self.calls.append((model, schema))
        if schema is BLUEPRINT_SCHEMA:
            return _blueprint(self.total)
        props = self._props(schema)
        if "milestone_index" in props:
            return self._outline()
        if "script" in props:
            return self._script()
        return self._tags()

    def _outline(self):
        n = self._counts["outline"] + 1
        self._counts["outline"] = n
        mi = 1 if (n < self.total or self.total == 1) else 2
        cast = "1girl solo" if n < self.total else "1girl, 1boy"
        return {"shots": [{
            "id": "%02d" % n, "milestone_index": mi,
            "outline": "大纲%d" % n, "cast": cast}]}

    def _script(self):
        n = self._counts["script"] + 1
        self._counts["script"] = n
        cast = "1girl solo" if n < self.total else "1girl, 1boy"
        text = "脚本%d" % n if n < self.total else "脚本%d：鸡巴插入阴道做爱" % n
        return {"shots": [{
            "id": "%02d" % n, "cast": cast, "script": text}]}

    def _tags(self):
        n = self._counts["tags"] + 1
        self._counts["tags"] = n
        if n < self.total:
            prompt = "1girl, solo, black blazer, black pantyhose"
        else:
            prompt = ("1girl, 1boy, nude male, faceless male, "
                      "black pantyhose, penis in pussy")
        return {"shots": [{
            "id": "%02d" % n, "prompt": prompt, "negative": "lowres"}]}



def test_generate_storyboard_runs_waterfall_and_is_ready():
    total = 2
    client = _WaterfallClient(total)
    options = make_options(shots=total, chunk=2)
    result = generate_storyboard(client, PREMISE_TWO_BEATS, options)
    assert [s["id"] for s in result] == ["01", "02"]
    assert all(s.get("ready") for s in result)
    assert "nude male" in result[1]["prompt"]


def test_generate_storyboard_early_returns_complete_shots(llm):
    existing = [{"id": "%02d" % i, "prompt": "1girl, smile",
                 "negative": "", "name": "n%d" % i} for i in range(1, 3)]
    options = make_options(shots=2)
    result = generate_storyboard(llm, PREMISE_TWO_BEATS, options, existing)
    assert llm.calls == []
    assert all(s.get("ready") for s in result)


class _SingleShotClient(_WaterfallClient):
    def chat_json(self, model, messages, **kwargs):
        from comfyui_generator.core.story_blueprint import BLUEPRINT_SCHEMA

        if kwargs.get("schema") is BLUEPRINT_SCHEMA:
            self.calls.append((model, kwargs["schema"]))
            return {"milestones": [{
                "index": 1, "title": "独处", "start": 1,
                "end": 1, "terminal": True}]}
        return super().chat_json(model, messages, **kwargs)

    def _tags(self):
        n = self._counts["tags"] + 1
        self._counts["tags"] = n
        return {"shots": [{
            "id": "01",
            "prompt": "1girl, solo, black blazer, black pantyhose",
            "negative": "lowres"}]}


def test_tag_conversion_uses_flash_model():
    client = _SingleShotClient(1)
    options = make_options(shots=1)
    generate_storyboard(client, "剧情：\n1.独处\n", options)
    tag_models = {m for m, s in client.calls
                  if _WaterfallClient._props(s)
                  == {"id", "prompt", "negative"}}
    assert tag_models == {PROMPT_CONVERSION_FLASH_MODEL}


def test_only_failed_shots_are_marked_not_ready():
    from comfyui_generator.core.stages import _convert_tags

    scripts = [
        {"id": "01", "name": "a", "script": "脚本一", "cast": "1girl solo"},
        {"id": "02", "name": "b", "script": "脚本二", "cast": "1girl solo"},
        {"id": "03", "name": "c", "script": "脚本三", "cast": "1girl solo"},
    ]

    class Client:
        def chat_json(self, model, messages, **kwargs):
            text = messages[-1]["content"]
            import re
            current = re.search(r"id\s*=\s*(\d{2})", text).group(1)
            base = "1girl, solo, exactly the same long tag set, sitting"
            if current == "01":
                prompt = base
            elif current == "02":
                # byte-identical to shot 01 -> adjacent_duplicate
                prompt = base
            else:
                prompt = "1girl, solo, a clearly different new action, standing"
            return {"shots": [{
                "id": current, "prompt": prompt, "negative": "x"}]}

    result = _convert_tags(
        Client(), "m", "剧情：x", 3, setting="", strip_appearance=False,
        scripts=scripts, style_positive="", timeout=30.0, log=lambda *_: None)
    readiness = {s["id"]: s["ready"] for s in result}
    assert readiness == {"01": True, "02": False, "03": True}


def test_failed_tag_conversion_keeps_last_candidate_and_findings():
    from comfyui_generator.core.stages import _convert_tags

    scripts = [{"id": "01", "name": "a", "script": "脚本一", "cast": "1boy"}]

    class Client:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [{
                "id": "01", "prompt": "1girl, 1boy, clothes", "negative": "x"}]}

    result = _convert_tags(
        Client(), "m", "剧情：x", 1, setting="", strip_appearance=False,
        scripts=scripts, style_positive="", timeout=30.0, log=lambda *_: None)
    assert result[0]["ready"] is False
    assert result[0]["prompt"] == "1girl, 1boy, clothes"
    assert {finding["kind"] for finding in result[0]["findings"]} >= {
        "male_nude", "male_faceless"}


def test_repair_carries_all_active_constraints():
    from comfyui_generator.core.stages import repair_tagged_shots

    prev_script = "previous locked script"
    locked_script = "locked next script"
    prev_prompt = "1girl, discarded blazer on chair, sitting"
    shots = [
        {"id": "01", "name": "a", "cast": "1girl",
         "script": prev_script, "outline": prev_script,
         "prompt": prev_prompt, "ready": True, "findings": []},
        {"id": "02", "name": "b", "cast": "1girl",
         "script": locked_script, "outline": locked_script,
         "prompt": "1girl, black blazer, blazer unbuttoned, sitting",
         "ready": False,
         "findings": [{"kind": "clothing:reworn", "message": "blazer：old", "correct": "off"}]},
    ]

    class Client:
        prompts = []

        def chat_json(self, model, messages, **kwargs):
            text = messages[-1]["content"]
            self.prompts.append(text)
            if len(self.prompts) <= 2:
                prompt = "1girl, discarded blazer on chair, sitting"
            else:
                prompt = "1girl, discarded blazer on chair, standing"
            return {"shots": [{"id": "02", "prompt": prompt, "negative": ""}]}

    client = Client()
    result = repair_tagged_shots(
        client, "m", shots, "剧情：x", timeout=30.0, log=lambda *_: None)
    constraints = client.prompts[2]
    assert any(word in constraints for word in ("不得回退", "resolved", "已解决"))
    assert "与上一镜" in constraints
    assert result[1]["ready"] is True
    assert result[1]["prompt"].endswith("standing")


def test_revalidate_tagged_shots_updates_status():
    from comfyui_generator.core.stages import revalidate_tagged_shots

    shots = [
        {"id": "01", "prompt": "1girl, sitting"},
        {"id": "02", "prompt": "1girl, 1boy, clothes"},
    ]
    result = revalidate_tagged_shots(shots, "剧情：x")
    assert result[0]["ready"] is True
    assert result[1]["ready"] is False
    assert {f["kind"] for f in result[1]["findings"]} >= {
        "male_nude", "male_faceless"}


def test_repair_tagged_shots_only_rewrites_not_ready_shots():
    from comfyui_generator.core.stages import repair_tagged_shots

    shots = [
        {"id": "01", "name": "a", "script": "脚本一", "cast": "1girl",
         "prompt": "1girl, old", "ready": True, "findings": []},
        {"id": "02", "name": "b", "script": "脚本二", "cast": "1girl",
         "prompt": "bad", "ready": False, "findings": [{"kind": "x"}]},
    ]

    class Client:
        calls = 0

        def chat_json(self, model, messages, **kwargs):
            self.calls += 1
            return {"shots": [{
                "id": "02", "prompt": "1girl, repaired", "negative": "x"}]}

    client = Client()
    result = repair_tagged_shots(
        client, "m", shots, "剧情：x", timeout=30.0, log=lambda *_: None)
    assert client.calls == 1
    assert result[0]["prompt"] == "1girl, old"
    assert result[1]["prompt"] == "1girl, repaired"
    assert result[1]["ready"] is True
