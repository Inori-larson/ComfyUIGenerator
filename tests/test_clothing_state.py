from comfyui_generator.core.clothing_state import (
    anatomy_conflicts,
    clothing_gate_blockers,
    clothing_gate_findings,
    clothing_repair_plan,
    initial_weighted_categories,
    lower_occlusion_open,
    script_clothing_conflicts,
    upper_occlusion_open,
)
from comfyui_generator.core import ai_review

PREMISE = (
    "初始服装：hairclip(1.2), puritan collar, flower brooch, black blazer, "
    "frilled black leotard, black pantyhose(1.2), black platform heels(1.2), "
    "back-seamed legwear(1.2), black lace panties(1.2), black lace bra(1.2)\n"
    "大场景：教室\n剧情：x")


def test_initial_weighted_categories():
    assert initial_weighted_categories(PREMISE) == {
        "hairclip", "panties", "pantyhose", "heels", "bra"}


def test_unweighted_leotard_must_come_off():
    shots = [
        {"id": "01", "prompt": "1girl, frilled black leotard"},
        {"id": "02", "prompt": "1girl, frilled black leotard, "
                                "leotard skirt rolled up to waist"},
    ]
    findings = clothing_gate_findings(shots, PREMISE)
    assert "02" in findings
    assert any("leotard" in m for m in findings["02"])


def test_weighted_pantyhose_cannot_be_fully_removed():
    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose"},
        {"id": "02", "prompt": "1girl, pantyhose removed, barefoot"},
    ]
    blockers = clothing_gate_blockers(shots, PREMISE)
    assert any("pantyhose" in b for b in blockers)


def test_weighted_allowed_states_pass():
    shots = [
        {"id": "01", "prompt": "1girl, black blazer, black pantyhose, "
                                "black lace panties, black lace bra"},
        {"id": "02", "prompt": "1girl, discarded black blazer on floor, "
                                "torn pantyhose, black lace panties, "
                                "panties aside, black lace bra, bra pull"},
    ]
    assert clothing_gate_findings(shots, PREMISE) == {}


def test_weighted_worn_and_off_conflict_is_detected():
    shots = [
        {"id": "01", "prompt": "1girl, black platform heels"},
        {"id": "02", "prompt": "1girl, black platform heels, heels on floor"},
    ]
    plan = clothing_repair_plan(shots, PREMISE)
    fixes = [f for f in plan["fixes"] if f["shot"] == "02"]
    assert any(f["kind"] == "conflicting_states"
               and f["category"] == "heels" for f in fixes)
    assert any("active" in f["expected"] for f in fixes
               if f["kind"] == "conflicting_states")


def test_unweighted_conflicting_states_still_detected():
    shots = [
        {"id": "01", "prompt": "1girl, black blazer"},
        {"id": "02", "prompt": "1girl, black blazer, blazer on chair"},
    ]
    plan = clothing_repair_plan(shots, PREMISE)
    assert any(f["shot"] == "02" and f["kind"] == "conflicting_states"
               and f["weighted"] is False for f in plan["fixes"])



def test_removed_garment_location_is_stable():
    shots = [
        {"id": "01", "prompt": "1girl, black blazer on floor"},
        {"id": "02", "prompt": "1girl, discarded black blazer on desk"},
    ]
    blockers = clothing_gate_blockers(shots, PREMISE)
    assert any("位置" in b for b in blockers)


def test_explicit_restore_allows_weighted_pullback():
    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose, "
                                "pantyhose pulled down"},
        {"id": "02", "prompt": "1girl, black pantyhose, pulled back up"},
    ]
    findings = clothing_gate_findings(shots, PREMISE)
    assert findings == {}


def test_hand_action_tags_not_treated_as_garment():
    shots = [
        {"id": "01", "prompt": "1girl, frilled black leotard, "
                                "hands on skirt, pulling skirt down"},
    ]
    findings = clothing_gate_findings(shots, PREMISE)
    assert all("skirt" not in m for messages in findings.values()
               for m in messages)


def test_backtrack_after_penetration_is_advisory_only():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, penis in pussy"},
        {"id": "02", "prompt": "1girl, 1boy, fellatio, penis in mouth"},
    ]
    blockers = ai_review.final_gate_blockers(shots, PREMISE)
    assert blockers == []
    coverage = ai_review.coverage_gate_findings(shots)
    assert any("确认项" in m for m in coverage)


def test_pacing_gate_flags_duplicate_adjacent_shots():
    shots = [
        {"id": "01", "prompt": "1girl, frilled black leotard, blush"},
        {"id": "02", "prompt": "1girl, frilled black leotard, blush"},
    ]
    coverage = ai_review.coverage_gate_findings(shots)
    assert any("几乎完全相同" in m for m in coverage)


def test_repair_plan_names_exact_tags_and_expected_action():
    shots = [{"id": "50",
              "prompt": "1girl, frilled black leotard, "
                        "leotard skirt rolled up to waist"}]
    plan = clothing_repair_plan(shots, PREMISE)
    kinds = {fix["kind"] for fix in plan["fixes"]}
    assert "must_be_off" in kinds
    off = next(f for f in plan["fixes"] if f["kind"] == "must_be_off")
    assert "frilled black leotard" in off["tags"]
    assert "off-body" in off["expected"]


def test_repair_plan_includes_ledger_and_weighted():
    shots = [
        {"id": "01", "prompt": "1girl, black pantyhose, black blazer"},
        {"id": "02", "prompt": "1girl, torn pantyhose, "
                                "discarded black blazer on floor"},
    ]
    plan = clothing_repair_plan(shots, PREMISE)
    assert set(plan["weighted"]) >= {"pantyhose"}
    assert plan["ledger"]["01"]["pantyhose"] == "worn"
    assert plan["ledger"]["02"]["pantyhose"] == "displaced"


def test_message_carries_fixes_ledger_and_residual():
    import json
    from comfyui_generator.core.ai_review import _build_messages
    batch = [{"id": "50",
              "prompt": "1girl, frilled black leotard, "
                        "leotard skirt rolled up to waist"}]
    plan = clothing_repair_plan(batch, PREMISE)
    plan["residual"] = [
        {"shot": "50", "category": "leotard",
         "message": "still there", "residual_tags": ["frilled black leotard"]}]
    msgs = _build_messages("clothing", PREMISE, batch, [],
                           clothing_plan=plan)
    payload = json.loads(msgs[1]["content"])
    assert payload["required_fixes"][0]["tags"]
    assert "clothing_ledger" in payload
    assert payload["residual_tags"][0]["residual_tags"] == [
        "frilled black leotard"]


def test_nonadjacent_pairs_detected_separately():
    shots = [
        {"id": "01", "prompt": "1girl, blush, sitting"},
        {"id": "02", "prompt": "1girl, different, standing, smile"},
        {"id": "03", "prompt": "1girl, blush, sitting"},
    ]
    pairs = ai_review.nonadjacent_similar_pairs(shots)
    assert any(set(p[:2]) == {"01", "03"} for p in pairs)
    assert ai_review.duplicate_shot_groups(shots) == []


def test_phase_stall_run_detected():
    shots = [
        {"id": "%02d" % (i + 1), "phase": "stuck", "prompt": "p%d" % i}
        for i in range(12)
    ]
    runs = ai_review.phase_stall_runs(shots)
    assert runs and runs[0][0] == "stuck"
    assert len(runs[0][1]) == 12


def test_final_gate_blocks_consecutive_duplicates_only():
    shots = [
        {"id": "%02d" % (i + 1), "phase": "stuck",
         "prompt": "1girl, identical tags, blush, smile"}
        for i in range(12)
    ]
    blockers = ai_review.final_gate_blockers(shots, PREMISE)
    assert any("consecutive duplicate" in b for b in blockers)
    assert all("phase stall" not in b for b in blockers)


def test_nonadjacent_similar_is_advisory_not_hard_blocker():
    shots = [
        {"id": "01", "prompt": "1girl, blush, smile, sitting"},
        {"id": "02", "prompt": "1girl, different, standing, frown"},
        {"id": "03", "prompt": "1girl, blush, smile, sitting"},
    ]
    pairs = ai_review.nonadjacent_similar_pairs(shots)
    assert any(set(p[:2]) == {"01", "03"} for p in pairs)
    assert ai_review.adjacent_duplicate_runs(shots) == []
    blockers = ai_review.final_gate_blockers(shots, PREMISE)
    assert all("duplicate" not in b for b in blockers)


def test_consecutive_identical_run_is_hard_blocker():
    shots = [
        {"id": "01", "prompt": "1girl, identical tags, blush, smile"},
        {"id": "02", "prompt": "1girl, identical tags, blush, smile"},
        {"id": "03", "prompt": "1girl, identical tags, blush, smile"},
    ]
    runs = ai_review.adjacent_duplicate_runs(shots)
    assert runs == [["01", "02", "03"]]
    blockers = ai_review.final_gate_blockers(shots, PREMISE)
    assert any("consecutive duplicate" in b for b in blockers)


def test_final_gate_clears_after_corrected_shot():
    clean_prompt = ("1girl, discarded frilled black leotard on floor, "
                    "discarded black blazer on floor, torn pantyhose, "
                    "black lace panties, panties aside, black lace bra")
    initial = [{"id": "01",
                "prompt": "1girl, black blazer, frilled black leotard, "
                          "leotard skirt rolled up to waist, "
                          "torn pantyhose, black lace panties, "
                          "panties aside, black lace bra"}]
    assert ai_review.final_gate_blockers(initial, PREMISE)

    corrected = [{"id": "01", "prompt": clean_prompt}]
    assert ai_review.final_gate_blockers(corrected, PREMISE) == []
    assert clothing_repair_plan(corrected, PREMISE)["fixes"] == []


def test_weighted_removed_midfilm_is_detected_even_if_it_returns():
    shots = [
        {"id": "01", "prompt": "1girl, black lace bra"},
        {"id": "02", "prompt": "1girl, black lace bra on desk"},
        {"id": "03", "prompt": "1girl, black lace bra, bra pull"},
    ]
    plan = clothing_repair_plan(shots, PREMISE)
    kinds = [(f["shot"], f["kind"]) for f in plan["fixes"]]
    assert ("02", "weighted_was_removed") in kinds


def test_cum_during_oral_is_advisory_not_blocker():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, fellatio, cum in mouth"},
        {"id": "02", "prompt": "1girl, 1boy, cum on face, cum on body"},
        {"id": "03", "prompt": "1girl, 1boy, cunnilingus"},
    ]
    blockers = ai_review.final_gate_blockers(shots, PREMISE)
    assert blockers == []


def test_progression_note_is_advisory():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, penis in pussy"},
        {"id": "02", "prompt": "1girl, 1boy, cunnilingus"},
    ]
    findings = ai_review.story_structure_findings(shots)
    assert all(f["kind"] == "progression_note" for f in findings)
    assert "无需修改" in findings[0]["message"]


def test_aftermath_rank_zero_has_no_note():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, penis in pussy"},
        {"id": "02", "prompt": "1girl, 1boy, afterglow, blush"},
    ]
    assert ai_review.story_structure_findings(shots) == []


BEACH_PREMISE = (
    "初始服装：school uniform, red blazer, blue bowtie, white collared shirt, "
    "white pleated skirt, zettai ryouiki, black thighhighs, "
    "black lace panties(1.2), black lace bra(1.2), black platform heels(1.2)\n"
    "大场景：海滩\n剧情：x")


def test_panties_missing_under_skirt_with_exposure_cue():
    shots = [
        {"id": "01", "prompt": "1girl, red blazer, white shirt, "
                               "white pleated skirt, sitting, knees up, "
                               "fingers twisting skirt"},
        {"id": "02", "prompt": "1girl, white pleated skirt, "
                               "skirt fluttering, rubbing thighs"},
    ]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    fixes = {(f["shot"], f["kind"]) for f in plan["fixes"]}
    assert ("01", "undergarment_visible_missing") in fixes
    assert ("02", "undergarment_visible_missing") in fixes
    off = next(f for f in plan["fixes"]
               if f["shot"] == "01" and f["kind"]
               == "undergarment_visible_missing")
    assert "black lace panties(1.2)" in off["keep"]


def test_present_panties_do_not_trigger_missing_fix():
    shots = [{"id": "01", "prompt": "1girl, white pleated skirt, "
                                    "black lace panties, sitting, knees up"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"]


def test_bra_not_required_while_shirt_closed():
    shots = [{"id": "01", "prompt": "1girl, red blazer, white shirt, "
                                    "white pleated skirt, standing"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"
                and f["category"] == "bra"]


def test_bra_required_when_shirt_open():
    shots = [{"id": "01", "prompt": "1girl, white shirt, unbuttoned shirt, "
                                    "white pleated skirt, sitting"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert any(f["kind"] == "undergarment_visible_missing"
               and f["category"] == "bra" for f in plan["fixes"])


def test_panties_never_required_under_pants():
    shots = [{"id": "01", "prompt": "1girl, white shirt, black pants, "
                                    "sitting, knees up"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"
                and f["category"] == "panties"]


def test_standing_skirt_without_exposure_cue_ok():
    shots = [{"id": "01", "prompt": "1girl, white shirt, "
                                    "white pleated skirt, standing, smile"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"
                and f["category"] == "panties"]


def test_bottomless_intent_suppresses_panties_missing():
    shots = [{"id": "01", "prompt": "1girl, white pleated skirt, "
                                    "skirt lifted, bottomless"}]
    plan = clothing_repair_plan(shots, BEACH_PREMISE)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"
                and f["category"] == "panties"]


def test_no_initial_undergarment_means_no_visibility_check():
    premise = "初始服装：t-shirt, jeans\n剧情：x"
    shots = [{"id": "01", "prompt": "1girl, t-shirt, jeans, sitting"}]
    plan = clothing_repair_plan(shots, premise)
    assert not [f for f in plan["fixes"]
                if f["kind"] == "undergarment_visible_missing"]


COVERED = "1girl, red jacket, white shirt, white pleated skirt, standing"
EXPOSED = ("1girl, white shirt, white pleated skirt, skirt lifted, "
           "panties aside, wet pussy")


def test_lower_occlusion_open_reflects_state():
    assert lower_occlusion_open({"prompt": COVERED}) is False
    assert lower_occlusion_open({"prompt": EXPOSED}) is True


def test_upper_occlusion_open_reflects_state():
    assert upper_occlusion_open({"prompt": COVERED}) is False
    open_shirt = "1girl, unbuttoned shirt, white pleated skirt, nipples"
    assert upper_occlusion_open({"prompt": open_shirt}) is True


def test_anatomy_conflict_flagged_when_covered():
    shot = {"prompt": COVERED + ", pussy"}
    conflicts = anatomy_conflicts(shot)
    assert "genital_exposed_while_covered" in conflicts
    assert "pussy" in conflicts["genital_exposed_while_covered"]


def test_anatomy_conflict_absent_when_exposed():
    assert anatomy_conflicts({"prompt": EXPOSED}) == {}


def test_plan_includes_anatomy_conflict():
    plan = clothing_repair_plan(
        [{"id": "01", "prompt": COVERED + ", pussy"}], BEACH_PREMISE)
    assert any(f["kind"] == "genital_exposed_while_covered"
               for f in plan["fixes"])




def test_tag_discarded_while_script_keeps_garment_is_flagged():
    shot = {
        "script": "服装：蓝色领结垂在领口两侧，白色百褶裙堆在腰间；",
        "prompt": "discarded necktie on armrest, discarded skirt on chair"}
    conflicts = script_clothing_conflicts(shot)["garment_removed_vs_script"]
    assert set(conflicts) == {"necktie", "skirt"}


def test_tag_discarded_when_script_confirms_removal_is_allowed():
    shot = {
        "script": "服装：红色外套搭在沙发扶手；",
        "prompt": "discarded coat on armrest"}
    assert script_clothing_conflicts(shot) == {}
