"""Local LLM backend backed by llama.cpp's llama-server.

Exposes an OllamaClient-shaped interface so the rest of the app keeps working,
but talks to llama-server's OpenAI-compatible API. llama-server can be started
and stopped here; reasoning runs on the server side (--reasoning on).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comfyui_generator.core.mechanical import split_tags
from comfyui_generator.core.subprocess_util import run_hidden

LLAMA_SERVER_DEFAULT = (
    r"C:\Users\gg935\AppData\Local\LocModel\engines\b12707-cuda-13.5\llama-server.exe"
)


class LlamaServerError(RuntimeError):
    pass


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise LlamaServerError("llama-server HTTP %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise LlamaServerError("Cannot reach llama-server at %s: %s" % (
            url, exc.reason)) from exc


def _get(url: str, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LlamaServerError("Cannot reach llama-server at %s: %s" % (
            url, exc.reason)) from exc


@dataclass
class LlamaServerConfig:
    exe: str = LLAMA_SERVER_DEFAULT
    model: str = (
        r"G:\AI-Models\huihui-ai__Huihui-Qwen3.8-27B-abliterated-GGUF"
        r"\Huihui-Qwen3.8-27B-abliterated-UD-Q2_K_XL.gguf"
    )
    mmproj: str = (
        r"G:\AI-Models\huihui-ai__Huihui-Qwen3.8-27B-abliterated-GGUF"
        r"\mmproj-model-bf16.gguf"
    )
    host: str = "127.0.0.1"
    port: int = 8080
    context: int = 16384
    gpu_layers: int = 32
    parallel: int = 1
    reasoning_effort: str = "low"
    reasoning_budget: int = 1024
    reasoning_preserve: bool = False
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 64
    auto_start: bool = False
    timeout: float = 900.0
    default_model: str = "local-model"
    keep_alive: str = "5m"
    profile: str = "muse"
    profiles: list[dict[str, Any]] = field(default_factory=list)

    _PROFILE_FIELDS = (
        "model", "mmproj", "context", "gpu_layers", "parallel",
        "reasoning_effort", "reasoning_budget", "reasoning_preserve",
        "temperature", "top_p", "top_k",
    )

    def active_profile(self) -> dict[str, Any]:
        for item in self.profiles:
            if isinstance(item, dict) and item.get("name") == self.profile:
                return item
        return {}

    def resolved(self) -> dict[str, Any]:
        values = {key: getattr(self, key) for key in self._PROFILE_FIELDS}
        values.update({
            key: value for key, value in self.active_profile().items()
            if key in self._PROFILE_FIELDS and value is not None
        })
        return values

    @property
    def base_url(self) -> str:
        host = self.host.strip().rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return "http://%s:%d" % (host, self.port)

    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/v1/chat/completions"

    def models_url(self) -> str:
        return self.base_url.rstrip("/") + "/v1/models"

    def health_url(self) -> str:
        return self.base_url.rstrip("/") + "/health"


def llama_server_command(cfg: LlamaServerConfig) -> list[str]:
    r = cfg.resolved()
    cmd = [
        cfg.exe, "-m", r["model"],
        "-ngl", str(r["gpu_layers"]), "-fa", "on", "--jinja",
        "--reasoning", "on", "--reasoning-format", "deepseek",
        "--reasoning-effort", r["reasoning_effort"],
        "--reasoning-budget", str(r["reasoning_budget"]),
    ]
    if not r["reasoning_preserve"]:
        cmd.append("--no-reasoning-preserve")
    cmd += [
        "--parallel", str(max(1, int(r["parallel"]))),
        "--host", cfg.host, "--port", str(cfg.port),
        "-c", str(r["context"]),
        "--temp", str(r["temperature"]),
        "--top-p", str(r["top_p"]),
        "--top-k", str(r["top_k"]),
    ]
    if r["mmproj"]:
        cmd += ["--mmproj", r["mmproj"]]
    return cmd


class LlamaServerService:
    def __init__(self, cfg: Any, log_path: Path | None = None):
        self.cfg = cfg if isinstance(cfg, LlamaServerConfig) else cfg.ollama
        self._app_cfg = cfg if not isinstance(cfg, LlamaServerConfig) else None
        self._proc: subprocess.Popen | None = None
        self._log_path = log_path

        if self._app_cfg is not None:
            logs_dir = getattr(self._app_cfg, "logs_dir", None)
            if logs_dir and self._log_path is None:
                self._log_path = Path(logs_dir) / "llama-server.log"

    def probe(self, timeout: float = 3.0) -> bool:
        try:
            _get(self.cfg.health_url(), timeout)
            return True
        except Exception:
            return False

    def loaded_model(self, timeout: float = 3.0) -> str:
        try:
            data = _get(self.cfg.models_url(), timeout)
        except Exception:
            return ""
        for item in (data.get("data") or []):
            if isinstance(item, dict) and item.get("id"):
                return str(item["id"])
        return ""

    def ensure(self) -> str:
        expected = self.cfg.resolved()["model"]
        if self.probe():
            loaded = self.loaded_model()
            if loaded and Path(loaded).name != Path(expected).name:
                self.stop()
                self._wait_stopped(loaded)
            else:
                return "attached"
        exe = self.cfg.exe
        if not exe or not Path(exe).is_file():
            raise LlamaServerError("llama-server.exe 不存在，请在设置里配置。")
        model = expected
        if not model or not Path(model).is_file():
            raise LlamaServerError("本地 GGUF 模型不存在，请在设置里配置。")
        if not self.cfg.auto_start:
            raise LlamaServerError("llama-server 未运行且 auto_start 已关闭。")
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            log = self._log_path.open("a", encoding="utf-8", errors="replace")
        else:
            log = subprocess.DEVNULL
        cmd = llama_server_command(self.cfg)
        self._proc = run_hidden(
            cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(Path.home()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.time() + 600
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise LlamaServerError("llama-server 启动后退出。")
            if self.probe(timeout=2):
                return "started"
            time.sleep(1.0)
        raise LlamaServerError("llama-server 启动超时。")

    def _wait_stopped(self, model_path: str, timeout: float = 30.0) -> None:
        name = Path(model_path).name
        deadline = time.time() + timeout
        while time.time() < deadline:
            loaded = self.loaded_model(timeout=2)
            if not loaded or Path(loaded).name != name:
                return
            time.sleep(1.0)

    def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            self._proc = None
        else:
            from comfyui_generator.core.subprocess_util import run_hidden
            run_hidden(
                ["taskkill", "/IM", "llama-server.exe", "/F"],
                capture_output=True, text=True, timeout=15)


class LlamaServerClient:
    def __init__(self, base_url: str, timeout: int = 900):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _chat_url(self) -> str:
        return self.base_url if self.base_url.endswith("/chat/completions") \
            else self.base_url + "/v1/chat/completions"

    def tags(self) -> list[dict[str, Any]]:
        try:
            data = _get(self.base_url.rstrip("/") + "/v1/models", self.timeout)
        except Exception:
            return []
        return [{"name": str(item.get("id") or "")}
                for item in (data.get("data") or []) if isinstance(item, dict)]

    def model_names(self) -> list[str]:
        return [tag["name"] for tag in self.tags() if tag.get("name")]

    def ps(self) -> list[dict[str, Any]]:
        return []

    def chat(self, model: str, messages: list[dict[str, str]], *,
             schema: dict[str, Any] | None = None,
             temperature: float = 0.8, top_p: float = 0.9,
             num_predict: int = 2048, num_ctx: int = 32768,
             keep_alive: str = "", timeout: float = 900.0,
             reasoning_effort: str = "") -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max(4096, int(num_predict)),
            "temperature": float(temperature),
            "top_p": float(top_p),
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        out = _post(self._chat_url(), payload, timeout)
        choices = out.get("choices") or []
        if not choices:
            raise LlamaServerError("llama-server returned no choices: %s" % str(out)[:300])
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content:
            raise LlamaServerError(
                "llama-server 返回空内容（reasoning 耗尽 max_tokens），请增大 num_predict。")
        return str(content)

    def chat_json(self, model: str, messages: list[dict[str, str]], *,
                  schema: dict[str, Any] | None = None,
                  retries: int = 1, **kwargs: Any) -> dict[str, Any]:
        from comfyui_generator.core.ollama import extract_json
        base_convo = list(messages)
        last = ""
        for attempt in range(retries + 1):
            convo = list(base_convo)
            call_kwargs = dict(kwargs)
            if attempt > 0:
                convo[-1] = dict(convo[-1])
                convo[-1]["content"] += (
                    "\n上一条输出无法解析，可能重复或未写完。"
                    "请只返回一个简短、结构完整、可被 json.loads 解析的 JSON 对象。")
                try:
                    call_kwargs["temperature"] = min(
                        float(call_kwargs.get("temperature", 0.6)), 0.3)
                except (TypeError, ValueError):
                    call_kwargs["temperature"] = 0.3
            last = self.chat(model, convo, schema=schema, **call_kwargs)
            try:
                data = json.loads(extract_json(last))
                if isinstance(data, dict):
                    required = (schema or {}).get("required") or []
                    missing = [key for key in required if key not in data]
                    if missing and attempt < retries:
                        convo[-1] = dict(base_convo[-1])
                        convo[-1]["content"] += (
                            "\n上一条 JSON 缺少必需字段：%s。"
                            "请重新输出包含该字段的完整 JSON，不要省略任何字段。"
                            % ", ".join(missing))
                        continue
                    return data
                raise ValueError("JSON root is not an object")
            except (ValueError, json.JSONDecodeError):
                if attempt >= retries:
                    break
        raise LlamaServerError("llama-server did not return usable JSON:\n" + last[:2000])

    def unload(self, model: str = "") -> None:
        return None
