import pytest

from comfyui_generator.core.workflow import (
    build_workflow,
    compose_pass_prompts,
    compose_prompts,
    expand_wildcards,
    is_double_shot,
    lora_chain,
    prompt_groups,
    split_prompt_groups,
    stage_for_node,
    _upscale_model_scale,
)


@pytest.fixture
def cfg():
    return {
        "loader": "checkpoint",
        "model": "WAI\\waiIllustriousSDXL_v170.safetensors",
        "clip_skip": -2,
        "prefix": "anime_story/test",
        "loras": [
            {"name": "角色\\绝区零\\仪玄\\Char-ZZZ-Yixuan-V2-IL.safetensors", "strength": 0.9},
            {"name": "AnimeScreencap\\anime_screencap-IllustriousV2.safetensors", "strength": 0.2},
        ],
        "character": {"tags": "yixuan, solo", "use_ipadapter": True,
                      "ipadapter": {"reference": "anime_story/ref.png", "weight": 0.6}},
        "style": {"positive": "masterpiece", "negative": "bad quality",
                  "suffix": "sunny"},
        "style_ref": {"enabled": True, "image": "anime_story/style.png", "weight": 0.8},
        "settings": {
            "width": 832, "height": 1216, "steps": 12, "cfg": 5,
            "sampler": "euler_ancestral", "scheduler": "normal", "base_seed": 100,
            "hires": {"enabled": True, "scale": 1.5, "steps": 8, "denoise": 0.4,
                      "upscale_model": "RealESRGAN_x4plus_anime_6B.pth", "model_scale": 4.0},
        },
        "detailers": [
            {"model": "bbox/face_yolov8n.pt", "prompt": "detailed face", "denoise": 0.3, "guide_size": 512},
            {"model": "bbox/hand_yolov8n.pt", "denoise": 0.4, "guide_size": 768},
        ],
        "wildcards": {"enabled": False, "dir": ""},
        "shots": [],
    }


def test_compose_prompts_order(cfg):
    shot = {"prompt": "wide shot, standing", "character_tags": "extra char tag"}
    positive, negative = compose_prompts(cfg, shot)
    assert positive.startswith("masterpiece")
    assert "extra char tag" in positive
    assert "wide shot, standing" in positive
    assert positive.endswith("sunny")
    assert negative.startswith("bad quality")
    assert "multiple boys" in negative
    assert "multiple girls" in negative


def test_compose_prompts_does_not_inject_hardcoded_scene_anchor(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, standing",
        "scene": "beach, ocean, sand, outdoors",
    })
    assert "beach" not in positive.split(",")
    assert "ocean" not in positive.split(",")
    assert "sand" not in positive.split(",")


def test_compose_prompts_keeps_ai_scene_without_hardcoded_filter(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, bedroom, soft lighting",
        "scene": "beach, ocean, sand, outdoors",
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "bedroom" in tags
    assert "beach" not in tags


def test_compose_prompts_keeps_ai_outdoor_scene_without_hardcoded_filter(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, beach, ocean, sunlight",
        "scene": "bedroom, bed, indoors",
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "beach" in tags
    assert "bedroom" not in tags


def test_compose_prompts_locks_hair_color(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, standing",
        "character_tags": "red_hair, red_eyes",
    })
    assert "(red_hair:1.2)" in positive
    assert "(red_eyes:1.2)" in positive
    assert "different hair color" in negative


def test_compose_prompts_locks_any_hair_color(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, standing",
        "character_tags": "teal_hair, two-tone_hair, heterochromia",
    })
    assert "(teal_hair:1.2)" in positive
    assert "(two-tone_hair:1.2)" in positive
    assert "(heterochromia:1.2)" in positive
    assert "different hair color" in negative


def test_compose_prompts_does_not_add_detailed_penis_for_solo_female(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, pussy, wet pussy",
        "cast": "1girl solo",
    })
    assert "detailed pussy" in positive
    assert "detailed penis" not in positive


def test_compose_prompts_adds_detailed_penis_when_male_present(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, nude male, pussy, penis in pussy",
        "cast": "1girl 1boy",
    })
    assert "detailed penis" in positive
    assert "detailed pussy" in positive


def test_compose_prompts_blocks_damage_when_script_has_none(cfg):
    _, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, black pantyhose",
        "script": "她穿着完整丝袜站在沙滩上。",
    })
    assert "torn pantyhose" in negative
    _, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, torn pantyhose",
        "script": "她的丝袜被撕破。",
    })
    assert "torn pantyhose" not in negative
    _, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, torn pantyhose, sitting",
        "script": "她坐在长椅上休息。",
    })
    assert "torn pantyhose" not in negative


def test_compose_prompts_blocks_intact_legwear_when_half_off(cfg):
    _, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, black pantyhose around thighs, "
                  "upper thighs bare",
    })
    assert "pantyhose around waist" in negative
    assert "crotch covered by pantyhose" in negative


def test_compose_prompts_drops_full_legwear_when_prompt_has_half_off(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, (black pantyhose around thighs:1.2), "
                  "pantyhose pulled down, upper thighs bare, "
                  "(bra:1.2), (panties:1.2)",
        "clothing": "(black pantyhose:1.2), (bra:1.2), (panties:1.2)",
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "(black pantyhose:1.2)" not in tags
    assert any("black pantyhose around thighs" in tag for tag in tags)
    assert "(bra:1.2)" in tags
    assert "(panties:1.2)" in tags


def test_compose_prompts_keeps_colored_base_for_generic_half_off_state(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, black bra, bra strap pulled down, "
                  "black lace panties, panties aside",
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "black bra" in tags
    assert "black lace panties" in tags
    assert "bra strap pulled down" in tags
    assert "panties aside" in tags


def test_compose_prompts_blocks_second_panties_when_legwear_is_pulled_down(cfg):
    _, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, black lace panties, pantyhose around ankles",
    })
    assert "two panties" in negative
    assert "panties around ankle" in negative


def test_compose_prompts_boosts_all_clothing_tags(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, beach",
        "clothing": "uniform, black bra",
    })
    assert "(uniform:1.15)" in positive
    assert "(black bra:1.15)" in positive


def test_compose_prompts_places_current_clothing_before_scene(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, solo, beach, standing",
        "clothing": "black pantyhose, black bra",
    })
    assert positive.index("black pantyhose") < positive.index("beach")
    assert positive.index("black bra") < positive.index("beach")


def test_compose_prompts_does_not_add_explicit_body_tags_when_clothed(cfg):
    cfg["body"] = {"tags": "pussy, pussy juice"}
    positive, _ = compose_prompts(
        cfg, {"prompt": "1girl, solo, standing, uniform, pantyhose"})
    assert "pussy" not in positive
    assert "pussy juice" not in positive


def test_compose_prompts_adds_body_tags_when_exposed(cfg):
    cfg["body"] = {"tags": "pussy, pussy juice"}
    positive, _ = compose_prompts(
        cfg, {"prompt": "1girl, solo, pantyhose pulled down, torn pantyhose"})
    assert "pussy" in positive
    assert "pussy juice" not in positive


def test_compose_prompts_adds_fluid_tags_only_with_fluid_context(cfg):
    cfg["body"] = {"tags": "pussy, pussy juice"}
    positive, _ = compose_prompts(
        cfg, {"prompt": "1girl, solo, nude, masturbation, pussy juice"})
    assert "pussy" in positive
    assert "pussy juice" in positive


def test_compose_prompts_includes_body_tags(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": "pussy, nude"}
    positive, _ = compose_prompts(cfg, {"prompt": "nude, park"})
    assert "pussy" in positive
    assert "nude" in positive


def test_compose_prompts_keeps_native_body_tags_without_filtering(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["negative"] = "bad quality, censored"
    cfg["body"] = {"tags": "pussy, nude, close-up, censored, breasts"}
    shot = {"prompt": "nude, black blazer, frilled black leotard, black pantyhose, full_body"}
    positive, _ = compose_prompts(cfg, shot)
    tags = [tag.strip() for tag in positive.split(",")]
    for expected in ("pussy", "nude", "close-up", "censored", "breasts",
                     "black blazer", "frilled black leotard", "black pantyhose"):
        assert expected in tags


def test_compose_prompts_keeps_native_body_tags_when_nude(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": "pussy, nude, close-up"}
    positive, _ = compose_prompts(cfg, {"prompt": "nude, full_body"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "pussy" in tags
    assert "nude" in tags
    assert "close-up" in tags


def test_compose_prompts_does_not_filter_negative_words(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["negative"] = "bad quality, censored"
    cfg["body"] = {"tags": "censored, pussy"}
    positive, _ = compose_prompts(cfg, {"prompt": "nude"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "censored" in tags
    assert "pussy" in tags


def test_compose_prompts_keeps_model_camera_tags(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": ""}
    positive, _ = compose_prompts(
        cfg, {"prompt": "looking_at_camera, holding_camera, black_pantyhose, from_below"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "looking_at_camera" in tags
    assert "holding_camera" in tags
    assert "black_pantyhose" in tags
    assert "from_below" in tags


def test_body_loras_are_selected_per_shot(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "身体部位\\AnimePussyV1.safetensors", "strength": 0.9,
         "scope": "body", "triggers": ["pussy"]},
        {"name": "身体部位\\pussy juice_illustrious_V1.0.safetensors", "strength": 0.9,
         "scope": "body", "triggers": ["pussy juice"]},
    ]
    clothed = {"prompt": "black blazer, frilled black leotard, full_body"}
    nude = {"prompt": "nude, full_body"}
    juice = {"prompt": "nude, pussy juice"}

    clothed_names = [item["name"] for item in lora_chain(cfg, clothed)]
    assert not any("身体部位" in name for name in clothed_names)
    nude_names = [item["name"] for item in lora_chain(cfg, nude)]
    assert "身体部位\\AnimePussyV1.safetensors" in nude_names
    assert "身体部位\\pussy juice_illustrious_V1.0.safetensors" not in nude_names
    juice_names = [item["name"] for item in lora_chain(cfg, juice)]
    assert "身体部位\\pussy juice_illustrious_V1.0.safetensors" in juice_names

    clothed_tags = [tag.strip() for tag in compose_prompts(cfg, clothed)[0].split(",")]
    nude_tags = [tag.strip() for tag in compose_prompts(cfg, nude)[0].split(",")]
    juice_tags = [tag.strip() for tag in compose_prompts(cfg, juice)[0].split(",")]
    assert "pussy" not in clothed_tags
    assert "pussy juice" not in clothed_tags
    assert "pussy" in nude_tags
    assert "pussy juice" not in nude_tags
    assert "pussy" in juice_tags
    assert "pussy juice" in juice_tags

    euphemism = {"prompt": "finger in vagina, quick hand movements"}
    euphemism_names = [item["name"] for item in lora_chain(cfg, euphemism)]
    assert "身体部位\\AnimePussyV1.safetensors" in euphemism_names
    assert "pussy" in [tag.strip() for tag in compose_prompts(cfg, euphemism)[0].split(",")]


def test_second_pass_can_skip_character_lora(cfg):
    cfg = dict(cfg)
    shot = {"prompt": "1boy, jeans", "skip_character_loras": True}
    names = [item["name"] for item in lora_chain(cfg, shot)]
    assert not any("角色" in name for name in names)
    assert any("anime_screencap" in name for name in names)


def test_action_loras_are_selected_per_shot(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "actions\\MissionaryV1.safetensors", "strength": 0.8,
         "scope": "action", "triggers": ["missionary"]},
    ]
    idle = {"prompt": "standing, smile"}
    action = {"prompt": "lying on back, legs up, sex"}

    assert not any("actions\\" in item["name"] for item in lora_chain(cfg, idle))
    assert any("actions\\" in item["name"] for item in lora_chain(cfg, action))
    tags = [tag.strip() for tag in compose_prompts(cfg, action)[0].split(",")]
    assert "missionary" in tags


def test_clothing_loras_are_selected_per_shot(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "outfits\\SchoolUniformV1.safetensors", "strength": 0.8,
         "scope": "clothing", "triggers": ["school uniform"]},
    ]
    idle = {"prompt": "standing, smile"}
    clothed = {"prompt": "serafuku, pleated skirt"}

    assert not any("outfits\\" in item["name"] for item in lora_chain(cfg, idle))
    assert any("outfits\\" in item["name"] for item in lora_chain(cfg, clothed))
    positive = compose_prompts(cfg, clothed)[0]
    assert "(school uniform:1.15)" in positive


def test_clothing_lora_uses_reference_tags_when_trigger_is_opaque(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "clothing\\AF_DarkDesire_ILL.safetensors", "strength": 0.8,
         "scope": "clothing", "triggers": ["af_darkdesire"],
         "reference": ["af_darkdesire", "lingerie", "panties", "high heels",
                       "standing", "1girl"]},
    ]
    clothed = {"prompt": "lingerie, panties, high heels"}
    idle = {"prompt": "standing, smile"}
    assert any("AF_DarkDesire" in item["name"] for item in lora_chain(cfg, clothed))
    assert not any("AF_DarkDesire" in item["name"] for item in lora_chain(cfg, idle))
    positive = compose_prompts(cfg, clothed)[0]
    assert "(af_darkdesire:1.15)" in positive


def test_action_lora_uses_filename_or_reference_when_triggers_are_empty(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "actions\\16_pussygrip_illus01_1a.safetensors", "strength": 0.8,
         "scope": "action", "triggers": [], "reference": []},
        {"name": "actions\\after-sex-fellatio-v2.safetensors", "strength": 0.8,
         "scope": "action", "triggers": [],
         "reference": ["after sex fellatio", "nude", "penis", "pussy"]},
    ]
    grip = {"prompt": "pussy, spread legs"}
    oral = {"prompt": "fellatio, cum"}
    idle = {"prompt": "standing, smile"}
    grip_names = [item["name"] for item in lora_chain(cfg, grip)]
    oral_names = [item["name"] for item in lora_chain(cfg, oral)]
    idle_names = [item["name"] for item in lora_chain(cfg, idle)]
    assert any("pussygrip" in name for name in grip_names)
    assert any("fellatio" in name for name in oral_names)
    assert not any("pussygrip" in name or "fellatio" in name for name in idle_names)


def test_scope_is_detected_from_lora_folder(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "动作\\MissionaryV1.safetensors", "strength": 0.8,
         "triggers": ["missionary"]},
        {"name": "服装\\SchoolUniformV1.safetensors", "strength": 0.8,
         "triggers": ["school uniform"]},
    ]
    action = {"prompt": "lying on back, legs up"}
    clothing = {"prompt": "serafuku, pleated skirt"}
    action_names = [item["name"] for item in lora_chain(cfg, action)]
    clothing_names = [item["name"] for item in lora_chain(cfg, clothing)]
    assert "动作\\MissionaryV1.safetensors" in action_names
    assert "服装\\SchoolUniformV1.safetensors" not in action_names
    assert "服装\\SchoolUniformV1.safetensors" in clothing_names
    assert "动作\\MissionaryV1.safetensors" not in clothing_names


def test_action_and_clothing_tags_are_added_without_loras(cfg):
    cfg = dict(cfg)
    cfg["action"] = {"tags": "action_tag"}
    cfg["clothing"] = {"tags": "clothing_tag"}
    positive, _ = compose_prompts(cfg, {"prompt": "park"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "action_tag" in tags
    assert "(clothing_tag:1.15)" in positive


def test_compose_prompts_includes_style_lora_tags(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["lora_tags"] = "style_a, style_b"
    positive, _ = compose_prompts(cfg, {"prompt": "park"})
    assert "style_a" in positive
    assert "style_b" in positive


def test_workflow_structure(cfg):
    shot = {"id": "01", "name": "test", "prompt": "wide shot, standing"}
    positive, negative = compose_prompts(cfg, shot)
    wf = build_workflow(cfg, shot, positive, negative, 123, True, "anime_story/01_test")

    assert wf["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["20"]["class_type"] == "LoraLoaderModelOnly"
    assert wf["21"]["inputs"]["model"] == ["20", 0]
    assert wf["21"]["inputs"]["strength_model"] == 0.2
    assert wf["9"]["class_type"] == "KSampler"
    assert wf["13"]["class_type"] == "KSampler"
    assert wf["9"]["inputs"]["steps"] == 12
    assert wf["13"]["inputs"]["denoise"] == 0.4
    assert wf["16"]["class_type"] == "UpscaleModelLoader"
    assert wf["40"]["class_type"] == "IPAdapterUnifiedLoader"
    assert wf["30"]["class_type"] == "IPAdapterUnifiedLoader"
    assert wf["301"]["class_type"] == "FaceDetailer"
    assert wf["303"]["class_type"] == "FaceDetailer"
    assert wf["200"]["inputs"]["text"] == "detailed face"
    assert wf["303"]["inputs"]["image"] == ["301", 0]
    assert wf["999"]["inputs"]["filename_prefix"] == "anime_story/01_test"


def test_upscale_model_scale_detection_supports_8x():
    assert _upscale_model_scale("8x_NMKD-Superscale_150000_G.pth") == 8
    assert _upscale_model_scale("4x-UltraSharp.pth") == 4
    assert _upscale_model_scale("RealESRGAN_x2plus.pth") == 2
    assert _upscale_model_scale("unknown.pth") == 4


def test_workflow_skips_segmentation_detectors_for_face_detailer(cfg):
    cfg = dict(cfg)
    cfg["detailers"] = [{"model": "segm/pussy_yolo11s_seg_best.pt"}]
    wf = build_workflow(cfg, {"prompt": "1girl"}, "p", "n", 1, False, "pref")
    assert not any(node.get("class_type") == "FaceDetailer"
                   for node in wf.values())


def test_workflow_applies_openpose_controlnet(cfg):
    shot = {
        "prompt": "1boy, jeans",
        "pose_image": "anime_story_pose/pose.png",
        "pose_controlnet": "openpose_sdxl.safetensors",
        "pose_strength": 0.65,
        "pose_start": 0.0,
        "pose_end": 0.8,
    }
    positive, negative = compose_prompts(cfg, shot)
    wf = build_workflow(cfg, shot, positive, negative, 1, False, "pref")
    assert wf["100"]["class_type"] == "ControlNetLoader"
    assert wf["100"]["inputs"]["control_net_name"] == "openpose_sdxl.safetensors"
    assert wf["101"]["class_type"] == "LoadImage"
    assert wf["101"]["inputs"]["image"] == "anime_story_pose/pose.png"
    assert wf["102"]["class_type"] == "ControlNetApplyAdvanced"
    assert wf["102"]["inputs"]["positive"] == ["6", 0]
    assert wf["102"]["inputs"]["negative"] == ["7", 0]
    assert wf["102"]["inputs"]["strength"] == 0.65
    assert wf["102"]["inputs"]["end_percent"] == 0.8
    assert wf["9"]["inputs"]["positive"] == ["102", 0]
    assert wf["9"]["inputs"]["negative"] == ["102", 1]


def test_workflow_uses_previous_image_for_img2img(cfg):
    shot = {"prompt": "standing", "init_image": "anime_story_chain/prev.png",
            "init_denoise": 0.55}
    wf = build_workflow(cfg, shot, "p", "n", 1, False, "pref")
    assert "8" not in wf
    assert wf["70"]["class_type"] == "LoadImage"
    assert wf["70"]["inputs"]["image"] == "anime_story_chain/prev.png"
    assert wf["72"]["class_type"] == "ImageScale"
    assert wf["72"]["inputs"]["image"] == ["70", 0]
    assert wf["72"]["inputs"]["width"] == 832
    assert wf["72"]["inputs"]["height"] == 1216
    assert wf["71"]["class_type"] == "VAEEncode"
    assert wf["71"]["inputs"]["pixels"] == ["72", 0]
    assert wf["9"]["inputs"]["latent_image"] == ["71", 0]
    assert wf["9"]["inputs"]["denoise"] == 0.55


def test_workflow_without_hires(cfg):
    shot = {"prompt": "close-up"}
    wf = build_workflow(cfg, shot, "p", "n", 1, False, "pref")
    assert "13" not in wf
    assert "16" not in wf
    assert wf["999"]["inputs"]["images"] == ["303", 0]


def test_wildcards_brace_and_file(tmp_path):
    (tmp_path / "outfit.txt").write_text("winter coat\nschool uniform\n", encoding="utf-8")
    wc = {"enabled": True, "dir": str(tmp_path)}
    text = "{red|blue} ribbon, __outfit__, {a|b|c}"
    first = expand_wildcards(text, 42, wc)
    second = expand_wildcards(text, 42, wc)
    assert first == second
    assert "{" not in first and "__" not in first
    assert any(token in first for token in ("red", "blue"))
    assert any(token in first for token in ("winter coat", "school uniform"))


def test_wildcards_disabled():
    assert expand_wildcards("{red|blue}", 1, {"enabled": False}) == "{red|blue}"
    assert expand_wildcards("{red|blue}", 1, None) == "{red|blue}"


def test_stage_mapping():
    assert stage_for_node("9") == "base"
    assert stage_for_node(13) == "hires"
    assert stage_for_node("301") == "detail"
    assert stage_for_node(90) == "inpaint"
    assert stage_for_node(None) == ""
    assert stage_for_node("999") == ""


def test_split_prompt_groups_keep_clothes_and_hair_apart():
    shot = {
        "cast": "1girl 1boy",
        "prompt": (
            "1girl, 1boy, red_hair, long_hair, white_shirt, torn_pantyhose, "
            "black_lace_bra, short_black_hair, black_eyes, blue_jeans, "
            "cowgirl_position, bedroom"),
        "character_states": {
            "char_01": "white_shirt, black_pantyhose",
            "char_02": "blue_jeans",
        },
        "clothing_details": {
            "char_01": "torn_pantyhose, bra_pull",
            "char_02": "",
        },
    }
    groups = split_prompt_groups(shot)
    girl = next(group for group in groups if group["gender"] == "girl")
    boy = next(group for group in groups if group["gender"] == "boy")
    assert is_double_shot(shot)
    assert "torn_pantyhose" in girl["prompt"]
    assert "white_shirt" in girl["prompt"]
    assert "red_hair" in girl["prompt"]
    assert "blue_jeans" not in girl["prompt"]
    assert "blue_jeans" in boy["prompt"]
    assert "short_black_hair" in boy["prompt"]
    assert "torn_pantyhose" not in boy["prompt"]
    assert "white_shirt" not in boy["prompt"]
    assert "red_hair" not in boy["prompt"]
    assert "long_hair" not in boy["prompt"]


def test_split_prompt_groups_detect_female_key_when_order_is_reversed():
    shot = {
        "cast": "1girl 1boy",
        "prompt": "1girl, 1boy, black dress, red_hair, blue_jeans, "
                  "short_black_hair",
        "character_states": {
            "char_02": "blue_jeans",
            "char_01": "black dress",
        },
    }
    groups = split_prompt_groups(shot)
    girl = next(group for group in groups if group["gender"] == "girl")
    boy = next(group for group in groups if group["gender"] == "boy")
    assert "black dress" in girl["prompt"]
    assert "red_hair" in girl["prompt"]
    assert "blue_jeans" in boy["prompt"]
    assert "short_black_hair" in boy["prompt"]
    assert "black dress" not in boy["prompt"]


def test_split_prompt_groups_keep_casual_male_clothes_off_girl():
    shot = {
        "cast": "1girl 1boy",
        "prompt": "1girl, 1boy, long hair, black hair, purple eyes, "
                  "blunt bangs, medium breasts, uniform, black pantyhose, "
                  "belt, epaulettes, casual shirt, pants",
    }
    groups = split_prompt_groups(shot)
    girl = next(group for group in groups if group["gender"] == "girl")
    boy = next(group for group in groups if group["gender"] == "boy")
    assert "casual shirt" not in girl["prompt"]
    assert "pants" not in girl["prompt"]
    assert "pantyhose" in girl["prompt"]
    assert "casual shirt" in boy["prompt"]
    assert "pants" in boy["prompt"]
    assert "uniform" not in boy["prompt"]
    assert "epaulettes" not in boy["prompt"]


def test_prompt_groups_can_disable_unreliable_fallback():
    shot = {
        "prompt": "1girl, 1boy, long hair, black hair, purple eyes, "
                  "short hair, brown eyes, casual shirt, dark pants",
        "cast": "1girl 1boy",
    }
    assert prompt_groups(shot)
    assert prompt_groups(shot, allow_fallback=False) == []


def test_compose_prompts_drops_half_off_when_pantyhose_is_torn(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": ("1girl, solo, black pantyhose, torn pantyhose, "
                   "pantyhose pulled aside, panties aside"),
        "clothing_details": {"char_01": "torn pantyhose, pantyhose pulled aside"},
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "torn pantyhose" in tags
    assert "pantyhose pulled aside" not in tags
    assert "torn pantyhose" not in negative


def test_compose_prompts_drops_half_off_when_pantyhose_has_crotch_hole(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": ("1girl, solo, black pantyhose, crotch hole, "
                   "pantyhose pulled aside"),
        "clothing_details": {"char_01": "crotch hole, pantyhose pulled aside"},
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "crotch hole" in tags
    assert "pantyhose pulled aside" not in tags


def test_compose_prompts_forces_male_nude_and_faceless(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, clothed male, casual shirt, pants, "
                  "black pantyhose, uniform",
        "cast": "1girl 1boy"})
    assert "clothed male" not in positive
    assert "casual shirt" not in positive
    assert "pants" not in positive
    assert "nude male" in positive
    assert "faceless male" in positive
    assert "male clothes" in negative
    assert "futanari" in negative
    assert "penis on female" in negative
    assert "female head on male" in negative
    assert "long-haired male" in negative


def test_compose_prompts_strips_male_clothing_when_prompt_requests_nude(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, nude male, faceless male, casual shirt, pants",
        "cast": "1girl 1boy"})
    assert "nude male" in positive
    assert "faceless male" in positive
    assert "casual shirt" not in positive
    assert "pants" not in positive
    assert "male clothes" in negative


def test_compose_prompts_forces_male_nude_faceless_and_no_full_body(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": ("1girl, 1boy, full body, wide shot, casual shirt, pants, "
                   "standing, bed"),
        "cast": "1girl 1boy"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "full body" not in tags
    assert "wide shot" not in tags
    assert "casual shirt" not in tags
    assert "pants" not in tags
    assert "nude male" in tags
    assert "faceless male" in tags
    assert "male clothes" in negative


def test_compose_prompts_keeps_full_body_when_script_requires_it(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, full body, standing",
        "script": "全身镜头，两人站在房间中央",
        "cast": "1girl 1boy"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "full body" in tags


def test_compose_prompts_drops_displaced_base_and_faceless_conflict(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": ("1girl, 1boy, black lace panties, panties around ankles, "
                   "red cape, cape on floor, military uniform, "
                   "military uniform around waist, cunnilingus, "
                   "male face between legs, faceless male, nude male"),
        "clothing": "military uniform around waist, panties around ankles",
        "cast": "1girl 1boy"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "black lace panties" not in tags
    assert "panties around ankles" in tags
    assert "red cape" not in tags
    assert "cape on floor" not in tags
    assert "military uniform" not in tags
    assert "military uniform around waist" in tags
    assert "male face between legs" not in tags
    assert "faceless male" in tags


def test_compose_prompts_never_allows_multiple_males(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, 2boys, multiple boys",
        "cast": "1girl solo"})
    assert "2boys" not in positive
    assert "multiple boys" not in positive
    assert "multiple boys" in negative


def test_compose_prompts_blocks_extra_females_without_two_female_cast(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, solo, 2girls, multiple girls",
        "cast": "1girl solo"})
    assert "2girls" not in positive
    assert "multiple girls" in negative


def test_compose_prompts_allows_two_females_with_two_female_cast(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "2girls, multiple girls, bedroom",
        "cast": "2girls"})
    assert "2girls" in positive
    assert "multiple girls" not in negative


def test_compose_prompts_strips_solo_female_from_double(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, solo female, nude male",
        "cast": "1girl 1boy",
    })
    tags = [tag.strip() for tag in positive.split(",")]
    assert "solo female" not in tags
    assert "1boy" in tags


def test_compose_prompts_strips_male_clothing_actions_from_double(cfg):
    positive, _ = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, nude_male, male_pov, unbuckling_belt, "
                  "hands_on_belt, undressing another, hand on clothes, "
                  "pulling clothes, white_shirt",
        "cast": "1girl 1boy",
        "clothing": "white_shirt",
    })
    assert "unbuckling_belt" not in positive
    assert "hands_on_belt" not in positive
    assert "male_pov" not in positive
    assert "undressing another" not in positive
    assert "hand on clothes" not in positive
    assert "pulling clothes" not in positive
    assert "nude_male" in positive
    assert "white_shirt" in positive


def test_compose_prompts_removes_orphan_penis_and_pov_with_visible_male(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, nude male, penis, pov, penis in pussy",
        "cast": "1girl 1boy"})
    assert "penis in pussy" in positive
    assert "nude male" in positive
    assert "pov" not in positive.split(",")
    assert "penis" not in [tag.strip() for tag in positive.split(",")]
    assert "two penises" in negative
    assert "second male" in negative


def test_compose_prompts_adds_double_negative(cfg):
    positive, negative = compose_prompts(cfg, {
        "prompt": "1girl, 1boy, bed", "cast": "1girl 1boy"})
    assert "1girl" in positive
    assert "merged bodies" in negative


def test_compose_prompts_adds_solo_head_and_second_person_negative(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, solo, completely nude, masturbation"})
    assert "1girl" in positive
    assert "two heads" in negative
    assert "extra person" in negative
    assert "1boy" in negative


def test_compose_prompts_blocks_futa_anatomy_in_solo_female_scene(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, solo, completely nude, hand between legs, masturbation"})
    assert "1girl" in positive
    assert "futanari" in negative
    assert "dickgirl" in negative
    assert "penis" in negative


def test_compose_prompts_allows_male_body_for_solo_pov_penetration(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, solo, completely nude, penetration, "
                        "penis in pussy, pov"})
    assert "1girl" in positive
    assert "1boy" not in negative
    assert "male face" in negative
    assert "futanari" in negative


def test_compose_prompts_allows_male_anatomy_for_solo_mouth_scene(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, solo, pov, fellatio, penis"})
    assert "1girl" in positive
    assert "1boy" not in negative
    assert "male head" in negative


def test_compose_prompts_allows_explicit_futanari_scene(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, solo, completely nude, futanari, masturbation"})
    assert "1girl" in positive
    assert "futanari" not in negative
    assert "dickgirl" not in negative


def test_compose_pass_prompts_block_duplicate_same_gender(cfg):
    girl = {"gender": "girl", "prompt": "1girl, long hair"}
    boy = {"gender": "boy", "prompt": "1boy, short hair"}
    _, girl_negative = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy"}, girl)
    _, boy_negative = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy"}, boy)
    assert "multiple girls" in girl_negative
    assert "multiple boys" in boy_negative


def test_compose_pass_prompts_use_gender_negatives(cfg):
    girl = {"gender": "girl", "prompt": "1girl, dress"}
    boy = {"gender": "boy", "prompt": "1boy, jeans"}
    girl_positive, girl_negative = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy"}, girl)
    boy_positive, boy_negative = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy"}, boy)
    assert "dress" in girl_positive
    assert "pantyhose" not in girl_negative
    assert "jeans" in boy_positive
    assert "pantyhose" in boy_negative
    assert "pussy" in boy_negative


def test_compose_pass_prompts_keep_character_and_scope_tags(cfg):
    cfg = dict(cfg)
    cfg["loras"] = cfg["loras"] + [
        {"name": "actions\\MissionaryV1.safetensors", "strength": 0.8,
         "scope": "action", "triggers": ["missionary"]},
    ]
    girl = {"gender": "girl",
            "prompt": "1girl, lying on back, legs up, red hair"}
    boy = {"gender": "boy", "prompt": "1boy, short black hair, jeans"}
    girl_positive, _ = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy", "prompt": "1girl, 1boy"}, girl)
    boy_positive, _ = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy", "prompt": "1girl, 1boy"}, boy)
    assert "yixuan" in girl_positive
    assert "missionary" in girl_positive
    assert "yixuan" not in boy_positive


def test_compose_pass_prompts_do_not_negate_male_long_hair(cfg):
    boy = {"gender": "boy", "prompt": "1boy, long hair, jeans"}
    _, negative = compose_pass_prompts(
        cfg, {"cast": "1girl 1boy"}, boy)
    assert "long hair" not in negative


def test_explicit_prompts_get_uncensored_reinforcement(cfg):
    positive, negative = compose_prompts(
        cfg, {"prompt": "1girl, hetero, penis_in_pussy"})
    assert "uncensored" in positive
    assert "detailed penis" in positive
    assert "mosaic" not in positive
    assert "pixelation" not in positive
    assert "mosaic" in negative
    assert "pixelated" in negative


def test_non_explicit_prompts_do_not_get_uncensored_tags(cfg):
    positive, negative = compose_prompts(cfg, {"prompt": "1girl, bedroom"})
    assert "uncensored" not in positive
    assert "pixelated" not in negative


def test_workflow_inpaints_second_character_in_masked_region(cfg):
    shot = {
        "prompt": "1boy",
        "init_image": "anime_story_chain/split.png",
        "init_denoise": 1.0,
        "inpaint_mask": {"x": 0.48, "y": 0.0, "width": 0.52,
                         "height": 1.0, "grow": 8},
    }
    wf = build_workflow(cfg, shot, "p", "n", 1, False, "pref")
    assert wf["90"]["class_type"] == "SolidMask"
    assert wf["90"]["inputs"]["value"] == 0.0
    assert wf["91"]["class_type"] == "SolidMask"
    assert wf["91"]["inputs"]["value"] == 1.0
    assert wf["92"]["class_type"] == "MaskComposite"
    assert wf["92"]["inputs"]["operation"] == "add"
    assert wf["71"]["class_type"] == "VAEEncodeForInpaint"
    assert wf["71"]["inputs"]["mask"] == ["92", 0]
    assert wf["9"]["inputs"]["latent_image"] == ["71", 0]
    assert wf["9"]["inputs"]["denoise"] == 1.0
