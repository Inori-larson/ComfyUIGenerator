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
