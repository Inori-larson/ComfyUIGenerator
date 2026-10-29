import pytest

from comfyui_generator.core.workflow import (
    build_workflow,
    compose_prompts,
    expand_wildcards,
    lora_chain,
    stage_for_node,
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
    assert negative == "bad quality"


def test_compose_prompts_includes_body_tags(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": "pussy, nude"}
    positive, _ = compose_prompts(cfg, {"prompt": "park"})
    assert "pussy" in positive
    assert "nude" in positive


def test_compose_prompts_blocks_body_tags_that_remove_clothing(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["negative"] = "bad quality, censored"
    cfg["body"] = {"tags": "pussy, nude, close-up, censored, breasts"}
    shot = {"prompt": "black blazer, frilled black leotard, black pantyhose, full_body"}
    positive, _ = compose_prompts(cfg, shot)
    tags = [tag.strip() for tag in positive.split(",")]
    assert "pussy" not in tags
    assert "nude" not in tags
    assert "close-up" not in tags
    assert "censored" not in tags
    assert "breasts" in tags
    assert "black blazer" in tags


def test_compose_prompts_keeps_body_tags_when_shot_is_nude(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": "pussy, nude, close-up"}
    positive, _ = compose_prompts(cfg, {"prompt": "nude, full_body"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "pussy" in tags
    assert "nude" in tags
    assert "close-up" not in tags


def test_compose_prompts_removes_body_tags_listed_in_negative(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["negative"] = "bad quality, censored"
    cfg["body"] = {"tags": "censored, pussy"}
    positive, _ = compose_prompts(cfg, {"prompt": "nude"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "censored" not in tags
    assert "pussy" in tags


def test_compose_prompts_removes_camera_equipment(cfg):
    cfg = dict(cfg)
    cfg["body"] = {"tags": ""}
    positive, _ = compose_prompts(
        cfg, {"prompt": "looking_at_camera, holding_camera, black_pantyhose, from_below"})
    tags = [tag.strip() for tag in positive.split(",")]
    assert "looking at viewer" in tags
    assert "holding camera" not in tags
    assert "black pantyhose" in tags
    assert "from below" in tags


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


def test_compose_prompts_includes_style_lora_tags(cfg):
    cfg = dict(cfg)
    cfg["style"] = dict(cfg["style"])
    cfg["style"]["lora_tags"] = "style_a, style_b"
    positive, _ = compose_prompts(cfg, {"prompt": "park"})
    assert "style a" in positive
    assert "style b" in positive


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
    assert wf["61"]["class_type"] == "FaceDetailer"
    assert wf["63"]["class_type"] == "FaceDetailer"
    assert wf["200"]["inputs"]["text"] == "detailed face"
    assert wf["63"]["inputs"]["image"] == ["61", 0]
    assert wf["64"]["inputs"]["filename_prefix"] == "anime_story/01_test"


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
    assert wf["64"]["inputs"]["images"] == ["63", 0]


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
    assert stage_for_node("61") == "detail"
    assert stage_for_node(None) == ""
    assert stage_for_node("64") == ""
