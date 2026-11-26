from __future__ import annotations

from comfyui_generator.core.outline_guard import detect_outline_pacing


def _shots(count: int, *, beat: str = "B1",
           descriptions: list[str] | None = None) -> list[dict]:
    return [
        {
            "id": "%02d" % (index + 1),
            "beat_id": beat,
            "description": descriptions[index] if descriptions else "same beat",
        }
        for index in range(count)
    ]


def test_beat_concentration_is_advisory():
    descriptions = ["alpha", "bravo", "charlie", "delta",
                    "echo", "foxtrot", "golf", "hotel"]
    shots = _shots(8, descriptions=descriptions)
    findings = detect_outline_pacing(shots)
    assert any(f["kind"] == "outline_beat_concentration"
               for f in findings.get(0, []))
    assert not [f for group in findings.values() for f in group
                if f["severity"] == "P1"]


def test_identical_descriptions_in_one_beat_are_blocking():
    findings = detect_outline_pacing(_shots(6))
    stalled = [f for group in findings.values() for f in group
               if f["kind"] == "outline_semantic_stall"]
    assert len(stalled) == 4
    assert all(f["severity"] == "P1" for f in stalled)
    assert sorted(int(f["shot_index"]) for f in stalled) == [2, 3, 4, 5]


def test_shots_without_declared_beats_are_left_alone():
    shots = [{"id": "%02d" % (index + 1), "description": "same"}
             for index in range(8)]
    assert detect_outline_pacing(shots) == {}


def test_beat_change_resets_semantic_stall_run():
    shots = [
        {"id": "01", "beat_id": "B1", "description": "a"},
        {"id": "02", "beat_id": "B1", "description": "a"},
        {"id": "03", "beat_id": "B2", "description": "a"},
        {"id": "04", "beat_id": "B2", "description": "a"},
        {"id": "05", "beat_id": "B2", "description": "a"},
        {"id": "06", "beat_id": "B2", "description": "a"},
    ]
    findings = detect_outline_pacing(shots)
    stalled = [int(f["shot_index"]) for group in findings.values()
               for f in group if f["kind"] == "outline_semantic_stall"]
    assert stalled == [4, 5]
