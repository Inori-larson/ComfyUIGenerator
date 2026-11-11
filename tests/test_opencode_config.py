import json

from comfyui_generator.core.opencode_config import (
    endpoint_for_model,
    iter_models,
    model_choices,
    load_opencode_config,
    _strip_json_comments,
)


def test_strip_json_comments():
    text = '{"a": 1, // note\n "b": "http://x", /* block */ "c": [1,2,],}'
    data = json.loads(_strip_json_comments(text))
    assert data == {"a": 1, "b": "http://x", "c": [1, 2]}


def test_load_config_with_comments(tmp_path):
    path = tmp_path / "opencode.json"
    path.write_text(
        '{\n  // provider list\n  "provider": {"p": {"name": "P", "options": '
        '{"baseURL": "https://api", "apiKey": "k"}, "models": '
        '{"m1": {"name": "Model One"}}}},\n}',
        encoding="utf-8")
    cfg = load_opencode_config(path)
    rows = iter_models(cfg)
    assert rows == [{
        "provider": "p", "provider_name": "P", "id": "m1",
        "name": "Model One", "base_url": "https://api", "api_key": "k",
    }]


def test_model_choices_excludes_local():
    cfg = {"provider": {
        "remote": {"name": "R", "options": {"baseURL": "https://api"},
                   "models": {"m1": {"name": "M1"}}},
        "local": {"name": "L", "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                  "models": {"lm": {"name": "LM"}}},
    }}
    choices = model_choices(cfg)
    assert choices == [("M1（R）", "m1")]


def test_model_choices_include_local_when_requested():
    cfg = {"provider": {
        "local": {"name": "L", "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                  "models": {"lm": {"name": "LM"}}},
    }}
    assert model_choices(cfg) == []
    assert model_choices(cfg, include_local=True) == [("LM（L）", "lm")]


def test_endpoint_for_model():
    cfg = {"provider": {
        "p": {"name": "P", "options": {"baseURL": "https://api", "apiKey": "k"},
              "models": {"m1": {}}},
    }}
    assert endpoint_for_model("m1", cfg) == {"base_url": "https://api",
                                            "api_key": "k"}
    assert endpoint_for_model("missing", cfg) == {}


def test_load_missing_config_returns_empty(tmp_path):
    assert load_opencode_config(tmp_path / "nope.json") == {}
