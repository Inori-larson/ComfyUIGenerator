from __future__ import annotations

from pathlib import Path

from comfyui_generator.core.prompt_repair import (
    REPAIRABLE_KINDS, auto_repair_shots, batch_repair_advisory,
    constrain_minimal,
)
from comfyui_generator.core.tag_validation import ValidationOptions
from comfyui_generator.core.tagdb import load_tag_database


class _RepairClient:
    """Returns a minimal repair: drop bra under closed uniform."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat_json(self, *args, **kwargs):
        self.calls += 1
        return {"prompt": self.reply}


class _BatchClient:
    def __init__(self, reply: dict):
        self.reply = reply
        self.calls = 0

    def chat_json(self, *args, **kwargs):
        self.calls += 1
        return self.reply


_OPT = ValidationOptions(report_unknown=False, report_aliases=False)


def test_clean_shots_not_sent_to_llm():
    db = load_tag_database()
    client = _RepairClient("ignored")
    shots = [{"id": "01",
              "prompt": "1girl 1boy, nude male, shirt open, bra, nipples, sex"}]
    report = auto_repair_shots(shots, db, client, "fake", options=_OPT)
    assert client.calls == 0
    assert shots[0]["ready"] is True
    assert report.repaired == [] and report.unresolved == []


def test_blocking_shot_repaired_by_dropping_inner_bra():
    db = load_tag_database()
    fixed = ("1girl solo, white gloves, uniform, military uniform, belt, "
             "cape, epaulettes, black pantyhose, heels, bedroom, standing")
    client = _RepairClient(fixed)
    shots = [{"id": "01",
              "prompt": "1girl solo, uniform, military uniform, black lace bra, standing"}]
    report = auto_repair_shots(shots, db, client, "fake", options=_OPT)
    assert client.calls == 1
    assert report.repaired == ["01"]
    assert shots[0]["ready"] is True
    assert "black lace bra" not in shots[0]["prompt"]


def test_unresolved_when_llm_keeps_violation():
    db = load_tag_database()
    # LLM returns the same offending prompt unchanged.
    bad = "1girl solo, uniform, military uniform, black bra"
    client = _RepairClient(bad)
    shots = [{"id": "09", "prompt": bad}]
    report = auto_repair_shots(shots, db, client, "fake",
                                options=_OPT, max_rounds=2)
    assert client.calls == 2
    assert report.unresolved == ["09"]
    assert shots[0]["ready"] is False


def test_constrain_minimal_drops_unrelated_additions():
    findings = [{"kind": "layer_overexposure"}]
    original = "1girl, uniform, military uniform, black bra"
    rewritten = ("1girl, uniform, military uniform, black bra, missionary, "
                 "sweat, masterpiece, ahegao, bed")
    out = constrain_minimal(rewritten, original, findings)
    tags = {t.strip() for t in out.split(",")}
    assert "missionary" not in tags and "masterpiece" not in tags
    assert "military uniform" in tags


def test_auto_repair_respects_call_budget():
    db = load_tag_database()
    bad = "1girl, uniform, military uniform, black bra"
    client = _RepairClient(bad)
    shots = [{"id": "01", "prompt": bad}, {"id": "02", "prompt": bad},
             {"id": "03", "prompt": bad}]
    report = auto_repair_shots(shots, db, client, "fake", options=_OPT,
                               max_calls=1, max_rounds=2)
    assert client.calls == 1
    assert report.attempts == 1
    assert len(report.unresolved) == 3
    assert all(s["ready"] is False for s in shots)


def test_batch_repair_advisory_layer_conflict():
    db = load_tag_database()
    fixed = ("1girl 1boy, nude male, black pantyhose pulled aside, "
             "black panties aside, nipples, sex")
    client = _BatchClient({"prompts": [{"id": "07", "prompt": fixed}]})
    shots = [{
        "id": "07",
        "prompt": ("1girl 1boy, nude male, black pantyhose, "
                   "black lace panties aside under black pantyhose, sex"),
        "findings": [{"kind": "layer_panty_under_legwear", "severity": "P2",
                      "message": "x", "evidence": "pantyhose, panties"}],
    }]
    report = batch_repair_advisory(shots, db, client, "fake", options=_OPT)
    assert client.calls == 1
    assert report.repaired == ["07"]
    assert shots[0]["prompt"] == fixed
    assert not shots[0]["findings"]


def test_batch_repair_ignores_clean_shots():
    db = load_tag_database()
    client = _BatchClient({"prompts": []})
    shots = [{"id": "01", "prompt": "1girl solo, smile", "findings": []}]
    report = batch_repair_advisory(shots, db, client, "fake", options=_OPT)
    assert client.calls == 0
    assert report.repaired == []


def test_contract_findings_are_not_prompt_repairable():
    for kind in ("contract_event_missing", "contract_order_violation",
                 "contract_ending_mismatch", "contract_unknown_beat"):
        assert kind not in REPAIRABLE_KINDS
    assert "shot_stall" not in REPAIRABLE_KINDS


def test_batch_repair_preserves_contract_findings():
    db = load_tag_database()
    fixed = ("1girl 1boy, nude male, black pantyhose pulled aside, "
             "black panties aside, nipples, sex")
    client = _BatchClient({"prompts": [{"id": "07", "prompt": fixed}]})
    contract_finding = {"kind": "contract_event_missing", "severity": "P1",
                        "message": "missing beat", "evidence": "B3"}
    shots = [{
        "id": "07",
        "prompt": ("1girl 1boy, nude male, black pantyhose, "
                   "black lace panties aside under black pantyhose, sex"),
        "findings": [
            {"kind": "layer_panty_under_legwear", "severity": "P2",
             "message": "x", "evidence": "pantyhose, panties"},
            contract_finding,
        ],
        "contract_findings": [contract_finding],
    }]
    report = batch_repair_advisory(shots, db, client, "fake", options=_OPT)
    assert report.repaired == ["07"]
    assert contract_finding in shots[0]["findings"]
    assert shots[0]["ready"] is False


def test_repair_invalidates_stale_translation():
    db = load_tag_database()
    fixed = ("1girl solo, white gloves, uniform, military uniform, belt, "
             "cape, epaulettes, black pantyhose, heels, bedroom, standing")
    client = _RepairClient(fixed)
    shots = [{
        "id": "01",
        "prompt": "1girl solo, uniform, military uniform, black lace bra, standing",
        "prompt_zh": "旧翻译",
        "continuity_state": "black pantyhose, standing",
    }]
    report = auto_repair_shots(shots, db, client, "fake", options=_OPT)
    assert report.repaired == ["01"]
    assert "prompt_zh" not in shots[0]
    assert shots[0]["continuity_stale"] is True
