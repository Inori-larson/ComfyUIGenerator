from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from comfyui_generator.core.config import default_config, load_config
from comfyui_generator.core.llama_server import (
    LlamaServerClient, LlamaServerConfig, llama_server_command,
)
from comfyui_generator.core.ollama import (
    OllamaClient, OllamaConfig, OllamaService,
)


def test_ollama_names_are_llama_server_aliases():
    assert OllamaClient is LlamaServerClient
    assert OllamaConfig is LlamaServerConfig
    assert OllamaService.__name__ == "LlamaServerService"


def test_default_config_points_to_llama_server():
    cfg = default_config()
    assert cfg.ollama.port == 8080
    assert "llama-server.exe" in cfg.ollama.exe
    assert cfg.ollama.base_url == "http://127.0.0.1:8080"


def test_command_has_reasoning_and_mmproj():
    cfg = LlamaServerConfig(model="M.gguf", mmproj="mm.gguf")
    cmd = llama_server_command(cfg)
    assert "--reasoning" in cmd and cmd[cmd.index("--reasoning") + 1] == "on"
    assert "--mmproj" in cmd
    assert cmd[cmd.index("--reasoning-effort") + 1] == cfg.reasoning_effort
    assert "--jinja" in cmd


def test_client_uses_openai_chat_endpoint(monkeypatch):
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = LlamaServerClient("http://127.0.0.1:8080", timeout=5)
    result = client.chat_json("local", [{"role": "user", "content": "hi"}])
    assert result == {"ok": True}
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["max_tokens"] >= 1024
    assert "response_format" not in captured["body"]


def test_client_reports_empty_reasoning_output(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {
                "content": "", "reasoning_content": "thinking..."}}]}).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    client = LlamaServerClient("http://127.0.0.1:8080", timeout=5)
    try:
        client.chat("local", [{"role": "user", "content": "hi"}])
    except Exception as exc:
        assert "reasoning" in str(exc) or "空内容" in str(exc)
    else:
        raise AssertionError("empty content should raise")


def test_load_config_migrates_ollama_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "ollama": {
            "host": "127.0.0.1", "port": 11434,
            "exe": "C:/Program Files/Ollama/ollama.exe",
            "default_model": "qwen2.5:14b", "timeout": 240,
        },
        "external_llm": {"timeout": 240},
    }), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.ollama.port == 8080
    assert "llama-server.exe" in cfg.ollama.exe
    assert cfg.external_llm.timeout == 900
