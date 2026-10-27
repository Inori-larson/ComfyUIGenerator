import pytest

from comfyui_generator.core.single import (
    FRAMING_TAGS,
    SingleOptions,
    build_single_messages,
    generate_single_prompt,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return dict(self.response)


def test_build_messages_contains_framing_and_setting():
    options = SingleOptions(model="qwen", framing="upper_body",
                            setting="park", character_tags="yixuan, solo",
                            style_positive="masterpiece")
    messages = build_single_messages("girl reading", options)
    user = messages[1]["content"]
    assert "Framing preference: upper body, medium shot" in user
    assert "Preferred atmosphere" not in user
    assert "Extra art direction: park" in user
    assert "yixuan, solo" in user
    assert "bright, cheerful" not in messages[0]["content"]


def test_generate_single_prompt_passes_schema_and_prefixes_framing():
    client = FakeClient({"prompt": "standing, smiling, park, sunny", "negative": "lowres"})
    options = SingleOptions(model="qwen", framing="full_body")
    result = generate_single_prompt(client, "girl in park", options)
    assert result["prompt"].startswith("full body, ")
    assert result["negative"] == "lowres"
    _, _, kwargs = client.calls[0]
    assert kwargs["schema"]["required"] == ["prompt"]


def test_generate_single_prompt_does_not_duplicate_framing():
    client = FakeClient({"prompt": "full body, standing, park", "negative": ""})
    result = generate_single_prompt(client, "girl", SingleOptions(model="qwen", framing="full_body"))
    assert result["prompt"].count("full body") == 1


def test_empty_prompt_raises():
    client = FakeClient({"prompt": "  ", "negative": ""})
    with pytest.raises(ValueError):
        generate_single_prompt(client, "girl", SingleOptions(model="qwen"))


def test_framing_table():
    assert FRAMING_TAGS["auto"] == ""
    assert FRAMING_TAGS["close_up"] == "close-up"
