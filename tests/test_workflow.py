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
            {"name": "角色\\绝区零\\仪玄\\Char-ZZZ-Yixuan-V2-IL.safetensors",
             "strength": 0.9},
            {"name": "AnimeScreencap\\anime_screencap-IllustriousV2.safetensors",
             "strength": 0.2},
        ],
        "character": {"tags": "yixuan, solo"},
        "style": {"positive": "masterpiece", "negative": "bad quality",
                  "suffix": "sunny"},
        "settings": {
            "width": 832, "height": 1216, "steps": 12, "cfg": 5,
            "sampler": "euler_ancestral", "scheduler": "normal",
            "base_seed": 100,
            "hires": {"enabled": True, "scale": 1.5, "steps": 8,
                      "denoise": 0.4,
                      "upscale_model": "RealESRGAN_x4plus_anime_6B.pth",
                      "model_scale": 4.0},
        },
        "detailers": [
            {"model": "bbox/face_yolov8n.pt", "prompt": "detailed face",
             "denoise": 0.3, "guide_size": 512},
        ],
        "wildcards": {"enabled": False, "dir": ""},
        "shots": [],
    }


# --------------------------------------------------------------- compose order

def test_compose_prompts_order(cfg):
    shot = {
        "prompt": "1girl, smile",
        "style_positive": "STYLE",
        "character_tags": "silver hair",
        "action_tags": "sitting",
        "clothing_tags": "skirt",
        "body_tags": "purple eyes",
        "style_suffix": "night",
    }
    positive, negative = compose_prompts(cfg, shot)
    assert positive.index("STYLE") < positive.index("silver hair")
    assert positive.index("silver hair") < positive.index("sitting")
    assert positive.index("sitting") < positive.index("skirt")
    assert positive.index("skirt") < positive.index("purple eyes")
    assert positive.index("purple eyes") < positive.index("1girl, smile")
    assert positive.endswith("night")
    assert negative == "bad quality"


def test_compose_prompts_uses_ai_negative_field(cfg):
    shot = {"prompt": "1girl", "negative": "ai generated neg"}
    _, negative = compose_prompts(cfg, shot)
    assert "ai generated neg" in negative
    assert "bad quality" in negative


def test_compose_prompts_dedupes_exact_tags(cfg):
    shot = {"prompt": "1girl, 1girl, smile", "character_tags": "1girl"}
    positive, _ = compose_prompts(cfg, shot)
    assert positive.count("1girl") == 1


# ------------------------------------------------------------- no hidden policydef test_compose_prompts_does_not_inject_scene_or_male_tags(cfg):
    shot = {"prompt": "1girl, classroom"}
    positive, negative = compose_prompts(cfg, shot)
    assert "nude male" not in positive
    assert "faceless male" not in positive
    assert "multiple boys" not in negative


def test_compose_prompts_keeps_ai_scene(cfg):
    shot = {"prompt": "1girl, balcony"}
    positive, _ = compose_prompts(cfg, shot)
    assert "balcony" in positive


def test_compose_prompts_passes_body_tag_through(cfg):
    # Keyword suppression removed: body tags are composed verbatim; clothing
    # continuity is validated by the AI judge, not by regex.
    shot = {"prompt": "1girl, red jacket, white shirt, white pleated skirt",
            "body_tags": "pussy"}
    positive, _ = compose_prompts(cfg, shot)
    assert "pussy" in positive


def test_compose_prompts_keeps_body_tag_when_exposed(cfg):
    shot = {"prompt": "1girl, white shirt, skirt lifted, panties aside",
            "body_tags": "pussy, wet pussy"}
    positive, _ = compose_prompts(cfg, shot)
    assert "pussy" in positive


# ------------------------------------------------------------------ lora chain

def test_lora_chain_filters_empty_and_supports_legacy():
    assert lora_chain(
        {"loras": [{"name": "a"}, {"name": ""}]}) == [{"name": "a"}]
    assert lora_chain({"lora": {"name": "b"}}) == [{"name": "b"}]
    assert lora_chain({}) == []


# ------------------------------------------------------------------ wildcards

def test_expand_wildcards_disabled_returns_text():
    assert expand_wildcards("hello", 1, {"enabled": False}) == "hello"
    assert expand_wildcards("x", 1, {}) == "x"


# ----------------------------------------------------------------- build workflow

def test_build_workflow_has_core_nodes(cfg):
    shot = {"id": "01", "prompt": "1girl, smile"}
    wf = build_workflow(cfg, shot, "pos text", "neg text", seed=100,
                        hires=False, prefix="anime_story/test")
    assert wf["6"]["inputs"]["text"] == "pos text"
    assert wf["7"]["inputs"]["text"] == "neg text"
    assert "9" in wf
    assert "10" in wf
    assert "999" in wf


def test_build_workflow_adds_lora_nodes(cfg):
    shot = {"id": "01", "prompt": "1girl"}
    wf = build_workflow(cfg, shot, "pos", "neg", seed=100, hires=False,
                        prefix="p")
    assert "20" in wf
    assert "21" in wf
    assert wf["20"]["class_type"] in {"LoraLoader", "LoraLoaderModelOnly"}


def test_build_workflow_includes_hires_when_enabled(cfg):
    shot = {"id": "01", "prompt": "1girl"}
    wf = build_workflow(cfg, shot, "pos", "neg", seed=100, hires=True,
                        prefix="p")
    assert "11" in wf


# --------------------------------------------------------------- stage_for_node

def test_stage_for_node_known_ids():
    assert stage_for_node(9) == "base"
    assert stage_for_node(91) == "inpaint"
    assert stage_for_node(102) == "pose"
    assert stage_for_node(13) == "hires"
    assert stage_for_node(300) == "detail"
    assert stage_for_node("not-int") == ""
    assert stage_for_node(None) == ""
