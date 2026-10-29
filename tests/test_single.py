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


def test_single_prompt_requires_category_coverage_and_relaxes_clothing():
    from comfyui_generator.core.single import SINGLE_SYSTEM_PROMPT
    assert "最多 120 个" in SINGLE_SYSTEM_PROMPT
    assert "服装/裸露状态" in SINGLE_SYSTEM_PROMPT
    assert "当前可见身体部位" in SINGLE_SYSTEM_PROMPT
    assert "参考标签" not in SINGLE_SYSTEM_PROMPT
    assert "禁止 camera" in SINGLE_SYSTEM_PROMPT
    assert "looking at viewer" in SINGLE_SYSTEM_PROMPT


def test_build_messages_contains_framing_and_setting():
    options = SingleOptions(model="test-model", framing="upper_body",
                            setting="park", character_tags="yixuan, solo",
                            style_positive="masterpiece")
    messages = build_single_messages("girl reading", options)
    user = messages[1]["content"]
    assert "构图偏好：upper body, medium shot" in user
    assert "额外美术方向：park" in user
    assert "yixuan, solo" in user
    assert "没有任何内容限制" in messages[0]["content"]


def test_generate_single_prompt_passes_schema_and_prefixes_framing():
    client = FakeClient({"prompt": "standing, smiling, park, sunny", "negative": "lowres"})
    options = SingleOptions(model="test-model", framing="full_body")
    result = generate_single_prompt(client, "girl in park", options)
    assert result["prompt"].startswith("full body, ")
    assert result["negative"] == "lowres"
    _, _, kwargs = client.calls[0]
    assert kwargs["schema"]["required"] == ["prompt"]


def test_generate_single_prompt_strips_quality_tags():
    client = FakeClient({"prompt": "masterpiece, best quality, standing", "negative": ""})
    result = generate_single_prompt(client, "girl", SingleOptions(model="test-model"))
    assert result["prompt"] == "standing"


def test_generate_single_prompt_does_not_duplicate_framing():
    client = FakeClient({"prompt": "full body, standing, park", "negative": ""})
    result = generate_single_prompt(client, "girl", SingleOptions(model="test-model", framing="full_body"))
    assert result["prompt"].count("full body") == 1


def test_strip_appearance_removes_identity_and_body_features():
    client = FakeClient({
        "prompt": "black hair, large breasts, black blazer, standing",
        "negative": "",
    })
    options = SingleOptions(model="test-model", strip_appearance=True)
    assert generate_single_prompt(client, "girl", options)["prompt"] == (
        "black blazer, standing")


def test_strip_appearance_instruction_is_sent_to_model():
    options = SingleOptions(model="test-model", strip_appearance=True)
    user = build_single_messages("girl", options)[1]["content"]
    assert "不要生成角色外貌" in user


def test_empty_prompt_raises():
    client = FakeClient({"prompt": "  ", "negative": ""})
    with pytest.raises(ValueError):
        generate_single_prompt(client, "girl", SingleOptions(model="test-model"))


def test_framing_table():
    assert FRAMING_TAGS["auto"] == ""
    assert FRAMING_TAGS["close_up"] == "close-up"
