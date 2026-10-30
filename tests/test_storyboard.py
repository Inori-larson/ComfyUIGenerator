import pytest

from comfyui_generator.core.storyboard import (
    OUTLINE_SYSTEM,
    STORY_SYSTEM,
    _clothing_key,
    SCRIPT_SYSTEM,
    TAG_SYSTEM,
    apply_character_state,
    apply_story_state,
    build_outline_messages,
    build_script_messages,
    build_tag_messages,
    character_states_for_beats,
    clothing_states_for_beats,
    extract_premise_beats,
    filter_locked_appearance,
    normalize_character_profiles,
    parse_character_profiles,
    present_character_profiles,
    normalize_scripts,
    normalize_tagged,
    premise_from_json,
    scene_states_for_beats,
    shots_from_json,
    slugify,
    StoryboardOptions,
)


def test_tagged_shots_use_the_generated_script_as_outline():
    script = "身份外貌：仪玄。服装：黑色西装。场景：卧室。"
    scripts = normalize_scripts({"shots": [{
        "id": "01", "name": "a", "script": script,
    }]}, 1, "fallback")
    tagged = normalize_tagged({"shots": [
        {"id": "01", "prompt": "1girl, standing"}]}, scripts)
    assert tagged[0]["outline"] == script


def test_prompts_do_not_depend_on_reference_tags():
    for prompt in (OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "参考标签" not in prompt
    assert "最多 100" in TAG_SYSTEM
    assert "禁止 camera" in TAG_SYSTEM
    assert "不生成质量" in TAG_SYSTEM
    for prompt in (STORY_SYSTEM, OUTLINE_SYSTEM, SCRIPT_SYSTEM, TAG_SYSTEM):
        assert "撕破连裤袜" in prompt


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
    assert states[1][girl.key] == set()
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
    for shot in shots:
        assert "silver hair" in shot["prompt"]
        assert "black hair" in shot["prompt"]
    assert "white shirt" in shots[0]["prompt"]
    assert "white shirt" in shots[1]["prompt"]
    assert "white shirt" not in shots[2]["prompt"]
    assert "black dress" not in shots[1]["prompt"]
    assert "completely nude" not in shots[1]["prompt"]
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


def test_long_story_is_split_into_acts_and_keeps_global_ids():
    from comfyui_generator.core.storyboard import generate_storyboard

    class LongFake:
        def chat_json(self, model, messages, **kwargs):
            return {"shots": [
                {"id": "%02d" % index, "name": "s%02d" % index,
                 "script": "脚本", "prompt": "1girl, solo",
                 "outline": "镜头", "cast": "1girl solo"}
                for index in range(1, 7)
            ]}

    shots = generate_storyboard(
        LongFake(), "剧情：她回家，自慰，被我看到，做爱",
        StoryboardOptions(model="test-model", shots=31, chunk=3,
                          log=lambda _message: None))
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
