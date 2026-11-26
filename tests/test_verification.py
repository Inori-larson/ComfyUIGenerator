from __future__ import annotations

from comfyui_generator.core.tagdb import load_tag_database
from comfyui_generator.core.verification import VerifyThresholds, verify_render


def result(**general) -> dict:
    return {"general": general}


def kinds(findings):
    return [(f["kind"], f["severity"]) for f in findings]


def test_solo_prompt_with_detected_boy_is_cast_conflict():
    db = load_tag_database()
    prompt = "1girl solo, school uniform, classroom"
    tagger = result(**{"1girl": 0.99, "1boy": 0.92, "solo": 0.4})
    findings = verify_render(prompt, tagger, db, VerifyThresholds())
    assert ("render_cast_extra_boy", "P1") in kinds(findings)


def test_two_person_prompt_without_boy_is_missing_boy():
    db = load_tag_database()
    prompt = "1girl 1boy, nude male, faceless male, missionary"
    tagger = result(**{"1girl": 0.99, "1boy": 0.2})
    findings = verify_render(prompt, tagger, db)
    assert ("render_cast_missing_boy", "P1") in kinds(findings)


def test_missing_girl_always_flagged():
    db = load_tag_database()
    tagger = result(**{"1girl": 0.2})
    findings = verify_render("1girl solo, smile", tagger, db)
    assert ("render_cast_missing_girl", "P1") in kinds(findings)


def test_closed_shirt_with_detected_nudity_is_layer_conflict():
    db = load_tag_database()
    prompt = "1girl solo, white shirt, long sleeves"
    tagger = result(**{"1girl": 0.99, "nipples": 0.9, "shirt": 0.8})
    findings = verify_render(prompt, tagger, db)
    assert ("render_layer_bra_over_outer", "P1") in kinds(findings)


def test_open_shirt_bare_breasts_is_not_conflict():
    db = load_tag_database()
    prompt = "1girl, shirt open, bra pulled down, nipples, bare breasts"
    tagger = result(**{
        "1girl": 0.99, "nipples": 0.95, "bare breasts": 0.9,
        "bra": 0.8, "shirt": 0.4,
    })
    findings = verify_render(prompt, tagger, db)
    assert not [f for f in findings if f["kind"] == "render_layer_bra_over_outer"]


def test_required_bare_breasts_not_detected_is_advisory():
    db = load_tag_database()
    prompt = "1girl 1boy, nude male, bra pulled down, nipples, bare breasts"
    tagger = result(**{"1girl": 0.99, "1boy": 0.9, "bra": 0.9,
                       "nipples": 0.1, "bare breasts": 0.1})
    findings = verify_render(prompt, tagger, db)
    assert ("render_layer_breasts_hidden", "P2") in kinds(findings)


def test_empty_tagger_result_produces_no_findings():
    db = load_tag_database()
    assert verify_render("1girl solo, white shirt, nipples", {"general": {}}, db) == []


def test_thresholds_avoid_low_confidence_finding():
    db = load_tag_database()
    prompt = "1girl solo, white shirt, long sleeves"
    tagger = result(**{"1girl": 0.99, "nipples": 0.52, "shirt": 0.9})
    findings = verify_render(
        prompt, tagger, db, VerifyThresholds(layer=0.75))
    assert not [f for f in findings if f["kind"] == "render_layer_bra_over_outer"]


def test_panties_and_legwear_cooccur_is_not_flagged():
    # WD cannot reliably tell panties-under vs panties-over legwear; both
    # tags co-occur normally, so no false layering finding is emitted.
    db = load_tag_database()
    prompt = ("1girl 1boy, nude male, black thighhighs, "
              "black lace panties, sex")
    tagger = result(**{"1girl": 0.99, "1boy": 0.9, "thighhighs": 0.97,
                       "panties": 0.98, "black panties": 0.95})
    findings = verify_render(prompt, tagger, db)
    assert not [f for f in findings if "legwear" in f["kind"]]


def test_extra_boys_beyond_requested_count_is_flagged():
    db = load_tag_database()
    prompt = "1girl 1boy, nude male, missionary"
    tagger = result(**{"1girl": 0.99, "1boy": 0.9, "2boys": 0.85,
                       "multiple boys": 0.8})
    findings = verify_render(prompt, tagger, db)
    assert ("render_cast_extra_boy", "P1") in kinds(findings)


def test_extra_girls_beyond_requested_count_is_flagged():
    db = load_tag_database()
    prompt = "1girl 1boy, nude male, doggystyle"
    tagger = result(**{"1girl": 0.99, "2girls": 0.9, "1boy": 0.9})
    findings = verify_render(prompt, tagger, db)
    assert ("render_cast_extra_girl", "P1") in kinds(findings)


def test_requested_two_girls_with_two_detected_is_not_flagged():
    db = load_tag_database()
    prompt = "2girls, smile"
    tagger = result(**{"2girls": 0.95})
    findings = verify_render(prompt, tagger, db)
    assert not [f for f in findings
                if f["kind"] in ("render_cast_extra_girl", "render_cast_extra_boy")]


def test_unspecified_cast_count_does_not_assume_extra():
    db = load_tag_database()
    prompt = "girl, boy, holding hands"
    tagger = result(**{"2girls": 0.9, "girl": 0.8})
    findings = verify_render(prompt, tagger, db)
    assert not [f for f in findings if f["kind"] == "render_cast_extra_girl"]


def test_no_character_prompt_does_not_require_a_girl():
    db = load_tag_database()
    tagger = result(**{"landscape": 0.9, "scenery": 0.8})
    findings = verify_render("scenery, landscape, no humans", tagger, db)
    assert findings == []


def test_declared_fluid_missing_in_render_is_advisory():
    db = load_tag_database()
    tagger = result(**{"1girl": 0.99, "1boy": 0.9, "fellatio": 0.8})
    findings = verify_render("1girl 1boy, cum in mouth, fellatio", tagger, db)
    assert ("render_fluid_missing", "P2") in kinds(findings)


def test_unexpected_rendered_fluid_is_advisory():
    db = load_tag_database()
    tagger = result(**{"1girl": 0.99, "cum": 0.8})
    findings = verify_render("1girl solo, sitting", tagger, db)
    assert ("render_fluid_unexpected", "P2") in kinds(findings)


def test_missing_scene_anchor_is_advisory():
    db = load_tag_database()
    tagger = result(**{"1girl": 0.99, "smile": 0.8})
    findings = verify_render(
        "1girl solo, smiling", tagger, db,
        expected_scene="classroom, school desk")
    assert ("render_scene_missing", "P2") in kinds(findings)


def test_matching_scene_anchor_is_not_flagged():
    db = load_tag_database()
    tagger = result(**{"1girl": 0.99, "classroom": 0.8})
    findings = verify_render(
        "1girl solo, smiling", tagger, db,
        expected_scene="classroom, school desk")
    assert "render_scene_missing" not in [f["kind"] for f in findings]
