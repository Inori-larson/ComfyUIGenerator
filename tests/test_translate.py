from comfyui_generator.core.translate import (
    build_messages, build_to_tags_messages, translate_prompts, translate_tag_list, translate_to_tags,
)


class FakeClient:
    def __init__(self, translations):
        self.translations = translations
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return {"translations": list(self.translations)}


class FakeTagsClient:
    def __init__(self, prompts):
        self.prompts = prompts
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return {"prompts": list(self.prompts)}


def test_build_messages_is_chinese_and_numbered():
    messages = build_messages(["1girl, solo", "park, smile"])
    user = messages[1]["content"]
    assert "请逐条翻译以下 2 条提示词" in user
    assert "1. 1girl, solo" in user
    assert "2. park, smile" in user


def test_translate_prompts_returns_same_order():
    client = FakeClient(["一个女孩，单人", "公园，微笑"])
    result = translate_prompts(client, "test-model", ["1girl, solo", "park, smile"])
    assert result == ["一个女孩，单人", "公园，微笑"]
    assert client.calls[0][2]["schema"]["required"] == ["translations"]


def test_translate_to_tags_returns_booru_tags():
    client = FakeTagsClient(["1girl, solo", "park, smile"])
    result = translate_to_tags(client, "test-model", ["一个女孩，单人", "公园，微笑"])
    assert result == ["1girl, solo", "park, smile"]
    assert "中文提示词" in build_to_tags_messages(["测试"])[1]["content"]


def test_translate_tag_list_uses_cache(tmp_path):
    cache = tmp_path / "tags.json"
    client = FakeClient(["1girl", "单人"])
    result = translate_tag_list(client, "test-model", ["1girl", "solo"], str(cache))
    assert result == {"1girl": "1girl", "solo": "单人"}
    assert len(client.calls) == 1

    again = FakeClient(["不应该再调用"])
    result = translate_tag_list(again, "test-model", ["1girl", "solo"], str(cache))
    assert result == {"1girl": "1girl", "solo": "单人"}
    assert again.calls == []
