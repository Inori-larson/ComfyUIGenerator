import json
import struct

from comfyui_generator.core.civitai import (
    find_model_ids, words_from_html, words_from_payload,
)
from comfyui_generator.core.lora_info import tags_for_lora


def write_safetensors(path, metadata=None):
    header = {"__metadata__": metadata or {}}
    raw = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def test_find_ids_from_metadata_and_link(tmp_path):
    model = tmp_path / "model.safetensors"
    write_safetensors(model)
    (tmp_path / "model.metadata.json").write_text(json.dumps({
        "civitai": {"modelId": 123, "modelVersionId": 456},
    }), encoding="utf-8")
    assert find_model_ids(model) == (123, 456)

    model2 = tmp_path / "model2.safetensors"
    write_safetensors(model2)
    (tmp_path / "链接.txt").write_text(
        "https://civitai.red/models/2998536/character-set", encoding="utf-8")
    assert find_model_ids(model2) == (2998536, None)


def test_words_from_model_payload():
    payload = {
        "modelVersions": [
            {"id": 1, "trainedWords": ["hero", "red hair"]},
            {"id": 2, "trainedWords": ["alt_hero"]},
        ]
    }
    assert words_from_payload(payload) == ["hero", "red hair", "alt_hero"]
    assert words_from_payload(payload, version_id=2) == ["alt_hero"]


def test_words_from_html_next_data():
    page = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"version":{"trainedWords":["hero","blue eyes"]}}}}'
        "</script></html>"
    )
    assert words_from_html(page) == ["hero", "blue eyes"]


def test_words_from_html_trigger_section():
    page = "<div>Trigger Words: hero, red hair, school uniform</div>"
    assert words_from_html(page) == ["hero", "red hair", "school uniform"]


def test_tags_for_lora_uses_online_fetcher_when_no_metadata(tmp_path):
    model = tmp_path / "hero.safetensors"
    write_safetensors(model)

    def fake_fetcher(path, base):
        return ["hero_trigger", "red hair"], "https://civitai.red/models/1"

    tags, source = tags_for_lora(model, online=True, fetcher=fake_fetcher)
    assert tags == "hero_trigger, red hair"
    assert source.startswith("Civitai")
