from comfyui_generator.core.fluid_guard import detect_fluid_discontinuity


def test_fluid_persists_across_shots_is_clean():
    shots = [
        {"prompt": "1girl 1boy, cum inside, vaginal sex"},
        {"prompt": "1girl 1boy, semen leaking, missionary"},
        {"prompt": "1girl 1boy, cum dripping, close-up"},
    ]
    assert detect_fluid_discontinuity(shots) == {}


def test_fluid_disappearing_is_flagged():
    shots = [
        {"prompt": "1girl 1boy, fellatio, cum in mouth"},
        {"prompt": "1girl 1boy, missionary, vaginal sex"},
    ]
    findings = detect_fluid_discontinuity(shots)
    assert 1 in findings
    assert findings[1][0]["kind"] == "fluid_discontinuity"
    assert findings[1][0]["severity"] == "P2"


def test_cleanup_resets_continuity():
    shots = [
        {"prompt": "1girl 1boy, cum inside, sex"},
        {"prompt": "1girl, cleaning cum, wiping"},
        {"prompt": "1girl solo, sitting, calm"},
    ]
    assert detect_fluid_discontinuity(shots) == {}


def test_new_fluid_after_gap_is_not_flagged_once():
    shots = [
        {"prompt": "1girl, masturbation, pussy juice"},
        {"prompt": "1girl, sitting"},
        {"prompt": "1girl 1boy, saliva, fellatio"},
        {"prompt": "1girl 1boy, cum, swallowing"},
    ]
    findings = detect_fluid_discontinuity(shots)
    assert sorted(findings) == [1]
