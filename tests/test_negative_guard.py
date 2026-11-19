from __future__ import annotations

from comfyui_generator.core.negative_guard import automatic_negative
from comfyui_generator.core.workflow import compose_prompts


def test_no_invented_correction_tag():
    negative = automatic_negative(
        "1girl 1boy, nude male, black pantyhose, black lace panties, sex", "")
    assert negative == ""


def test_removed_shoes_are_suppressed_in_negative():
    negative = automatic_negative(
        "1girl, black platform heels removed, mary janes removed, standing", "")
    assert "black platform heels" in negative
    assert "mary janes" in negative


def test_removed_outfit_placed_on_chair_is_suppressed():
    negative = automatic_negative(
        "1girl, uniform removed, uniform placed on chair, heels", "")
    assert "uniform" in negative


def test_guard_not_duplicated():
    once = automatic_negative(
        "1girl, black platform heels removed",
        "black platform heels")
    assert once.count("black platform heels") == 1


def test_open_clothes_are_not_suppressed():
    negative = automatic_negative(
        "1girl, shirt open, black bra, nipples, bare breasts", "")
    assert negative == ""


def test_compose_prompts_keeps_negative_and_suppresses_removed():
    cfg = {
        "style": {"positive": "", "negative": "lowres, bad anatomy"},
        "character": {"tags": "1girl"},
        "settings": {},
    }
    shot = {"prompt": "1girl 1boy, nude male, black platform heels removed, sex"}
    positive, negative = compose_prompts(cfg, shot)
    assert "black platform heels removed" in positive
    assert "black platform heels" in negative
    assert "bad anatomy" in negative
