from comfyui_generator.core.model_configs import (
    find_model_config, load_model_configs, normalize_model_name,
)


def test_load_model_configs_has_checkpoints():
    configs = load_model_configs()
    assert configs
    assert any("noobaiXLNAIXL_epsilonPred11Version" in item["model"]
               for item in configs)


def test_find_model_config_normalizes_paths():
    configs = [
        {"id": "a", "model": "WAI\\waiIllustriousSDXL_v170.safetensors"},
        {"id": "b", "model": "NoobAI-XL\\noobaiXLNAIXL_epsilonPred11Version.safetensors"},
    ]
    assert find_model_config(
        configs, "WAI/waiIllustriousSDXL_v170.safetensors")["id"] == "a"
    assert find_model_config(
        configs,
        "H:/models/checkpoints/NoobAI-XL/noobaiXLNAIXL_epsilonPred11Version.safetensors",
    )["id"] == "b"


def test_normalize_model_name():
    assert normalize_model_name("A/B\\c.SAFETENSORS") == "a\\b\\c.safetensors"


def test_wai_anima_preset_present():
    configs = load_model_configs()
    anima = next((c for c in configs if c.get("id") == "wai_anima_v1"), None)
    assert anima is not None
    assert anima["loader"] == "unet"
    assert anima["unet_name"] == "WAI_Anima\\waiANIMA_v10.safetensors"
    assert anima["clip_name"] == "WAI_Anima\\qwen_3_06b_base.safetensors"
    assert anima["vae_name"] == "WAI_Anima\\qwen_image_vae.safetensors"
    assert anima["clip_type"] == "qwen_image"
    assert anima["steps"] == 25
    assert anima["cfg"] == 4.5
    assert anima["sampler"] == "euler_ancestral"
    assert anima["scheduler"] == "normal"
    assert anima["width"] == 1024 and anima["height"] == 1344
    assert anima["hires"]["scale"] == 1.5
    assert anima["hires"]["denoise"] == 0.4
    assert anima["upscaler"] == "RealESRGAN_x4plus_anime_6B.pth"
