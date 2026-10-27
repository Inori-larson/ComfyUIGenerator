import json
import struct

from comfyui_generator.core.lora_info import (
    default_activation, extract_tags, is_style_lora, lora_tag_info,
    preset_tags, tags_for_lora,
)


def write_safetensors(path, metadata):
    header = {"__metadata__": metadata}
    raw = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def test_extract_tags_lists_everything():
    meta = {
        "modelspec.title": "hero",
        "ss_tag_frequency": json.dumps({"dataset": {
            "1girl": 100, "hero": 100, "red hair": 80, "blue hair": 5,
            "nude": 60, "glasses": 60, "pubic hair": 40, "ring": 70,
        }}),
    }
    tags = extract_tags(meta, "hero.safetensors")
    assert tags[0] == "hero"
    for expected in ("1girl", "red hair", "blue hair", "nude", "glasses", "pubic hair", "ring"):
        assert expected in tags


def test_extract_tags_includes_explicit_triggers_first():
    meta = {
        "modelspec.trigger_words": "hero_trigger, blonde hair",
        "ss_tag_frequency": json.dumps({"d": {"red hair": 10}}),
    }
    tags = extract_tags(meta, "x.safetensors")
    assert tags[:2] == ["hero_trigger", "blonde hair"]
    assert "red hair" in tags


def test_style_classification_only():
    assert is_style_lora("AnimeScreencap\\anime_screencap-IllustriousV2.safetensors")
    assert is_style_lora("Sysdeep\\hrf1style_IllustriousXL_v1.safetensors")
    assert not is_style_lora("角色\\绝区零\\仪玄\\Char-ZZZ-Yixuan-V2-IL.safetensors")


def test_sidecar_fallback_when_no_metadata(tmp_path):
    model = tmp_path / "hero.safetensors"
    write_safetensors(model, {})
    (tmp_path / "hero.metadata.json").write_text(json.dumps({
        "trainedWords": ["hero_trigger", "red hair"],
    }), encoding="utf-8")
    tags, source = tags_for_lora(model)
    assert "hero_trigger" in tags
    assert "red hair" in tags
    assert source == "LoRA 伴随文件"


def test_metadata_preferred_over_sidecar(tmp_path):
    model = tmp_path / "hero.safetensors"
    write_safetensors(model, {
        "modelspec.title": "hero",
        "ss_tag_frequency": json.dumps({"d": {"hero": 50, "black hair": 40}}),
    })
    (tmp_path / "hero.metadata.json").write_text(json.dumps({
        "trainedWords": ["sidecar_only"],
    }), encoding="utf-8")
    tags, source = tags_for_lora(model)
    assert "hero" in tags
    assert "black hair" in tags
    assert "sidecar_only" not in tags
    assert source == "safetensors 内置元数据"


def test_preset_tags_still_reads_bundled_preset():
    tags = preset_tags(r"角色\绝区零\仪玄\Char-ZZZ-Yixuan-V2-IL.safetensors")
    assert "yixuan" in tags
    assert "hairclip" in tags


def test_default_activation_prefers_title_tag():
    meta = {"modelspec.title": "hero",
            "ss_tag_frequency": '{"d":{"hero":100,"1girl":100,"red hair":80}}'}
    reference = extract_tags(meta, "hero.safetensors")
    assert default_activation(meta, "hero.safetensors", reference) == ["hero"]


def test_default_activation_does_not_filter_content():
    meta = {"ss_tag_frequency": '{"d":{"1girl":100,"red hair":80,"nude":90,"blue sky":20}}'}
    reference = extract_tags(meta, "x.safetensors")
    assert default_activation(meta, "x.safetensors", reference) == reference


def test_lora_tag_info_shape(tmp_path):
    model = tmp_path / "hero.safetensors"
    write_safetensors(model, {"ss_tag_frequency": '{"d":{"hero":10,"red hair":8}}'})
    info = lora_tag_info(model)
    assert info["reference"] == ["hero", "red hair"]
    assert info["triggers"] == ["hero"]
    assert info["source"] == "safetensors 内置元数据"
