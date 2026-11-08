import json
from types import SimpleNamespace

from comfyui_generator.core.external_llm import (
    EXTERNAL_LLM_MODEL,
    ExternalLLMClient,
    _first_json_value,
    resolve_external_model,
)


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
    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_external_client_retries_without_doubling_budget(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)
    bodies = []

    def fake_urlopen(req, timeout):
        bodies.append(json.loads(req.data.decode("utf-8")))
        if len(bodies) == 1:
            return FakeResponse({
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": "{\"shots\": ["},
                }]
            })
        return FakeResponse({
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "{\"shots\": []}"},
            }]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = client.chat_json(
        "test-model", [{"role": "user", "content": "x"}],
        num_predict=4096, retries=1)
    assert result == {"shots": []}
    assert bodies[0]["max_tokens"] == 4096
    assert bodies[1]["max_tokens"] == 4096
    assert len(bodies[1]["messages"]) == 2
    assert "截断" in bodies[1]["messages"][-1]["content"]


def test_external_client_retries_on_incomplete_json_with_stop(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)
    bodies = []

    def fake_urlopen(req, timeout):
        bodies.append(json.loads(req.data.decode("utf-8")))
        if len(bodies) == 1:
            return FakeResponse({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "```json\n{\"shots\": ["},
                }]
            })
        return FakeResponse({
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "{\"shots\": []}"},
            }]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client.chat_json(
        "test-model", [{"role": "user", "content": "x"}],
        num_predict=4096, retries=1) == {"shots": []}
    assert len(bodies) == 2


def test_external_client_retries_after_read_timeout(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)
    attempts = []

    class TimeoutResponse(FakeResponse):
        def read(self):
            raise TimeoutError("The read operation timed out")

    def fake_urlopen(req, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            return TimeoutResponse({})
        return FakeResponse({
            "choices": [{"message": {"content": "{\"shots\": []}"}}]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = client.chat_json(
        "test-model", [{"role": "user", "content": "x"}],
        timeout=12, retries=1)
    assert result == {"shots": []}
    assert len(attempts) == 2


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


def test_first_json_value_ignores_trailing_braces():
    payload = '{"shots":[{"id":7,"prompt":"a: [\\"x\\"]"}]}' + " }" * 100
    assert json.loads(_first_json_value(payload))["shots"][0]["id"] == 7


def test_first_json_value_respects_braces_inside_strings():
    payload = 'noise {"a":"}{ }","b":[1]} trailing }}}'
    assert json.loads(_first_json_value(payload)) == {"a": "}{ }", "b": [1]}


def test_first_json_value_handles_array_root():
    payload = '[{"id": 1}, {"id": 2}]' + "]" * 40
    assert json.loads(_first_json_value(payload))[1]["id"] == 2


def test_external_client_accepts_json_with_trailing_braces(monkeypatch):
    cfg = SimpleNamespace(base_url="https://example.test/v1", api_key="",
                          model="test-model", timeout=30)
    client = ExternalLLMClient(cfg)
    content = '{"shots": [{"id": 7}]}' + " }" * 100

    def fake_urlopen(req, timeout):
        return FakeResponse({
            "choices": [{"finish_reason": "stop",
                         "message": {"content": content}}]
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client.chat_json(
        "test-model", [{"role": "user", "content": "x"}]) == {
            "shots": [{"id": 7}]}
