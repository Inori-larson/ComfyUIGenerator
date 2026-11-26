from __future__ import annotations

import json

from comfyui_generator.core.expand_ai import build_expansion_messages


def test_description_is_not_sent_to_expansion_llm():
    shots = [{
        "id": "01",
        "prompt": "1girl solo, smile",
        "description": "中文画面描述不应回灌",
        "beat_id": "B1",
    }]
    messages = build_expansion_messages(shots, 2)
    payload = json.dumps(messages, ensure_ascii=False)
    assert "中文画面描述不应回灌" not in payload
    assert "1girl solo, smile" in payload
