from __future__ import annotations

from comfyui_generator.core.story_contract import (
    StoryContract, contract_from_generation, validate_contract,
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
