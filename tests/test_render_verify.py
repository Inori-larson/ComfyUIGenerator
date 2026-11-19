from __future__ import annotations

from pathlib import Path

import pytest

from comfyui_generator.core.render_verify import RenderVerifier


class _TaggerConfig:
    enabled = True
    max_rerender = 2
    model_path = ""
    device = "cpu"
    cast_threshold = 0.6
    layer_threshold = 0.5
    general_threshold = 0.55


class _TagDbConfig:
    csv_path = ""
    alias_path = ""


class _FakeLLM:
    def __init__(self, reply="1girl, shirt open, nipples"):
        self.reply = reply
        self.calls = 0

    def chat_json(self, *args, **kwargs):
        self.calls += 1
        return {"prompt": self.reply}


def _verifier(tmp_path: Path, prompt_reply: str) -> RenderVerifier:
    return RenderVerifier(
        python="python", root=tmp_path, base_dir="",
        tagger_config=_TaggerConfig(), tagdb_config=_TagDbConfig(),
        llm_client=_FakeLLM(prompt_reply), llm_model="fake")


def test_instruction_mentions_findings():
    instruction = RenderVerifier.rewrite_instruction([
        {"message": "成品检出男性", "expected": "1girl solo", "actual": "1boy 0.9"}])
    assert "成品" in instruction and "1boy 0.9" in instruction


def test_evaluate_accepts_when_no_blocking(tmp_path: Path, monkeypatch):
    v = _verifier(tmp_path, "ignored")
    clean = {"general": {"1girl": 0.99, "solo": 0.9}}
    monkeypatch.setattr(v, "interrogate", lambda path: clean)
    decision = v.evaluate(str(tmp_path / "x.png"),
                          "1girl solo, school uniform, smile")
    assert decision.accepted is True
    assert decision.new_prompt == ""
    assert v.llm_client.calls == 0


def test_evaluate_rewrites_on_blocking_cast(tmp_path: Path, monkeypatch):
    reply = "1girl, 1boy, male focus, nude male, faceless male, school uniform"
    v = _verifier(tmp_path, reply)
    tagger = {"general": {"1girl": 0.95, "1boy": 0.93}}
    monkeypatch.setattr(v, "interrogate", lambda path: tagger)
    decision = v.evaluate(str(tmp_path / "x.png"),
                          "1girl solo, school uniform")
    assert decision.accepted is False
    tags = {t.strip() for t in decision.new_prompt.split(",")}
    assert "1boy" in tags
    assert "school uniform" in tags
    assert "testicles" not in tags


def test_evaluate_layer_conflict_triggers_rewrite(tmp_path: Path, monkeypatch):
    v = _verifier(tmp_path, "1girl, shirt open, nipples, bare breasts")
    tagger = {"general": {"1girl": 0.99, "nipples": 0.9, "shirt": 0.9}}
    monkeypatch.setattr(v, "interrogate", lambda path: tagger)
    decision = v.evaluate(str(tmp_path / "x.png"),
                          "1girl solo, white shirt, long sleeves")
    assert decision.accepted is False
    assert any(f["kind"] == "render_layer_bra_over_outer"
               for f in decision.findings)


def test_evaluate_accepts_on_rewrite_failure(tmp_path: Path, monkeypatch):
    v = _verifier(tmp_path, "ignored")

    def boom(*args, **kwargs):
        raise RuntimeError("content filter")

    v.llm_client.chat_json = boom
    tagger = {"general": {"1girl": 0.9, "1boy": 0.9}}
    monkeypatch.setattr(v, "interrogate", lambda path: tagger)
    decision = v.evaluate(str(tmp_path / "x.png"), "1girl solo")
    assert decision.accepted is True
    assert decision.new_prompt == ""
    assert decision.findings


class _DummyVerifier(RenderVerifier):
    def __init__(self):
        pass


def test_constrain_keeps_only_allowed_additions():
    v = _DummyVerifier()
    original = "1girl 1boy, nude male, military uniform, penis, sex"
    rewritten = ("1girl, 1boy, nude male, military uniform, penis, sex, "
                 "male focus, testicles, missionary, masterpiece, sweat, bed")
    findings = [{"kind": "render_cast_missing_boy",
                 "expected": "1boy", "evidence": "1boy"}]
    out = v._constrain(rewritten, original, findings)
    tags = {t.strip() for t in out.split(",")}
    assert "1boy" in tags
    assert "male focus" not in tags
    assert "testicles" not in tags
    assert "missionary" not in tags
    assert "masterpiece" not in tags
    assert "military uniform" in tags


def test_constrain_allows_bare_breast_tags_only_for_hidden_finding():
    v = _DummyVerifier()
    original = "1girl 1boy, bra pulled down"
    rewritten = ("1girl, 1boy, bra pulled down, nipples, bare breasts, "
                 "missionary, ahegao, bed")
    findings = [{"kind": "render_layer_breasts_hidden",
                 "expected": "nipples, bare breasts",
                 "evidence": "nipples, bare breasts"}]
    out = v._constrain(rewritten, original, findings)
    tags = {t.strip() for t in out.split(",")}
    assert {"nipples", "bare breasts"} <= tags
    assert "missionary" not in tags and "ahegao" not in tags
