from __future__ import annotations

from comfyui_generator.core import prompt_repair, render_verify
from comfyui_generator.core.repair_shared import (
    MINIMAL_FIX_SYSTEM, constrain_to_findings,
)


def test_single_shared_system_prompt():
    assert prompt_repair.MINIMAL_FIX_SYSTEM is MINIMAL_FIX_SYSTEM
    assert render_verify.MINIMAL_FIX_SYSTEM is MINIMAL_FIX_SYSTEM


def test_shared_constraint_is_used_by_both_repair_paths():
    original = "1girl, smile, black bra"
    rewritten = "1girl, smile, black bra, missionary, 1boy"
    findings = [{"kind": "render_cast_missing_boy", "message": "1boy",
                 "evidence": "1boy"}]
    expected = constrain_to_findings(rewritten, original, findings)
    assert prompt_repair.constrain_minimal(rewritten, original, findings) == expected
    verifier = render_verify.RenderVerifier.__new__(render_verify.RenderVerifier)
    assert verifier._constrain(rewritten, original, findings) == expected
    assert "missionary" not in expected
