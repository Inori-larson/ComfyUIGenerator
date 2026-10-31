import json

import pytest

from comfyui_generator.core.auto_continuity import (
    _clean, build_continuity_messages, extract_continuity,
)


def test_continuity_messages_include_shots_and_character():
    messages = build_continuity_messages(
        "bedroom story",
        [{"id": "01", "prompt": "1girl, bedroom", "scene": "bedroom"}],
        "silver hair")
    payload = json.loads(messages[1]["content"])
    assert payload["character_tags"] == "silver hair"
    assert payload["shots"][0]["id"] == "01"


def test_clean_aligns_ledger_and_fills_missing():
    shots = [{"id": "01"}, {"id": "02"}, {"id": "03"}]
    data = {
        "character": "silver hair",
        "scene": "bedroom",
        "negative": "different hair",
        "ledger": [
            {"id": "02", "scene": "bedroom", "state": "nude"},
        ],
    }
    result = _clean(data, shots)
    assert result["character"] == "silver hair"
    assert [item["id"] for item in result["ledger"]] == ["01", "02", "03"]
    assert result["ledger"][1]["state"] == "nude"
    assert result["ledger"][0]["state"] == ""


def test_clean_falls_back_to_order_when_id_missing():
    shots = [{"id": "01"}, {"id": "02"}]
    result = _clean({"ledger": [{"state": "sweat"}, {"state": "torn"}]}, shots)
    assert result["ledger"][0]["state"] == "sweat"
    assert result["ledger"][1]["state"] == "torn"


def test_extract_continuity_rejects_empty_result():
    class EmptyClient:
        def chat_json(self, *args, **kwargs):
            return {"character": "", "scene": "", "negative": "", "ledger": []}

    with pytest.raises(ValueError):
        extract_continuity(EmptyClient(), "model", "premise", [{"id": "01"}])
