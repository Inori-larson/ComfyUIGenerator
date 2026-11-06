from comfyui_generator.core.style_profile import (
    STYLE_PROFILES,
    apply_style_profile,
    normalize_style_profile,
    style_profile_apply_settings,
    style_profile_positive,
)
from comfyui_generator.core.workflow import compose_prompts


def test_normalize_defaults_to_none():
    assert normalize_style_profile(None)["id"] == "none"
    assert normalize_style_profile({"id": "missing"})["id"] == "none"
    selected = normalize_style_profile({"id": "tv_anime"})
    assert selected == {
        "id": "tv_anime",
        "use_prompt": True,
        "use_negative": True,
        "use_suffix": True,
    }


def test_apply_style_profile_is_opt_in():
    style = {"positive": "masterpiece", "negative": "bad quality", "suffix": "sunny"}
    out = apply_style_profile(style, {"id": "none"})
    assert out == style
    assert out is not style


def test_apply_style_profile_respects_switches():
    style = {"positive": "masterpiece", "negative": "bad quality", "suffix": "sunny"}
    out = apply_style_profile(style, {
        "id": "tv_anime",
        "use_prompt": True,
        "use_negative": False,
        "use_suffix": True,
    })
    assert "masterpiece" in out["positive"]
    assert "anime screencap" in out["positive"]
    assert out["negative"] == "bad quality"
    assert "consistent character design" in out["suffix"]


def test_style_text_is_deduplicated():
    style = {"positive": "anime screencap", "negative": "", "suffix": ""}
    out = apply_style_profile(style, {"id": "tv_anime"})
    assert out["positive"].lower().count("anime screencap") == 1


def test_workflow_applies_profile_to_prompts():
    cfg = {
        "style": {"positive": "masterpiece", "negative": "bad quality"},
        "style_profile": {"id": "live_action"},
    }
    positive, negative = compose_prompts(cfg, {"prompt": "standing"})
    assert "cinematic film still" in positive
    assert "anime" in negative


def test_workflow_profile_can_be_disabled():
    cfg = {
        "style": {"positive": "masterpiece", "negative": "bad quality"},
        "style_profile": {"id": "live_action", "use_prompt": False,
                          "use_negative": False, "use_suffix": False},
    }
    positive, negative = compose_prompts(cfg, {"prompt": "standing"})
    assert positive.startswith("masterpiece")
    assert "cinematic film still" not in positive
    assert negative.startswith("bad quality")


def test_profile_positive_helper():
    assert style_profile_positive({"id": "none"}) == ""
    assert "anime screencap" in style_profile_positive({"id": "tv_anime"})
    assert style_profile_positive(
        {"id": "tv_anime", "use_prompt": False}) == ""


def test_builtin_profiles_are_complete():
    for profile_id, profile in STYLE_PROFILES.items():
        assert profile["label"]
        assert profile["description"]
        assert profile["apply"]
        if profile_id != "none":
            assert profile["positive"]


def test_default_profile_has_baseline_setup():
    setup = style_profile_apply_settings({"id": "none"})
    assert "waiIllustrious" in setup["checkpoint_hints"][0]
    assert setup["width"] == 1024
    assert setup["height"] == 1344
    assert setup["steps"] == 30
    assert style_profile_apply_settings({"id": "tv_anime"})[
        "style_lora_hints"]


def test_profile_setup_is_a_copy():
    setup = style_profile_apply_settings({"id": "tv_anime"})
    setup["steps"] = 1
    assert style_profile_apply_settings({"id": "tv_anime"})["steps"] == 30
