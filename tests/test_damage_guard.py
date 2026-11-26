from comfyui_generator.core.damage_guard import detect_damage_restored


def test_damaged_garment_staying_damaged_is_clean():
    shots = [
        {"prompt": "1girl, black pantyhose torn, black panties"},
        {"prompt": "1girl, black pantyhose ripped, black panties"},
    ]
    assert detect_damage_restored(shots) == {}


def test_damaged_garment_restored_is_flagged():
    shots = [
        {"prompt": "1girl, black pantyhose cut, black panties"},
        {"prompt": "1girl, black pantyhose, black panties"},
    ]
    findings = detect_damage_restored(shots)
    assert 1 in findings
    assert findings[1][0]["kind"] == "damage_restored"
    assert findings[1][0]["severity"] == "P2"


def test_replacement_resets_damage():
    shots = [
        {"prompt": "1girl, black pantyhose torn"},
        {"prompt": "1girl, new pantyhose, clean"},
        {"prompt": "1girl, black pantyhose, clean"},
    ]
    assert detect_damage_restored(shots) == {}


def test_garment_absent_is_not_restored():
    shots = [
        {"prompt": "1girl, black pantyhose torn"},
        {"prompt": "1girl, dress, no pantyhose"},
    ]
    assert detect_damage_restored(shots) == {}
