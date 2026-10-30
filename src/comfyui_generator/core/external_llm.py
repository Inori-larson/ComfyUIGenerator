"""Minimal OpenAI-compatible chat client for external prompt generation."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


class ExternalLLMError(RuntimeError):
    pass


class ExternalLLMClient:
    def __init__(self, cfg: Any):
        self.cfg = cfg

    def _url(self) -> str:
        base = str(getattr(self.cfg, "base_url", "") or "").strip().rstrip("/")
        if not base:
            raise ExternalLLMError("External LLM base_url is empty.")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def chat_json(self, model: str, messages: list[dict[str, str]], *,
                  schema: dict[str, Any] | None = None,
                  temperature: float = 0.8,
                  num_predict: int = 4096,
                  num_ctx: int = 0,
                  keep_alive: str = "",
                  timeout: float | None = None,
                  retries: int = 0,
                  **kwargs: Any) -> dict[str, Any]:
        target = str(model or getattr(self.cfg, "model", "") or "").strip()
        if not target:
            raise ExternalLLMError("External LLM model is empty.")
        key = str(getattr(self.cfg, "api_key", "") or os.environ.get("OPENAI_API_KEY", "")).strip()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        effective_timeout = float(timeout or getattr(self.cfg, "timeout", 240.0) or 240.0)
        last = ""
        finish = ""
        convo = list(messages)
        for attempt in range(max(0, int(retries)) + 1):
            payload = {
                "model": target,
                "messages": convo,
                "temperature": float(temperature),
                "max_tokens": max(256, min(16384, int(num_predict or 4096))),
                "stream": False,
            }
            if getattr(self.cfg, "disable_thinking", True):
                payload["thinking"] = {"type": "disabled"}
            req = urllib.request.Request(
                self._url(), data=json.dumps(payload).encode("utf-8"),
                headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:2000]
                if exc.code >= 500 and attempt < retries:
                    time.sleep(3 + attempt * 4)
                    continue
                raise ExternalLLMError("External LLM HTTP %s: %s" % (exc.code, detail)) from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    time.sleep(3 + attempt * 4)
                    continue
                raise ExternalLLMError("Cannot reach external LLM: %s" % exc.reason) from exc
            choices = data.get("choices") or []
            choice = choices[0] if choices else {}
            message = choice.get("message") or {}
            finish = str(choice.get("finish_reason") or "")
            last = str(message.get("content") or "")
            try:
                text = last.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.startswith("json"):
                        text = text[4:]
                text = text.strip()
                if text.startswith("["):
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return {"shots": parsed}
                if "{" not in text and "[" in text:
                    start = text.find("[")
                    end = text.rfind("]")
                    if start >= 0 and end > start:
                        parsed = json.loads(text[start:end + 1])
                        if isinstance(parsed, list):
                            return {"shots": parsed}
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    text = text[start:end + 1]
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    return {"shots": parsed}
            except (ValueError, json.JSONDecodeError):
                pass
            if attempt < retries:
                convo = list(messages)
                if last.strip():
                    convo += [
                        {"role": "assistant", "content": last},
                        {"role": "user", "content": "上一条 JSON 不完整或无效。"
                         "请重新返回完整、可解析的 JSON，不要解释，不要 markdown。"},
                    ]
                else:
                    convo += [{"role": "user", "content": "上一条响应为空。"
                               "请只返回完整、可解析的 JSON。"}]
        raise ExternalLLMError(
            "External LLM did not return usable JSON (finish=%s): %s" % (
                finish, last[:1000]))

    def unload(self, model: str = "") -> None:
        return None
