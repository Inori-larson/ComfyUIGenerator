import pytest

from comfyui_generator.core.workflow import (
    build_workflow,
    compose_prompts,
    expand_wildcards,
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
