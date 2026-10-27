from pathlib import Path

from comfyui_generator.core.lora_sources import (
    lora_entries, match_comfy_name, scan_lora_dir,
)


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
