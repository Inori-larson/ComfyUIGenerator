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
