from comfyui_generator.core.clothing_state import (
    clothing_gate_blockers,
    clothing_gate_findings,
    clothing_repair_plan,
    initial_weighted_categories,
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


def test_pacing_gate_flags_post_penetration_backtrack():
    shots = [
        {"id": "01", "prompt": "1girl, 1boy, penis in pussy"},
        {"id": "02", "prompt": "1girl, 1boy, fellatio, penis in mouth"},
    ]
    coverage = ai_review.coverage_gate_findings(shots)
    assert any("回退" in m for m in coverage)


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


def test_ensure_clothing_gate_loops_until_clear():
    from comfyui_generator.core.ai_review import ensure_clothing_gate

    clean_prompt = ("1girl, discarded frilled black leotard on floor, "
                    "discarded black blazer on floor, torn pantyhose, "
                    "black lace panties, panties aside, black lace bra")
    repaired = {"shots": [
        {"id": "01", "valid": False, "issues": ["fixed"],
         "prompt": clean_prompt}]}

    class GateClient:
        def __init__(self):
            self.calls = 0

        def chat_json(self, *a, **k):
            self.calls += 1
            return repaired

    initial = [{"id": "01",
                "prompt": "1girl, black blazer, frilled black leotard, "
                          "leotard skirt rolled up to waist, "
                          "torn pantyhose, black lace panties, "
                          "panties aside, black lace bra"}]
    client = GateClient()
    performed = ensure_clothing_gate(client, "deepseek-v4.1-flash",
                                     initial, PREMISE, max_passes=3)
    assert performed >= 1
    assert client.calls >= 1
    plan = clothing_repair_plan(initial, PREMISE)
    assert plan["fixes"] == []
