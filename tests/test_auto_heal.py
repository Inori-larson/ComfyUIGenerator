from __future__ import annotations

import json
from types import SimpleNamespace

from comfyui_generator.core.auto_heal import (
    archive_report, build_heal_requirement, collect_blocking, new_report,
    premise_hash, record_round, summarize_findings,
)
from comfyui_generator.core.config import AutoHealConfig
from comfyui_generator.core.storyboard import StoryboardOptions
from comfyui_generator.ui import workers


def test_collect_blocking_ignores_advisory_and_deduplicates():
    shots = [{
        "id": "01",
        "findings": [
            {"kind": "shot_stall", "severity": "P2", "message": "advisory"},
            {"kind": "render_cast_extra_boy", "severity": "P1",
             "message": "extra"},
            {"kind": "contract_event_missing", "severity": "P1",
             "message": "missing"},
            {"kind": "contract_event_missing", "severity": "P1",
             "message": "missing"},
        ],
    }]
    findings = collect_blocking(shots)
    assert len(findings) == 2
    assert {f["kind"] for f in findings} == {
        "render_cast_extra_boy", "contract_event_missing"}
    assert all(f["shot_id"] == "01" for f in findings)


def test_heal_requirement_uses_only_structured_evidence():
    findings = [{
        "kind": "outline_semantic_stall", "severity": "P1",
        "shot_id": "07", "message": "no new semantic", "evidence": "run=4",
    }]
    text = build_heal_requirement(findings, 12)
    assert "目标镜数：12" in text
    assert "outline_semantic_stall" in text or "no new semantic" in text
    assert "run=4" in text


def test_report_rounds_and_archive(tmp_path):
    report = new_report("任意剧情", 8, "fake-model")
    before = [{"kind": "contract_event_missing", "severity": "P1",
               "message": "x", "shot_id": "03"}]
    record_round(report, round_index=1, before=before, after=[], accepted=True)
    assert report["resolved"] is True
    assert report["rounds"][0]["blocking_before"] == 1
    assert summarize_findings(before) == {"contract_event_missing": 1}
    path = archive_report(tmp_path, report)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["premise_id"] == premise_hash("任意剧情")
    assert saved["resolved"] is True


def test_premise_hash_is_stable_and_content_addressed():
    assert premise_hash("abc") == premise_hash("abc")
    assert premise_hash("abc") != premise_hash("abd")


class _Log:
    def __init__(self):
        self.messages: list[str] = []

    def emit(self, message: str) -> None:
        self.messages.append(message)


def test_heal_loop_regenerates_until_blocking_clears(monkeypatch):
    settings: list[str] = []

    def fake_generate(client, premise, options):
        settings.append(options.setting)
        blocking = (len(settings) == 1)
        shot = {"id": "01", "prompt": "1girl"}
        if blocking:
            shot["findings"] = [{
                "kind": "contract_event_missing", "severity": "P1",
                "message": "missing B2", "shot_id": "01"}]
        if options.on_contract:
            options.on_contract([{"id": "B1"}, {"id": "B2"}])
        return [shot]

    monkeypatch.setattr(workers, "generate_storyboard", fake_generate)
    worker = SimpleNamespace(
        cfg=SimpleNamespace(auto_heal=AutoHealConfig(
            enabled=True, max_rounds=2, archive=False)),
        story_options=StoryboardOptions(model="fake", shots=1, setting="base"),
        text="任意剧情", model="fake", use_external=False,
        log=_Log(), _heal_report=None, _generated_beats=None,
        _canceled=lambda: False,
        _story_llm_client=lambda: (object(), "fake"),
        _prepare_story_shots=lambda shots: None,
    )
    shots = [{"id": "01", "prompt": "1girl", "findings": [{
        "kind": "contract_event_missing", "severity": "P1",
        "message": "missing B2", "shot_id": "01"}]}]

    workers.PromptWorker._auto_heal_story(worker, shots)

    assert len(settings) == 2
    assert "校验发现的问题" in settings[0]
    assert worker._heal_report["rounds"][0]["accepted"] is False
    assert worker._heal_report["rounds"][1]["accepted"] is True
    assert worker._heal_report["resolved"] is True
    assert shots == [{"id": "01", "prompt": "1girl"}]
