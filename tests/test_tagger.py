from comfyui_generator.core.tagger import build_messages, select_tags
from comfyui_generator.core.tags import estimate_tokens, limit_tags


class FakeClient:
    def __init__(self, tags):
        self.tags = tags
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return {"tags": list(self.tags)}


def test_build_messages_contains_required_and_reference():
    messages = build_messages(["hero", "red hair"], "park",
                              "current", ["hero"])
    user = messages[1]["content"]
    assert "角色标签" in user
    assert "hero" in user
    assert "参考标签" in user


def test_select_tags_keeps_required_and_does_not_filter_content():
    reference = ["hero", "red hair", "yellow dress", "1girl", "3d", "nude",
                 "looking at viewer", "blue sky", "park"]
    client = FakeClient(["invented", "1girl", "3d", "nude", "blue sky",
                         "park", "yellow dress", "looking at viewer", "hero"])
    tags = select_tags(client, "m", reference, "park", required=["hero"])
    assert tags[0] == "hero"
    for expected in ("blue sky", "park", "yellow dress", "1girl", "3d", "nude"):
        assert expected in tags
    assert "invented" not in tags


def test_select_tags_empty_output_raises():
    client = FakeClient([])
    try:
        select_tags(client, "m", ["hero"], "x", required=[])
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_estimate_tokens_grows_with_tags():
    assert estimate_tokens("") == 2
    assert estimate_tokens("hero, red hair") > estimate_tokens("hero")
    assert estimate_tokens(["a", "b", "c"]) > estimate_tokens("a, b")


def test_limit_tags_dedupes_and_caps_at_100():
    assert limit_tags("a, b, a, c, d") == "a, b, c, d"
    assert limit_tags("") == ""
    tags = ", ".join("tag%d" % index for index in range(150))
    assert len(limit_tags(tags).split(", ")) == 100
