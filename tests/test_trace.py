import json

from comfyui_generator.core.trace import trace_event, trace_session


def test_trace_session_writes_structured_and_text_logs(tmp_path):
    with trace_session(tmp_path, "story", {"premise": "test"}) as session:
        trace_event("custom", {"value": {1, 2}})
    assert session.jsonl_path.is_file()
    assert session.text_path.is_file()
    lines = [json.loads(line) for line in
             session.jsonl_path.read_text(encoding="utf-8").splitlines()]
    events = [line["event"] for line in lines]
    assert "session.start" in events
    assert "custom" in events
    assert "session.end" in events
    assert events.index("session.start") < events.index("custom")
