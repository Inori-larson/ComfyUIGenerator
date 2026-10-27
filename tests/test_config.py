from dataclasses import asdict

from comfyui_generator.core.config import AppConfig, ComfyConfig, load_config, save_config


def test_urls_plain_host():
    cfg = ComfyConfig(host="127.0.0.1", port=8000)
    assert cfg.base_url == "http://127.0.0.1:8000"
    assert cfg.ws_url == "ws://127.0.0.1:8000/ws"


def test_urls_with_scheme_and_port():
    cfg = ComfyConfig(host="http://192.168.1.5:8188", port=8000)
    assert cfg.base_url == "http://192.168.1.5:8188"


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig(storage_root=str(tmp_path / "data"))
    cfg.comfy.port = 8123
    cfg.generation.shots = 9
    cfg.ui.language = "en-US"
    cfg.lora.character_dir = r"D:\loras\char"
    cfg.lora.style_dir = r"D:\loras\style"
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.comfy.port == 8123
    assert loaded.generation.shots == 9
    assert loaded.ui.language == "en-US"
    assert loaded.lora.character_dir == r"D:\loras\char"
    assert loaded.lora.style_dir == r"D:\loras\style"
    assert loaded.storage_root == str(tmp_path / "data")


def test_resolved_paths_follow_base_dir():
    cfg = ComfyConfig(base_dir=r"H:\ComfyUIData")
    paths = cfg.resolved_paths()
    assert paths["input_dir"].endswith("input")
    assert paths["output_dir"].endswith("output")
    assert paths["user_dir"].endswith("user")


def test_to_dict_is_plain_json():
    data = asdict(AppConfig())
    assert isinstance(data["comfy"], dict)
    assert data["comfy"]["preview_method"] == "latent2rgb"
    assert data["generation"]["variants"] == 1
