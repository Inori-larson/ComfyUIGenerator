from __future__ import annotations

from comfyui_generator.core.stall_guard import detect_stalls


def _shot(prompt: str) -> dict[str, str]:
    return {"prompt": prompt}


def test_no_stall_for_progressing_shots():
    shots = [
        _shot("1girl solo, standing, smile"),
        _shot("1girl 1boy, fellatio, penis"),
        _shot("1girl 1boy, missionary, vaginal sex, cum"),
    ]
    assert detect_stalls(shots) == {}


def test_stall_detected_for_near_duplicate_run():
    same = "1girl 1boy, nude male, sixty-nine, fellatio, cunnilingus, saliva"
    shots = [
        _shot("1girl solo, masturbation"),
        _shot(same),
        _shot(same),
        _shot(same),
    ]
    findings = detect_stalls(shots, min_run=3, threshold=0.9)
    assert 1 not in findings
    assert 2 in findings and 3 in findings
    assert findings[2][0]["severity"] == "P2"
    assert findings[2][0]["kind"] == "shot_stall"


def test_stall_resets_after_distinct_shot():
    same = "1girl 1boy, doggy style, sex, sweat"
    shots = [
        _shot(same),
        _shot(same),
        _shot("1girl solo, masturbation, fingering"),
        _shot(same),
        _shot(same),
    ]
    findings = detect_stalls(shots, min_run=3, threshold=0.9)
    assert not findings
