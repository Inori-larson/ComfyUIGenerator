from __future__ import annotations

import pytest

from comfyui_generator.core.storyboard import (
    STORYBOARD_SCHEMA,
    StoryboardOptions,
    build_storyboard_messages,
    extract_premise_beats,
    generate_storyboard,
    normalize_shot_casts,
    normalize_shots,
    parse_character_profiles,
    premise_from_json,
    shots_from_json,
    slugify,
)

from conftest import ScriptedLLMClient


def make_options(**kwargs):
    base = dict(model="deepseek", shots=3)
    base.update(kwargs)
    return StoryboardOptions(**base)


def shot(id, prompt, description="desc"):
    return {"id": id, "prompt": prompt, "description": description}


def raw(*items):
    return {"shots": list(items)}


def test_messages_request_shot_count_and_json():
    msgs = build_storyboard_messages("剧情内容", 4)
    assert len(msgs) == 2
    assert "剧情内容" in msgs[1]["content"]
    assert "目标镜数：4" in msgs[1]["content"]


def test_messages_include_clothing_rules():
    system = build_storyboard_messages("剧情内容", 2)[0]["content"]
    assert "只能使用用户给出的初始服装" in system
    assert "颜色" in system
    assert "不允许全脱" in system
    assert "禁止跳变" in system
    assert "体液状态" in system


def test_messages_strip_appearance():
    msgs = build_storyboard_messages("p", 2, strip_appearance=True)
    assert "LoRA" in msgs[1]["content"]


def test_normalize_keeps_only_core_fields():
    out = normalize_shots(raw(
        shot("01", "1girl, solo, smile", "第一个"),
        shot("02", "1girl, 1boy, hug", "第二个")), 2)
    assert [s["id"] for s in out] == ["01", "02"]
    assert out[0]["prompt"] == "1girl, solo, smile"
    assert out[0]["description"] == "第一个"
    assert out[0]["name"] == "shot_01"
    assert "cast" not in out[0]


def test_normalize_derives_name_and_renumbers():
    out = normalize_shots(raw(
        {"id": "9", "prompt": "1girl", "description": "x"},
        {"id": "x", "prompt": "1boy", "description": "y"}), 0)
    assert out[0]["id"] == "01"
    assert out[0]["name"] == "shot_01"
    assert out[1]["id"] == "02"


def test_normalize_drops_empty_prompt():
    out = normalize_shots(raw(
        shot("01", "1girl", "a"),
        shot("02", "   ", "b"),
        shot("03", "1boy", "c")), 3)
    assert [s["id"] for s in out] == ["01", "02"]


def test_normalize_strips_cjk_from_prompt():
    out = normalize_shots(raw(shot("01", "1girl, 中文, smile", "d")), 1)
    assert out[0]["prompt"] == "1girl, smile"


def test_normalize_no_shots_raises():
    with pytest.raises(ValueError):
        normalize_shots({"shots": []}, 1)
    with pytest.raises(ValueError):
        normalize_shots({}, 1)


def test_generate_calls_client_with_schema():
    client = ScriptedLLMClient([raw(
        shot("01", "1girl", "a"),
        shot("02", "1girl", "b"),
        shot("03", "1girl", "c"))])
    out = generate_storyboard(client, "premise", make_options())
    assert len(out) == 3
    model, messages, kwargs = client.calls[0]
    assert model == "deepseek"
    assert kwargs["schema"] is STORYBOARD_SCHEMA
    assert kwargs["retries"] == 1


def test_generate_returns_all_requested_shots():
    client = ScriptedLLMClient([raw(
        shot("01", "1girl", "a"), shot("02", "1girl", "b"))])
    out = generate_storyboard(client, "p", make_options(shots=2))
    assert len(out) == 2


def test_generate_uses_initial_when_sufficient():
    initial = [
        {"id": "01", "name": "shot_01", "prompt": "1girl"},
        {"id": "02", "name": "shot_02", "prompt": "1boy"},
    ]
    client = ScriptedLLMClient([])
    out = generate_storyboard(client, "p", make_options(shots=2),
                              initial_shots=initial)
    assert client.calls == []
    assert [s["id"] for s in out] == ["01", "02"]


def test_slugify():
    assert slugify("Hello World!") == "hello_world"
    assert slugify("") == ""
    assert slugify("", "fb") == "fb"


def test_extract_premise_beats():
    beats = extract_premise_beats("1. 第一个\n2. 第二个\n无关")
    assert beats == ["第一个", "第二个"]
    assert extract_premise_beats("没有编号") == []


def test_normalize_shot_casts_noop():
    shots = [{"cast": "1girl"}]
    assert normalize_shot_casts(shots) is None
    assert shots[0]["cast"] == "1girl"


def test_parse_character_profiles():
    premise = (
        "角色：hor1kita\n"
        "外貌身材：black hair\n"
        "初始服装：school uniform, red jacket\n"
        "剧情：故事")
    profiles = parse_character_profiles(premise)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.appearance == ["black hair"]
    assert p.initial_clothing == ["school uniform", "red jacket"]


def test_premise_from_json():
    assert premise_from_json({"premise": "x"}) == "x"
    assert premise_from_json({"story": "y"}) == "y"
    assert premise_from_json({"nested": 1}) == ""


def test_shots_from_json_array():
    out = shots_from_json([
        {"id": "01", "prompt": "1girl"},
        {"id": "02", "prompt": "1boy"},
    ])
    assert [s["id"] for s in out] == ["01", "02"]


def test_shots_from_json_shots_key():
    out = shots_from_json({"shots": [{"prompt": "1girl, smile"}]})
    assert out[0]["id"] == "01"
    assert out[0]["prompt"] == "1girl, smile"


def test_shots_from_json_string_shots():
    out = shots_from_json(["just tags"])
    assert out[0]["prompt"] == "just tags"


def test_shots_from_json_empty_raises():
    with pytest.raises(ValueError):
        shots_from_json({"shots": []})
