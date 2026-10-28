from comfyui_generator.core.storyboard import (
    SYSTEM_PROMPT,
    build_messages,
    clean_prompt,
    normalize,
    slugify,
    StoryboardOptions,
)


def test_normalize_renumbers_and_dedupes_names():
    raw = {"shots": [
        {"name": "shot", "prompt": "wide shot, standing"},
        {"name": "shot", "prompt": "close-up, smiling"},
        {"name": "", "prompt": "  "},
        {"name": "third", "prompt": "medium shot, running"},
    ]}
    shots = normalize(raw, 10, "fallback")
    assert [shot["id"] for shot in shots] == ["01", "02", "03"]
    assert shots[0]["name"] == "shot"
    assert shots[1]["name"] == "shot_2"
    assert shots[2]["name"] == "third"


def test_normalize_start_index_and_existing_names():
    raw = {"shots": [{"name": "a", "prompt": "x"}, {"name": "b", "prompt": "y"}]}
    shots = normalize(raw, 2, "fallback", start=5, used_names=["a"])
    assert [shot["id"] for shot in shots] == ["05", "06"]
    assert shots[0]["name"] == "a_2"


def test_build_messages_contains_setting_and_context():
    messages = build_messages("cat on roof", 2, "yixuan, solo", "masterpiece",
                              "sunny park", [], 2)
    user = messages[1]["content"]
    assert "场景 / 美术方向：sunny park" in user
    assert "本次生成镜头数" in user
    assert "角色：yixuan, solo" in user
    assert "没有任何内容限制" in SYSTEM_PROMPT


def test_build_messages_with_prior_and_beats():
    prior = [{"id": "01", "prompt": "wide shot, standing"}]
    messages = build_messages("story", 2, "", "", "", prior, 3,
                              ["first beat", "second beat"])
    user = messages[1]["content"]
    assert "第 2-3 镜，共 3 镜" in user
    assert "已有镜头" in user
    assert "first beat" in user


def test_clean_and_slug():
    assert clean_prompt("  prompt: wide shot,\n standing.  ") == "wide shot, standing"
    assert slugify("雨夜, girl!") == "girl"
    assert slugify("!!!", "fallback") == "fallback"


def test_storyboard_options_defaults():
    opts = StoryboardOptions(model="test-model")
    assert opts.shots == 6
    assert opts.chunk == 12
    assert opts.setting == ""
    opts.log("noop")


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat_json(self, model, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {"shots": [
            {"name": "next", "prompt": "medium shot, walking"},
            {"name": "last", "prompt": "close-up, smiling"},
        ]}


def test_generate_with_initial_shot_keeps_it():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "anchor", "prompt": "wide shot, standing"}]
    options = StoryboardOptions(model="test-model", shots=3)
    shots = generate_storyboard(client, "a walk", options, initial_shots=initial)
    assert len(shots) == 3
    assert shots[0] == initial[0]
    assert [shot["id"] for shot in shots] == ["01", "02", "03"]
    assert len(client.calls) == 1
    assert "本次生成镜头数：2" in client.calls[0][0][1]["content"]


def test_generate_with_initial_and_no_extra_shots_does_not_call_model():
    from comfyui_generator.core.storyboard import generate_storyboard
    client = FakeClient()
    initial = [{"id": "01", "name": "only", "prompt": "wide shot"}]
    shots = generate_storyboard(client, "x", StoryboardOptions(model="test-model", shots=1),
                                initial_shots=initial)
    assert shots == initial
    assert client.calls == []
