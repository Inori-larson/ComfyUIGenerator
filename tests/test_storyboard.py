import pytest

from comfyui_generator.core.storyboard import (
    OUTLINE_SYSTEM,
    _clothing_key,
    SCRIPT_SYSTEM,
    TAG_SYSTEM,
    apply_cast_state,
    apply_phase_terms,
    apply_story_state,
    build_outline_messages,
    build_script_messages,
    build_story_spine,
    build_tag_messages,
    clean_prompt,
    clothing_states_for_beats,
    detect_cast,
    enforce_beat_terms,
    extract_premise_beats,
    normalize,
    normalize_prompt_tags,
    normalize_scripts,
    normalize_shot_terms,
    normalize_tagged,
    premise_from_json,
    scene_states_for_beats,
    shots_from_json,
    slugify,
    strip_generation_quality,
    strip_stage1_identity,
    summarize_clothing,
    summarize_shot_state,
    StoryboardOptions,
)


def test_normalize_renumbers_and_dedupes_names():
    raw = {"shots": [
        {"name": "shot", "prompt": "wide shot, standing"},
        {"name": "shot", "prompt": "close-up, smiling"},
        {"name": "", "prompt": "  "},
        {"name": "third", "prompt": "medium shot, running"},
    ]}
    shots = normalize(raw, 10, "fallback")
    assert [shot["id"] for shot in shots] == ["01", "02", "03"]
    assert shots[0]["name"] == "shot"
    assert shots[1]["name"] == "shot_2"
    assert shots[2]["name"] == "third"


def test_normalize_combines_structured_prompt_fields():
    raw = {"shots": [{
        "name": "a", "brief": "第一镜大纲",
        "clothing": "black blazer", "body": "hands", "pose": "standing",
        "expression": "calm", "scene": "room", "camera": "full body",
        "lighting": "soft lighting", "prompt": "looking at viewer",
    }]}
    shot = normalize(raw, 1, "fallback")[0]
    assert shot["outline"] == "第一镜大纲"
    assert shot["prompt"] == (
        "black blazer, hands, standing, calm, room, full body, "
        "soft lighting, looking at viewer")


def test_stage1_strips_guessed_identity_but_keeps_reference_accessories():
    prompt = ("black hair, yellow eyes, long hair, hairclip, yixuan, glasses, "
              "cyberpunk_girl, instrument yuan")
    assert strip_stage1_identity(prompt, "仪玄") == "hairclip, yixuan"
    assert "white hair" in strip_stage1_identity("white hair, yixuan", "white hair 仪玄")


def test_normalize_keeps_script_field():
    raw = {"shots": [{"prompt": "standing", "script": "身份外貌：仪玄；服装：..."}]}
    assert normalize(raw, 1, "fallback")[0]["script"].startswith("身份外貌")


def test_cast_detection_and_solo_cleanup():
    assert detect_cast("仪玄独自坐在沙发上") == ["1girl", "solo"]
    assert detect_cast("仪玄和我一起坐在沙发上") == ["1girl", "1boy"]
    result = apply_cast_state(
        "people, 1boy, black blazer, 1girl, solo",
        "仪玄独自坐在沙发上，黑发垂落")
    tags = [tag.strip() for tag in result.split(",")]
    assert "people" not in tags
    assert "1boy" not in tags
    assert "1girl" in tags
    assert "solo" in tags


def test_strip_generation_quality_keeps_scene_and_clothing():
    assert strip_generation_quality(
        "masterpiece, best quality, anime style, black blazer, smile"
    ) == "black blazer, smile"


def test_tagged_shots_use_the_generated_script_as_outline():
    script = "身份外貌：仪玄。服装：黑色西装。场景：卧室。"
    scripts = normalize_scripts({"shots": [{
        "id": "01", "name": "a", "script": script,
    }]}, 1, "fallback")
    tagged = normalize_tagged({"shots": [
        {"id": "01", "prompt": "1girl, standing"}]}, scripts)
    assert tagged[0]["outline"] == script


def test_normalize_start_index_and_existing_names():
    raw = {"shots": [{"name": "a", "prompt": "x"}, {"name": "b", "prompt": "y"}]}
    shots = normalize(raw, 2, "fallback", start=5, used_names=["a"])
    assert [shot["id"] for shot in shots] == ["05", "06"]
    assert shots[0]["name"] == "a_2"


def test_prompts_do_not_depend_on_reference_tags():
    for prompt in (OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "参考标签" not in prompt
    assert "最多 100" in TAG_SYSTEM
    assert "禁止 camera" in TAG_SYSTEM
    assert "不生成质量" in TAG_SYSTEM


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


def test_strip_stage1_identity_removes_body_identity_features():
    assert strip_stage1_identity(
        "black hair, large breasts, wide hips, black blazer", ""
    ) == "black blazer"


def test_summarize_clothing_tracks_worn_and_exposed_parts():
    state = summarize_clothing({
        "prompt": "black pantyhose half on, black platform heels, topless, pussy"})
    assert "wearing: black pantyhose" in state
    assert "black platform heels" in state
    assert "exposed: topless" in state
    assert "pussy" in state


def test_summarize_shot_state_includes_pose_and_camera():
    state = summarize_shot_state({
        "clothing": "black pantyhose, topless",
        "pose": "standing, hands on hips",
        "camera": "full body, from side",
        "outline": "站在床边",
    })
    assert "wearing: black pantyhose" in state
    assert "exposed: topless" in state
    assert "pose: standing" in state
    assert "camera: full body" in state
    assert "last scene: 站在床边" in state


def test_normalize_shot_terms_replaces_euphemisms():
    prompt = ("hand on private parts, finger in vagina, quick hand movements, "
              "love liquid, private parts")
    tags = [tag.strip() for tag in normalize_shot_terms(prompt).split(",")]
    assert "hand on pussy" in tags
    assert "finger in pussy" in tags
    assert "masturbation" in tags
    assert "pussy juice" in tags
    assert "pussy" in tags


def test_story_spine_allocates_discovery_seduction_and_sex():
    premise = ("角色：仪玄\n初始服装：black blazer\n大场景：家里\n剧情：\n"
               "仪玄回到家寂寞难耐，自慰，不小心被我发现了，然后开始勾引我，最后我两一起做爱\n"
               "其它：夜晚")
    spine = build_story_spine(premise, 30)
    phases = [item["phase"] for item in spine]
    assert phases == ["story", "solo", "discovery", "seduction", "sex"]
    assert spine[2]["cast"] == "1girl 1boy"
    assert spine[-1]["cast"] == "1girl 1boy"
    assert spine[-1]["end"] == 30
    assert spine[-1]["end"] - spine[-1]["start"] + 1 >= 14


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
        "completely nude", {"hairclip"}, ["bedroom", "bed"])
    tags = [tag.strip() for tag in result.split(",")]
    for item in ("back-seamed legwear", "black tight top", "black lace lingerie"):
        assert item not in tags
    assert "completely nude" in tags


def test_phase_terms_inject_explicit_sex_and_keep_erotic_clothing():
    result = apply_phase_terms(
        "1girl, 1boy, black blazer, black lace lingerie, black pantyhose, "
        "black platform heels, undressing, hugging",
        "sex", "1girl 1boy")
    tags = [tag.strip() for tag in result.split(",")]
    assert "sex" in tags
    assert "vaginal" in tags
    assert "penis" in tags
    assert "penetration" in tags
    assert "black blazer" not in tags
    assert "black lace lingerie" in tags
    assert "black pantyhose" in tags
    assert "black platform heels" in tags
    assert "completely nude" not in tags
    assert "undressing" not in tags
    assert "hugging" not in tags


def test_non_sex_phase_removes_explicit_sex_pose_tags():
    result = apply_phase_terms(
        "1girl, solo, doggy style, sex, vaginal, sitting on bed",
        "solo", "1girl solo")
    tags = [tag.strip() for tag in result.split(",")]
    assert "doggy style" not in tags
    assert "sex" not in tags
    assert "vaginal" not in tags


def test_normalize_prompt_tags_dedupes_synonyms_and_camera_size():
    result = normalize_prompt_tags(
        "closeup, close-up, side view, from side, high angle, from above, "
        "full body, medium shot, shadow, shadow")
    tags = [tag.strip() for tag in result.split(",")]
    assert tags == ["close-up", "from side", "from above", "full body", "shadow"]


def test_normalize_prompt_tags_resolves_invented_clothing_and_state_conflicts():
    result = normalize_prompt_tags(
        "brooch, flower brooch, hairpin, hairclip, black romper, "
        "frilled black leotard, peter pan collar, puritan collar, "
        "fully clothed, topless, pussy, completely nude, black pantyhose")
    tags = [tag.strip() for tag in result.split(",")]
    assert "brooch" not in tags
    assert "hairpin" not in tags
    assert "black romper" not in tags
    assert "peter pan collar" not in tags
    assert "fully clothed" not in tags
    assert "completely nude" not in tags
    assert "flower brooch" in tags
    assert "hairclip" in tags
    assert "frilled black leotard" in tags
    assert "puritan collar" in tags
    assert "black pantyhose" in tags


def test_enforce_beat_terms_adds_nude_and_removes_clothing():
    prompt = ("black pantyhose, black platform heels, standing, calm, "
              "full body")
    result = enforce_beat_terms(prompt, "black pantyhose 与高跟鞋全部脱去，全裸")
    tags = [tag.strip() for tag in result.split(",")]
    assert "completely nude" in tags
    assert "pussy" in tags
    assert "black pantyhose" not in tags
    assert "black platform heels" not in tags


def test_enforce_beat_does_not_pull_pantyhose_for_leotard_only():
    result = enforce_beat_terms(
        "black pantyhose, black platform heels, standing",
        "手指拉下 leotard 胸口，上半拉到腰下，黑丝与高跟鞋还在")
    tags = [tag.strip() for tag in result.split(",")]
    assert "clothes pull" in tags
    assert "pantyhose pull" not in tags


def test_enforce_beat_marks_pantyhose_transition():
    result = enforce_beat_terms(
        "black pantyhose, black platform heels, standing",
        "双手勾住 black pantyhose 腰边，往下褪到大腿中部，私处露出")
    tags = [tag.strip() for tag in result.split(",")]
    assert "pantyhose pull" in tags
    assert "undressing" in tags
    assert "thighs" in tags
    assert "pussy" in tags


def test_enforce_beat_does_not_pull_remaining_pantyhose():
    result = enforce_beat_terms(
        "hands on hips, black pantyhose, black platform heels",
        "把 leotard 从腿部完全脱下，只剩 black pantyhose 与 black platform heels")
    tags = [tag.strip() for tag in result.split(",")]
    assert "clothes pull" in tags
    assert "pantyhose pull" not in tags
    assert "hands on hips" not in tags


def test_enforce_beat_fixes_afterglow_pose():
    result = enforce_beat_terms(
        "lying down, legs spread, masturbation, intense expression",
        "高潮余波后，用被子盖住下半身，上身仍裸露，靠在床头，轻松笑容")
    tags = [tag.strip() for tag in result.split(",")]
    assert "sitting" in tags
    assert "lying down" not in tags
    assert "legs spread" not in tags
    assert "masturbation" not in tags
    assert "topless" in tags


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


def test_apply_story_state_clears_stale_clothing_and_scene():
    result = apply_story_state(
        "black blazer, frilled black leotard, black pantyhose, black platform heels, "
        "white background, simple background, 3d, upper body covered, undressing, "
        "clothes pull, pussy, nipples, room, sofa",
        "全裸站在床边",
        {"hairclip", "puritan collar", "flower brooch"},
        ["bedroom", "bed", "indoors", "double bed"],
    )
    tags = [tag.strip() for tag in result.split(",")]
    assert "black blazer" not in tags
    assert "frilled black leotard" not in tags
    assert "black pantyhose" not in tags
    assert "white background" not in tags
    assert "simple background" not in tags
    assert "3d" not in tags
    assert "upper body covered" not in tags
    assert "undressing" not in tags
    assert "clothes pull" not in tags
    assert "completely nude" in tags
    assert "pussy" in tags
    assert "bedroom" in tags
    assert "sofa" not in tags


def test_apply_story_state_covered_lower_is_topless_not_full_nude():
    result = apply_story_state(
        "lying on side, legs spread, pussy, pussy juice",
        "用被子盖住下半身，上身仍裸露，靠在床头",
        {"hairclip", "puritan collar"},
        ["bedroom", "bed", "indoors"],
    )
    tags = [tag.strip() for tag in result.split(",")]
    assert "completely nude" not in tags
    assert "topless" in tags
    assert "pussy" not in tags
    assert "sitting" in tags
    assert "lying" not in tags
    assert "lying on side" not in tags


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


def test_generic_nsfw_rule_expansion():
    result = enforce_beat_terms(
        "nude, sitting",
        "被绳子捆绑双手，蒙眼，使用跳蛋，随后口交并潮吹")
    tags = [tag.strip() for tag in result.split(",")]
    for expected in ("bondage", "bound", "blindfold", "sex toy", "vibrator",
                     "oral", "pussy juice"):
        assert expected in tags


def test_generic_pose_expression_camera_lighting_body_rules():
    result = enforce_beat_terms(
        "1girl, solo",
        "站在窗边，黄昏逆光，半闭眼，微微张嘴，脸红，"
        "镜头从下往上拍，全身照，揉捏乳头，小穴流出爱液")
    tags = [tag.strip() for tag in result.split(",")]
    for expected in ("standing", "sunset", "backlighting", "half-closed eyes",
                     "parted lips", "blush", "from below", "full body",
                     "nipples", "pussy", "pussy juice"):
        assert expected in tags


def test_generic_maid_outfit_and_hospital_scene():
    premise = "初始服装：maid outfit, white apron, black stockings, black heels"
    states = clothing_states_for_beats(premise, [
        "01. 在医院病房穿着女仆装",
        "02. 脱下 maid outfit",
    ])
    assert "maid outfit" in states[0]
    assert "maid outfit" not in states[1]
    assert scene_states_for_beats(["医院病房"])[0][0] == "hospital"


def test_clean_and_slug():
    assert clean_prompt("  prompt: wide shot,\n standing.  ") == "wide shot, standing"
    assert clean_prompt("looking_at_camera, holding_camera, black_pantyhose, close-up") == (
        "looking at viewer, black pantyhose, close-up")
    assert slugify("雨夜, girl!") == "girl"
    assert slugify("!!!", "fallback") == "fallback"


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


def test_generate_bounds_output_tokens_and_timeout():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    generate_storyboard(client, "01. one\n02. two",
                        StoryboardOptions(model="test-model", shots=2, chunk=2))
    kwargs = client.calls[0][1]
    assert 1536 <= kwargs["num_predict"] <= 8192
    assert kwargs["timeout"] == 240.0


def test_generate_with_initial_shot_keeps_it():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "anchor", "prompt": "wide shot, standing"}]
    options = StoryboardOptions(model="test-model", shots=3)
    shots = generate_storyboard(client, "a walk", options, initial_shots=initial)
    assert len(shots) == 3
    assert shots[0] == initial[0]
    assert [shot["id"] for shot in shots] == ["01", "02", "03"]
    assert len(client.calls) == 3
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


def test_generate_with_initial_and_no_extra_shots_does_not_call_model():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "only", "prompt": "wide shot"}]
    shots = generate_storyboard(client, "x", StoryboardOptions(model="test-model", shots=1),
                                initial_shots=initial)
    assert shots == initial
    assert client.calls == []
