from comfyui_generator.core.continuity import (
    apply_auto_grammar,
    auto_shot_grammar,
    character_sheet_prompt,
    continuity_negative,
    continuity_positive,
    normalize_continuity,
    strip_shot_grammar,
)
from comfyui_generator.core.workflow import compose_pass_prompts, compose_prompts


def test_normalize_continuity_defaults():
    data = normalize_continuity(None)
    assert data["grammar"] == {"auto": True, "style": "cinematic"}
    assert normalize_continuity({"grammar": {"style": "missing"}})[
        "grammar"]["style"] == "cinematic"


def test_auto_shot_grammar_cycles():
    first = auto_shot_grammar(0, 3, {"grammar": {"style": "cinematic"}})
    second = auto_shot_grammar(1, 3, {"grammar": {"style": "cinematic"}})
    assert first["shot_size"] == "wide shot"
    assert second["shot_size"] == "medium shot"
    assert second["camera_angle"] == "from side"


def test_apply_auto_grammar_preserves_manual_values():
    shots = [{"shot_size": "close-up", "camera_angle": "from below"},
             {"shot_size": "", "camera_angle": ""}]
    apply_auto_grammar(shots, {"grammar": {"style": "cinematic"}})
    assert shots[0]["shot_size"] == "close-up"
    assert shots[1]["shot_size"] == "medium shot"
    apply_auto_grammar(shots, {"grammar": {"style": "cinematic"}},
                       overwrite=True)
    assert shots[0]["shot_size"] == "wide shot"


def test_character_sheet_prompt_contains_views_and_character():
    text = character_sheet_prompt(
        "silver hair, red eyes", "black blazer", "anime screencap")
    for expected in ("front view", "side view", "back view", "silver hair",
                     "black blazer", "anime screencap"):
        assert expected in text


def test_continuity_prompt_includes_bible_state_and_grammar():
    text = continuity_positive(
        {"character": "silver hair, red eyes",
         "scene": "bedroom, night, warm lamp",
         "state": "torn stockings, sweat"},
        {"shot_size": "close-up", "camera_angle": "from above"})
    for expected in ("silver hair", "bedroom", "torn stockings", "close-up",
                     "from above"):
        assert expected in text


def test_continuity_negative():
    assert continuity_negative({"negative": "different hair, extra people"}) == (
        "different hair, extra people")


def test_strip_old_framing_tags():
    assert strip_shot_grammar(
        "close-up, full-body, from below, bedroom, smiling") == (
        "bedroom, smiling")


def test_workflow_injects_continuity_and_shot_grammar():
    cfg = {
        "style": {"positive": "masterpiece", "negative": "bad quality"},
        "continuity": {
            "character": "silver hair",
            "scene": "bedroom",
            "state": "sweat",
            "negative": "different location",
            "grammar": {"style": "cinematic"},
        },
    }
    shot = {
        "prompt": "standing, wide shot, from below",
        "shot_size": "close-up",
        "camera_angle": "from above",
    }
    positive, negative = compose_prompts(cfg, shot)
    assert "silver hair" in positive
    assert "bedroom" in positive
    assert "sweat" in positive
    assert "close-up" in positive
    assert "from above" in positive
    assert "wide shot" not in positive
    assert "different location" in negative


def test_boy_pass_does_not_receive_female_character_anchor():
    cfg = {
        "style": {"positive": "masterpiece", "negative": "bad quality"},
        "continuity": {
            "character": "silver hair, breasts",
            "scene": "bedroom",
            "state": "cum on thigh",
        },
    }
    shot = {"prompt": "1boy, standing"}
    positive, _ = compose_pass_prompts(
        cfg, shot, {"gender": "boy", "prompt": "1boy, standing"})
    assert "silver hair" not in positive
    assert "cum on thigh" not in positive
    assert "bedroom" in positive
