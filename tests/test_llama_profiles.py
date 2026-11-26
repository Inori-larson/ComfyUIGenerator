from __future__ import annotations

from comfyui_generator.core.config import load_config
from comfyui_generator.core.llama_server import (
    LlamaServerConfig, llama_server_command,
)


def test_active_profile_overrides_defaults():
    cfg = LlamaServerConfig(
        model="default.gguf", gpu_layers=10, profile="qwen",
        profiles=[{"name": "qwen", "model": "qwen.gguf", "gpu_layers": 99}],
    )
    r = cfg.resolved()
    assert r["model"] == "qwen.gguf"
    assert r["gpu_layers"] == 99


def test_unknown_profile_falls_back_to_defaults():
    cfg = LlamaServerConfig(model="default.gguf", profile="missing",
                            profiles=[{"name": "muse", "model": "muse.gguf"}])
    assert cfg.resolved()["model"] == "default.gguf"


def test_command_uses_selected_profile(tmp_path):
    cfg = LlamaServerConfig(
        exe="server.exe", profile="muse",
        profiles=[{
            "name": "muse", "model": "muse.gguf", "mmproj": "vision.gguf",
            "gpu_layers": 32, "context": 16384,
        }],
    )
    cmd = llama_server_command(cfg)
    assert cmd[cmd.index("-m") + 1] == "muse.gguf"
    assert cmd[cmd.index("-ngl") + 1] == "32"
    assert cmd[cmd.index("--mmproj") + 1] == "vision.gguf"


def test_saved_config_has_two_switchable_profiles():
    cfg = load_config()
    names = [p["name"] for p in cfg.ollama.profiles]
    assert "muse" in names and "qwen3.8-27b" in names
    assert cfg.ollama.profile in names
