from comfyui_generator.core.continuity import (
    character_sheet_prompt,
    continuity_negative,
    continuity_positive,
    normalize_continuity,
)
from comfyui_generator.core.workflow import compose_prompts


def test_normalize_continuity_defaults():
    data = normalize_continuity(None)
    assert data == {"character": "", "scene": "", "state": "", "negative": ""}


def test_normalize_continuity_strips_fields():
    data = normalize_continuity({"character": "silver hair", "extra": 1})
    assert data["character"] == "silver hair"
    assert "extra" not in data


def test_character_sheet_prompt_contains_views_and_character():
    text = character_sheet_prompt(
        "silver hair, red eyes", "black blazer", "anime screencap")
    for expected in ("front view", "side view", "back view", "silver hair",
                     "black blazer", "anime screencap"):
        assert expected in text


def test_continuity_prompt_includes_bible_state():
    text = continuity_positive(
        {"character": "silver hair, red eyes",
         "scene": "bedroom, night, warm lamp",
         "state": "torn stockings, sweat"})
    for expected in ("silver hair", "bedroom", "torn stockings"):
        assert expected in text


def test_shot_ledger_overrides_global_state():
    text = continuity_positive(
        {"character": "silver hair", "scene": "bedroom", "state": "sweat"},
        {"continuity_scene": "kitchen", "continuity_state": "torn stockings"})
    assert "kitchen" in text
    assert "torn stockings" in text
    assert "sweat" not in text


def test_continuity_negative():
    assert continuity_negative({"negative": "different hair, extra people"}) == (
        "different hair, extra people")


def test_workflow_injects_continuity():
    cfg = {
        "style": {"positive": "anime style", "negative": "bad quality"},
        "continuity": {
            "character": "silver hair",
            "scene": "bedroom",
            "state": "sweat",
            "negative": "different location",
        },
    }
    shot = {
        "prompt": "standing, wide shot, from below",
    }
    positive, negative = compose_prompts(cfg, shot)
    assert "silver hair" in positive
    assert "bedroom" in positive
    assert "sweat" in positive
    assert "wide shot" in positive
    assert "different location" in negative
