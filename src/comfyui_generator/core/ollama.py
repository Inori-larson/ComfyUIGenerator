"""Minimal Ollama client (chat, model list, unload)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    pass


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(f"Cannot reach Ollama at {url}: {exc.reason}") from exc


def _get(url: str, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OllamaError(f"Cannot reach Ollama at {url}: {exc.reason}") from exc


def extract_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return text[start:end + 1]


class OllamaClient:
    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def tags(self) -> list[dict[str, Any]]:
        return _get(self.base_url + "/api/tags", self.timeout).get("models", [])

    def model_names(self) -> list[str]:
        return [m.get("name", "") for m in self.tags()]

    def ps(self) -> list[dict[str, Any]]:
        try:
            return _get(self.base_url + "/api/ps", self.timeout).get("models", [])
        except OllamaError:
            return []

    def chat(self, model: str, messages: list[dict[str, str]], *,
             schema: dict[str, Any] | None = None,
             temperature: float = 0.8,
             top_p: float = 0.9,
             num_predict: int = 2048,
             num_ctx: int = 8192,
             keep_alive: str = "5m",
             timeout: float = 900.0) -> str:
        options = {
            "temperature": float(temperature),
            "top_p": float(top_p),
            "num_predict": int(num_predict),
            "num_ctx": int(num_ctx),
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive,
            "options": options,
        }
        if schema is not None:
            payload["format"] = schema
        out = _post(self.base_url + "/api/chat", payload, timeout)
        message = out.get("message") or {}
        content = message.get("content") or out.get("response") or ""
        if not content:
            raise OllamaError(f"Empty response from Ollama: {out}")
        return content

    def chat_json(self, model: str, messages: list[dict[str, str]], *,
                  schema: dict[str, Any] | None = None,
                  retries: int = 1,
                  **kwargs: Any) -> dict[str, Any]:
        last = ""
        convo = list(messages)
        for attempt in range(retries + 1):
            last = self.chat(model, convo, schema=schema, **kwargs)
            try:
                data = json.loads(extract_json(last))
                if isinstance(data, dict):
                    return data
                raise ValueError("JSON root is not an object")
            except (ValueError, json.JSONDecodeError) as exc:
                if attempt >= retries:
                    break
                convo = convo + [
                    {"role": "assistant", "content": last},
                    {"role": "user", "content": f"That was invalid JSON ({exc}). Return ONLY the JSON object."},
                ]
        raise OllamaError("Model did not return usable JSON:\n" + last[:2000])

    def unload(self, model: str) -> None:
        try:
            _post(self.base_url + "/api/generate", {"model": model, "keep_alive": 0}, 30)
        except OllamaError:
            pass
