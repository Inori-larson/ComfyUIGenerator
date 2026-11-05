from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (set, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)


class TraceSession:
    def __init__(self, log_dir: Path, kind: str,
                 meta: dict[str, Any] | None = None):
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.stem = "%s_%s" % (stamp, kind or "run")
        self.jsonl_path = log_dir / (self.stem + ".jsonl")
        self.text_path = log_dir / (self.stem + ".log")
        self._jsonl = self.jsonl_path.open("w", encoding="utf-8")
        self._text = self.text_path.open("w", encoding="utf-8")
        self._lock = threading.Lock()
        self.write("session.start", meta or {})

    def write(self, event: str, data: Any = None) -> None:
        payload = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "event": event,
            "data": _jsonable(data),
        }
        with self._lock:
            self._jsonl.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._jsonl.flush()
            self._text.write("[%s] %s %s\n" % (
                payload["time"], event,
                json.dumps(payload["data"], ensure_ascii=False)))
            self._text.flush()

    def close(self) -> None:
        self.write("session.end", {})
        with self._lock:
            self._jsonl.close()
            self._text.close()


_CURRENT: ContextVar[TraceSession | None] = ContextVar(
    "comfyui_generator_trace", default=None)


def trace_event(event: str, data: Any = None) -> None:
    session = _CURRENT.get()
    if session is not None:
        session.write(event, data)


def current_trace() -> TraceSession | None:
    return _CURRENT.get()


def start_trace(log_dir: Path, kind: str,
                meta: dict[str, Any] | None = None) -> tuple[TraceSession, Any]:
    session = TraceSession(log_dir, kind, meta)
    return session, _CURRENT.set(session)


def stop_trace(session: TraceSession, token: Any) -> None:
    _CURRENT.reset(token)
    session.close()


@contextmanager
def trace_session(log_dir: Path, kind: str,
                  meta: dict[str, Any] | None = None) -> Iterator[TraceSession]:
    session = TraceSession(log_dir, kind, meta)
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        _CURRENT.reset(token)
        session.close()


class TracedClient:
    def __init__(self, client: Any, label: str = ""):
        self._client = client
        self._label = label

    def chat_json(self, model: str, messages: list[dict[str, str]],
                  **kwargs: Any) -> Any:
        started = time.time()
        trace_event("ai.request", {
            "label": self._label,
            "model": model,
            "messages": messages,
            "options": kwargs,
        })
        try:
            result = self._client.chat_json(model, messages, **kwargs)
        except Exception as exc:
            trace_event("ai.error", {
                "label": self._label,
                "model": model,
                "duration": round(time.time() - started, 3),
                "error": repr(exc),
            })
            raise
        trace_event("ai.response", {
            "label": self._label,
            "model": model,
            "duration": round(time.time() - started, 3),
            "response": result,
        })
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
