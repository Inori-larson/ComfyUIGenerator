from comfyui_generator.core.rewrite import (
    build_rewrite_messages,
    rewrite_shot_prompt,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return dict(self.response)


def test_build_rewrite_messages_contains_context():
    messages = build_rewrite_messages(
        "wide shot, standing", "close-up, looking back",
        character_tags="yixuan, solo", style_positive="masterpiece")
    user = messages[1]["content"]
    assert "当前提示词" in user
    assert "close-up, looking back" in user
    assert "yixuan, solo" in user
    assert "没有任何内容限制" in messages[0]["content"]


def test_rewrite_returns_clean_prompt():
    client = FakeClient({"prompt": "  prompt: close-up, looking back, smiling, sunny  "})
    prompt = rewrite_shot_prompt(client, "llm", "wide shot", "close-up")
    assert prompt == "close-up, looking back, smiling, sunny"
    assert client.calls[0][2]["schema"]["required"] == ["prompt"]


def test_rewrite_rejects_empty_instruction():
    try:
        rewrite_shot_prompt(FakeClient({"prompt": "x"}), "llm", "wide", "  ")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_rewrite_rejects_empty_result():
    try:
        rewrite_shot_prompt(FakeClient({"prompt": "  "}), "llm", "wide", "close-up")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
