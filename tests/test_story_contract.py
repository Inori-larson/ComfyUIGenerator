from __future__ import annotations

from comfyui_generator.core.story_contract import (
    CONTRACT_SCOPE, StoryContract, contract_from_generation, validate_contract,
)


def test_contract_from_generation_reads_ai_declared_beats():
    raw = {"beats": [{"id": "B1", "description": "自慰"},
                     {"id": "B2", "description": "口交"}]}
    contract = contract_from_generation(raw)
    assert contract.beat_ids == ["B1", "B2"]
    assert contract.has_beats


def test_contract_ignores_premise_text():
    # No regex/semantic extraction: a premise string alone yields no beats.
    assert not contract_from_generation({"premise": "1. 自慰 2. 口交"}).has_beats


def test_full_coverage_order_and_ending():
    raw = {"beats": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]}
    contract = contract_from_generation(raw)
    shots = [
        {"id": "01", "beat_id": "B1"},
        {"id": "02", "beat_id": "B1"},
        {"id": "03", "beat_id": "B2"},
        {"id": "04", "beat_id": "B3"},
    ]
    assert validate_contract(shots, contract) == []


def test_missing_beat_and_ending_mismatch():
    contract = contract_from_generation(
        {"beats": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]})
    shots = [
        {"id": "01", "beat_id": "B1"},
        {"id": "02", "beat_id": "B1"},
        {"id": "03", "beat_id": "B1"},
    ]
    findings = validate_contract(shots, contract)
    kinds = {f["kind"] for f in findings}
    assert "contract_event_missing" in kinds
    assert "contract_ending_mismatch" in kinds


def test_order_violation_and_unknown_beat():
    contract = contract_from_generation(
        {"beats": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]})
    shots = [
        {"id": "01", "beat_id": "B2"},
        {"id": "02", "beat_id": "B1"},
        {"id": "03", "beat_id": "B3"},
    ]
    findings = validate_contract(shots, contract)
    assert any(f["kind"] == "contract_order_violation" for f in findings)

    bad = validate_contract([{"id": "01", "beat_id": "B9"}], contract)
    assert bad[0]["kind"] == "contract_unknown_beat"


def test_no_beats_declared_means_no_validator_opinion():
    assert validate_contract([{"id": "01"}], StoryContract()) == []


def test_contract_scope_declares_its_limits():
    assert "entity/clothing state" in CONTRACT_SCOPE["not_validated"]
    assert "fluid timeline" in CONTRACT_SCOPE["not_validated"]
    assert "request AI outline rewrite" in CONTRACT_SCOPE["on_findings"]


def test_findings_are_scoped_to_the_relevant_shot():
    contract = contract_from_generation(
        {"beats": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]})
    shots = [
        {"id": "01", "beat_id": "B2"},
        {"id": "02", "beat_id": "B1"},
        {"id": "03", "beat_id": "B1"},
    ]
    order = next(f for f in validate_contract(shots, contract)
                 if f["kind"] == "contract_order_violation")
    assert order["scope"] == "shot"
    assert order["shot_index"] == 1
    assert order["shot_id"] == "02"


def test_project_level_and_ending_findings_are_scoped():
    contract = contract_from_generation(
        {"beats": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]})
    shots = [
        {"id": "01", "beat_id": "B1"},
        {"id": "02", "beat_id": "B1"},
        {"id": "03", "beat_id": "B1"},
    ]
    findings = validate_contract(shots, contract)
    missing = next(f for f in findings if f["kind"] == "contract_event_missing")
    assert missing["scope"] == "contract"
    assert missing["shot_index"] is None
    ending = next(f for f in findings if f["kind"] == "contract_ending_mismatch")
    assert ending["scope"] == "shot"
    assert ending["shot_index"] == 2
    assert ending["shot_id"] == "03"


def test_unknown_beat_finding_points_at_the_offending_shot():
    contract = contract_from_generation(
        {"beats": [{"id": "B1"}, {"id": "B2"}]})
    finding = validate_contract(
        [{"id": "01", "beat_id": "B1"}, {"id": "02", "beat_id": "B9"}],
        contract)[0]
    assert finding["kind"] == "contract_unknown_beat"
    assert finding["shot_index"] == 1
    assert finding["shot_id"] == "02"
