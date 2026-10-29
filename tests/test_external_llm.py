import json
from types import SimpleNamespace

from comfyui_generator.core.external_llm import ExternalLLMClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_external_client_parses_openai_json(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="secret",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse({
            "choices": [{"message": {"content": "```json\n{\"shots\": []}\n```"}}]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = client.chat_json("test-model", [{"role": "user", "content": "x"}],
                              timeout=10)
    assert result == {"shots": []}
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["body"]["model"] == "test-model"


def test_external_client_accepts_array_root(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)

    def fake_urlopen(req, timeout):
        return FakeResponse({
            "choices": [{"message": {"content": "```json\n[{\"id\": \"01\"}]\n```"}}]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client.chat_json("test-model", [{"role": "user", "content": "x"}]) == {
        "shots": [{"id": "01"}]}
