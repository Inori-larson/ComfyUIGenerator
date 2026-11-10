"""Minimal OpenAI-compatible chat client for external prompt generation."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

EXTERNAL_LLM_MODEL = "doubao-seed-2.1-pro"


def resolve_external_model(configured: Any = None, supplied: str = "") -> str:
    if configured is not None:
        value = str(getattr(configured, "model", configured) or "").strip()
        if value:
            return value
    return str(supplied or EXTERNAL_LLM_MODEL).strip() or EXTERNAL_LLM_MODEL


def _first_json_value(text: str) -> str:
    """Return the first complete JSON object/array, ignoring trailing junk.

    Braces are balanced while respecting string literals and escapes, so a
    run of stray closing braces appended by the model is not included.
    """
    open_for = {"{": "}", "[": "]"}
    for i, ch in enumerate(text):
        if ch not in open_for:
            continue
        close = open_for[ch]
        depth = 0
        in_string = False
        escaped = False
        for j in range(i, len(text)):
            cur = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif cur == "\\":
                    escaped = True
                elif cur == '"':
                    in_string = False
                continue
            if cur == '"':
                in_string = True
            elif cur == ch:
                depth += 1
            elif cur == close:
                depth -= 1
                if depth == 0:
                    return text[i:j + 1]
        break
    return text


class ExternalLLMError(RuntimeError):
    pass


def _urlopen_with_deadline(req: Any, wall_timeout: float,
                           socket_timeout: float) -> bytes:
    """Fetch with a hard wall-clock cap covering connect + full response read.

    urllib's own timeout applies per socket operation, so a server that keeps
    the connection open without completing the response can stall far beyond
    it. The worker thread is daemonized; the caller is unblocked at the
    deadline regardless of server behavior.
    """
    result: dict[str, Any] = {}
    done = threading.Event()

    def worker() -> None:
        try:
            with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                result["data"] = resp.read()
        except BaseException as exc:
            result["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    if not done.wait(timeout=wall_timeout):
        raise TimeoutError(
            "request exceeded wall-clock timeout %.0fs" % wall_timeout)
    if "error" in result:
        raise result["error"]
    return result["data"]


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

    @staticmethod
    def _model_identity(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "model"):
            value = getattr(value, "model")
        return str(value or "").strip()

    def chat_json(self, model: str, messages: list[dict[str, str]], *,
                  schema: dict[str, Any] | None = None,
                  temperature: float = 0.8,
                  num_predict: int = 4096,
                  num_ctx: int = 0,
                  keep_alive: str = "",
                  timeout: float | None = None,
                  retries: int = 0,
                  **kwargs: Any) -> dict[str, Any]:
        target = resolve_external_model(self.cfg, model)
        key = str(getattr(self.cfg, "api_key", "") or os.environ.get("OPENAI_API_KEY", "")).strip()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        effective_timeout = float(timeout or getattr(self.cfg, "timeout", 240.0) or 240.0)
        wall_timeout = max(1.0, effective_timeout)
        socket_timeout = max(1.0, min(wall_timeout, max(15.0, wall_timeout / 2)))
        last = ""
        finish = ""
        token_budget = max(256, min(32768, int(num_predict or 4096)))
        json_forced = bool(schema)
        for attempt in range(max(0, int(retries)) + 1):
            payload = {
                "model": target,
                "messages": messages,
                "temperature": float(temperature),
                "max_tokens": token_budget,
                "stream": False,
            }
            if json_forced:
                payload["response_format"] = {"type": "json_object"}
            if getattr(self.cfg, "disable_thinking", True):
                payload["thinking"] = {"type": "disabled"}
            req = urllib.request.Request(
                self._url(), data=json.dumps(payload).encode("utf-8"),
                headers=headers, method="POST")
            try:
                raw = _urlopen_with_deadline(
                    req, wall_timeout, socket_timeout)
                data = json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:2000]
                if exc.code == 400 and json_forced:
                    json_forced = False
                    continue
                if exc.code >= 500 and attempt < retries:
                    time.sleep(3 + attempt * 4)
                    continue
                raise ExternalLLMError("External LLM HTTP %s: %s" % (exc.code, detail)) from exc
            except (TimeoutError, socket.timeout) as exc:
                if attempt < retries:
                    time.sleep(3 + attempt * 4)
                    continue
                raise ExternalLLMError(
                    "External LLM request timed out after %.0fs: %s" % (
                        effective_timeout, exc)) from exc
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
                    text = text[3:]
                    if text[:4].lower() == "json":
                        text = text[4:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip().strip("`").strip()
                candidate = _first_json_value(text)
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    return {"shots": parsed}
            except (ValueError, json.JSONDecodeError):
                pass
            if attempt < retries:
                finish_hint = (
                    "上一条 JSON 在输出中途被截断（finish=%s）。" % finish
                    if finish else "上一条 JSON 不完整或无法解析。")
                payload_note = (
                    finish_hint +
                    "请只返回更精简、完整、可解析的 JSON：只包含要求的条目，"
                    "不要解释，不要 markdown，不要重复无关内容。")
                messages = list(messages) + [
                    {"role": "user", "content": payload_note}]
                continue
        raise ExternalLLMError(
            "External LLM did not return usable JSON (finish=%s): %s" % (
                finish, last[:1000]))

    def unload(self, model: str = "") -> None:
        return None
