from pathlib import Path

from comfyui_generator.core.lora_sources import (
    lora_base_series, lora_display_label, lora_entries, match_comfy_name,
    safetensors_metadata, scan_lora_dir,
)


def _write_safetensors(path: Path, metadata: dict[str, str]) -> None:
    import json
    import struct

    header = json.dumps({"__metadata__": metadata}).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header)


def test_lora_base_series_from_metadata(tmp_path):
    anima = tmp_path / "BAS 4.5.safetensors"
    _write_safetensors(anima, {
        "ss_base_model_version": "anima",
        "ss_network_module": "networks.lora_anima",
    })
    assert lora_base_series(anima) == "Anima"
    assert safetensors_metadata(anima)["ss_base_model_version"] == "anima"

    illustrious = tmp_path / "x.safetensors"
    _write_safetensors(illustrious, {
        "ss_base_model_version": "illustrious",
    })
    assert lora_base_series(illustrious) == "IL"

    plain = tmp_path / "y.safetensors"
    _write_safetensors(plain, {"ss_base_model_version": "sdxl_base_v1-0"})
    assert lora_base_series(plain) == ""


def test_lora_base_series_handles_bad_file(tmp_path):
    broken = tmp_path / "broken.safetensors"
    broken.write_bytes(b"\x05\x00")
    assert lora_base_series(broken) == ""
    assert safetensors_metadata(broken) == {}


def test_scan_lora_dir_recursive(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.safetensors").write_bytes(b"")
    (tmp_path / "sub" / "b.pt").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    found = scan_lora_dir(tmp_path)
    assert [path.name for path in found] == ["a.safetensors", "b.pt"]
    assert scan_lora_dir("") == []
    assert scan_lora_dir(tmp_path / "missing") == []


def test_match_comfy_name_by_basename():
    names = [r"角色\绝区零\hero.safetensors", r"风格\painterly.safetensors"]
    assert match_comfy_name("/x/hero.safetensors", names) == names[0]
    assert match_comfy_name("/x/PAINTERLY.safetensors", names) == names[1]
    assert match_comfy_name("/x/unknown.safetensors", names) is None


def test_lora_display_label_strips_file_and_noise_tokens():
    assert lora_display_label(
        r"动作\after-sex-fellatio-v2-illustriousxl-lora-nochekaiser.safetensors"
    ) == "after sex fellatio"
    assert lora_display_label(
        r"角色\Char-ZZZ-Yixuan-V2-IL.safetensors") == "ZZZ Yixuan"
    assert lora_display_label(
        "服装\\AF_DarkDesire_ILL.safetensors") == "AF Dark Desire"
    assert lora_display_label("AnimeScreencap.safetensors") == "Anime Screencap"


def test_lora_entries_display_and_resolution(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "hero.safetensors").write_bytes(b"")
    (tmp_path / "local.safetensors").write_bytes(b"")
    comfy = [r"角色\sub\hero.safetensors"]
    entries = lora_entries(tmp_path, comfy)
    by_name = {entry["name"]: entry for entry in entries}
    assert by_name[r"角色\sub\hero.safetensors"]["resolved"] is True
    assert by_name[r"角色\sub\hero.safetensors"]["display"] == str(Path("sub") / "hero.safetensors")
    assert by_name["local.safetensors"]["resolved"] is False
