from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from comfyui_generator.core.entity_state import OPEN, REMOVED, WORN, parse_state
from comfyui_generator.core.tag_validation import (
    ValidationOptions,
    annotate_shots,
    validate_prompt,
)
from comfyui_generator.core.tagdb import (
    TagDatabase,
    load_layers,
    load_tag_database,
)

LAYERS = load_layers()


def kinds(result):
    return [(f["kind"], f["severity"]) for f in result.findings]


def test_shipped_layer_vocab_loads():
    assert "outer_top" in LAYERS and "inner_top" in LAYERS
    db = load_tag_database()
    assert db.layer_vocab()
    assert not db.has_table()


def test_on_ground_outer_allows_bra():
    db = load_tag_database()
    result = validate_prompt(
        "1girl solo, uniform on ground, black lace bra, bare shoulders", db)
    assert not result.blocking


def test_same_garment_worn_and_removed_is_state_conflict():
    db = load_tag_database()
    result = validate_prompt(
        "1girl, military uniform, military uniform on ground, black bra", db)
    assert any(f["kind"] == "state_conflict"
               and f["severity"] == "P1" for f in result.findings)


def test_footwear_removed_with_bare_feet_is_clean():
    db = load_tag_database()
    result = validate_prompt(
        "1girl, black platform heels removed, mary janes removed, bare feet", db)
    assert not result.findings


def test_only_lingerie_with_non_inner_garments_is_advisory():
    db = load_tag_database()
    result = validate_prompt(
        "1girl, only lingerie, white gloves, black pantyhose, platform heels", db)
    assert any(f["kind"] == "layer_claim_conflict"
               and f["severity"] == "P2" for f in result.findings)


def test_only_lingerie_with_inner_items_only_is_clean():
    db = load_tag_database()
    result = validate_prompt(
        "1girl, only lingerie, black lace bra, black lace panties", db)
    assert not result.findings


def test_panties_aside_under_pantyhose_is_advisory():
    db = load_tag_database()
    result = validate_prompt(
        "1girl 1boy, black lace panties aside under black pantyhose, sex", db)
    assert any(f["kind"] == "layer_panty_under_legwear"
               and f["severity"] == "P2" for f in result.findings)


def test_panties_aside_with_thighhighs_is_clean():
    db = load_tag_database()
    result = validate_prompt(
        "1girl 1boy, black lace panties aside, black thighhighs, sex", db)
    assert not [f for f in result.findings
                if f["kind"] == "layer_panty_under_legwear"]


def test_torn_pantyhose_with_panties_aside_is_clean():
    db = load_tag_database()
    result = validate_prompt(
        "1girl 1boy, black pantyhose torn, black lace panties aside, sex", db)
    assert not [f for f in result.findings
                if f["kind"] == "layer_panty_under_legwear"]


def test_non_fetish_accessories_during_sex_are_advisory():
    db = load_tag_database()
    result = validate_prompt(
        "1girl 1boy, nude male, white gloves, black platform heels, "
        "nipples, bare breasts, sex", db)
    kinds = [f["kind"] for f in result.findings]
    assert "removable_garment_during_sex" in kinds
    finding = next(f for f in result.findings
                   if f["kind"] == "removable_garment_during_sex")
    assert "white gloves" in finding["evidence"]
    assert "black platform heels" not in finding["evidence"]


def test_non_fetish_accessories_before_nudity_are_clean():
    db = load_tag_database()
    result = validate_prompt(
        "1girl solo, uniform, white gloves, black platform heels, sitting", db)
    assert not [f for f in result.findings
                if f["kind"] == "removable_garment_during_sex"]


def test_closed_jacket_with_bra_is_blocking():
    db = load_tag_database()
    prompt = "1girl, military uniform, red jacket, white shirt, black bra"
    result = validate_prompt(prompt, db)
    assert ("layer_overexposure", "P1") in kinds(result)
    assert result.blocking
    assert not result.ready


def test_closed_shirt_with_nipples_is_blocking():
    db = load_tag_database()
    prompt = "1girl, white shirt, long sleeves, nipples, bare breasts"
    result = validate_prompt(prompt, db)
    assert ("layer_conflict", "P1") in kinds(result)
    assert result.blocking
    assert not result.ready


def test_open_or_removed_outer_allows_breasts_and_bra():
    db = load_tag_database()
    opened = validate_prompt(
        "1girl, shirt open, black bra, nipples, bare breasts", db)
    assert not opened.blocking
    removed = validate_prompt(
        "1girl, white shirt removed, bra pulled down, nipples", db)
    assert not removed.blocking


def test_onpiece_dress_removed_allows_nudity():
    db = load_tag_database()
    result = validate_prompt("1girl solo, dress removed, nipples, pussy", db)
    assert not result.blocking


def test_closed_skirt_with_pussy_is_advisory_lifted_is_ok():
    db = load_tag_database()
    closed = validate_prompt("1girl, pleated skirt, panties, pussy", db)
    assert ("layer_conflict", "P2") in kinds(closed)
    lifted = validate_prompt(
        "1girl, pleated skirt hiked up, panties aside, pussy", db)
    assert not lifted.findings


def test_cast_conflict_solo_with_boy():
    db = load_tag_database()
    result = validate_prompt("1girl solo, 1boy, nude male", db)
    assert ("cast_conflict", "P1") in kinds(result)
    clean = validate_prompt("1girl 1boy, nude male, faceless male", db)
    assert not clean.blocking


def test_normal_sex_scene_has_no_layer_finding():
    db = load_tag_database()
    prompt = ("1girl 1boy, nude male, faceless male, black lace bra pulled down, "
              "bare breasts, nipples, black lace panties aside, "
              "pleated skirt hiked up, missionary position, vaginal sex")
    result = validate_prompt(prompt, db)
    assert not result.blocking
    assert not [f for f in result.findings if f["kind"].startswith("layer")]


def test_sfw_story_is_not_injected_with_nsfw_logic():
    db = load_tag_database()
    prompt = ("1girl solo, school uniform, pleated skirt, classroom, "
              "smile, holding book")
    result = validate_prompt(prompt, db)
    assert not result.findings


def test_word_boundaries_do_not_misread_braid_as_bra():
    state = parse_state("1girl, side braid, long hair, military uniform", LAYERS)
    inner = [g for g in state.garments if g.category == "inner_top"]
    assert inner == []


def test_entity_states():
    state = parse_state(
        "white shirt removed, black bra pulled down, pleated skirt hiked up, "
        "panties aside, nipples", LAYERS)
    states = {(g.category, g.state) for g in state.garments}
    assert ("outer_top", REMOVED) in states
    assert ("inner_top", OPEN) in states
    assert ("outer_bottom", "lifted") in states
    assert state.skin_top


def test_danbooru_csv_unknown_and_alias(tmp_path: Path):
    csv_file = tmp_path / "danbooru.csv"
    csv_file.write_text(textwrap.dedent(
        '1girl,0,100,\n'
        'pleated_skirt,0,90,pleated skirt\n'
        'school_uniform,0,80,\n'
        'nipples,0,70,\n'), encoding="utf-8")
    db = load_tag_database(csv_file)
    assert db.has_table()
    assert db.is_known("pleated skirt")
    assert not db.is_known("flibberty gibbet")
    result = validate_prompt(
        "1girl, flibberty gibbet, made up triggerword", db,
        ValidationOptions(report_unknown=True, report_aliases=False))
    assert any(f["kind"] == "unknown_tag" for f in result.findings)


def test_alias_canonicalisation_off_by_default(tmp_path: Path):
    csv_file = tmp_path / "danbooru.csv"
    csv_file.write_text(
        'school_uniform,0,80,"school uniform,seifuku aliased"\n',
        encoding="utf-8")
    db = load_tag_database(csv_file)
    result = validate_prompt("1girl, school uniform", db)
    assert result.canonical == {}
    options = ValidationOptions(report_unknown=False, auto_canonical_alias=True)
    shots = [{"id": "01", "prompt": "1girl, school uniform"}]
    annotate_shots(shots, db, options)
    assert "school_uniform" in shots[0]["prompt"]


def test_wildcards_are_not_unknown_tags(tmp_path: Path):
    csv_file = tmp_path / "danbooru.csv"
    csv_file.write_text("1girl,0,100,\n", encoding="utf-8")
    db = load_tag_database(csv_file)
    result = validate_prompt(
        "1girl, __backgrounds/cinema__, {a|b}, <lora:x:1>, smile", db)
    unknown = [f for f in result.findings if f["kind"] == "unknown_tag"]
    evidence = " ".join(f["evidence"] for f in unknown)
    assert "__backgrounds" not in evidence
    assert "{a|b}" not in evidence
    assert "<lora" not in evidence


def test_annotate_shots_sets_ready_and_findings():
    db = TagDatabase(layers=LAYERS)
    shots = [
        {"id": "01", "prompt": "1girl solo, white shirt, nipples"},
        {"id": "02", "prompt": "1girl 1boy, nude male, faceless male, nipples"},
    ]
    annotate_shots(shots, db, ValidationOptions(report_unknown=False,
                                                report_aliases=False))
    assert shots[0]["ready"] is False
    assert shots[0]["findings"]
    assert shots[1]["ready"] is True
    assert shots[1]["findings"] == []
