"""HTTP + WebSocket client for the ComfyUI API."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from comfyui_generator.core.preview import PreviewFrame, parse_binary_frame, parse_text_frame

try:  # pragma: no cover - optional at import time for headless tests
    import websocket
    from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException
except Exception:  # pragma: no cover
    websocket = None
    WebSocketConnectionClosedException = Exception
    WebSocketTimeoutException = Exception


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, client_id: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or uuid.uuid4().hex
        self.timeout = timeout

    # ---------------------------------------------------------------- low level

    def _request(self, path: str, payload: dict[str, Any] | None = None,
                 timeout: int | None = None, raw: bool = False) -> Any:
        url = self.base_url + path
        data = None
        headers = {}
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise ComfyError(f"ComfyUI HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ComfyError(f"Cannot reach ComfyUI at {self.base_url}: {exc.reason}") from exc
        if raw:
            return body
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ComfyError(f"Invalid JSON from ComfyUI {path}: {exc}") from exc

    def post_bytes(self, path: str, body: bytes, content_type: str, timeout: int | None = None) -> Any:
        req = urllib.request.Request(self.base_url + path, data=body, method="POST",
                                     headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise ComfyError(f"ComfyUI HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ComfyError(f"Cannot reach ComfyUI at {self.base_url}: {exc.reason}") from exc

    # ---------------------------------------------------------------- API

    def system_stats(self) -> dict[str, Any]:
        return self._request("/system_stats", timeout=10)

    def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        path = "/object_info" if node_class is None else f"/object_info/{node_class}"
        return self._request(path, timeout=60)

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        out = self._request("/prompt", {"prompt": workflow, "client_id": self.client_id}, timeout=30)
        if out.get("node_errors"):
            raise ComfyError("ComfyUI rejected the workflow:\n" +
                             json.dumps(out["node_errors"], ensure_ascii=False, indent=2))
        prompt_id = out.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI did not return a prompt_id: {out}")
        return prompt_id

    def history(self, prompt_id: str) -> dict[str, Any]:
        return self._request(f"/history/{prompt_id}", timeout=15)

    def wait_for(self, prompt_id: str, timeout: float = 1800.0, poll: float = 0.5) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                hist = self.history(prompt_id)
            except ComfyError:
                time.sleep(poll)
                continue
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                state = status.get("status_str")
                if state == "success":
                    return entry
                if state == "error":
                    raise ComfyError("Generation failed:\n" +
                                     json.dumps(status, ensure_ascii=False, indent=2)[:4000])
            time.sleep(poll)
        raise ComfyError(f"Timed out waiting for prompt {prompt_id}")

    def interrupt(self) -> None:
        try:
            self._request("/interrupt", {}, timeout=10)
        except ComfyError:
            pass

    def queue_state(self) -> dict[str, Any]:
        return self._request("/queue", timeout=10)

    def upload_image(self, path: str | Path, subfolder: str = "anime_story",
                     overwrite: bool = True, folder_type: str = "input") -> str:
        path = Path(path)
        if not path.is_file():
            raise ComfyError(f"Image not found: {path}")
        boundary = "----ComfyUIGenerator" + uuid.uuid4().hex
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
            )

        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        )
        parts.append(path.read_bytes())
        parts.append(b"\r\n")
        if subfolder:
            field("subfolder", subfolder)
        field("type", folder_type)
        field("overwrite", "true" if overwrite else "false")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        out = self.post_bytes("/upload/image", body, f"multipart/form-data; boundary={boundary}", timeout=120)
        name = out.get("name") or path.name
        sub = out.get("subfolder") or subfolder
        return f"{sub}/{name}".replace("\\", "/") if sub else name

    def view(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
        return self._request(f"/view?{query}", timeout=60, raw=True)


class ComfyEventStream(threading.Thread):
    """Background WebSocket listener that emits text events and preview frames."""

    def __init__(self, ws_url: str, client_id: str,
                 on_event: Callable[[dict[str, Any]], None] | None = None,
                 on_preview: Callable[[PreviewFrame], None] | None = None,
                 reconnect_delay: float = 1.0):
        super().__init__(daemon=True, name="ComfyEventStream")
        self.ws_url = f"{ws_url.rstrip('/')}?clientId={client_id}"
        self.on_event = on_event
        self.on_preview = on_preview
        self.reconnect_delay = reconnect_delay
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._conn = None

    def stop(self) -> None:
        self._stop.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def run(self) -> None:  # pragma: no cover - requires live server
        if websocket is None:
            self.last_error = "websocket-client is not installed"
            return
        while not self._stop.is_set():
            try:
                conn = websocket.create_connection(self.ws_url, timeout=5)
                self._conn = conn
                conn.settimeout(2.0)
                self.last_error = None
                while not self._stop.is_set():
                    try:
                        message = conn.recv()
                    except WebSocketTimeoutException:
                        continue
                    except WebSocketConnectionClosedException as exc:
                        self.last_error = str(exc)
                        break
                    if isinstance(message, bytes):
                        parsed = parse_binary_frame(message)
                        if isinstance(parsed, PreviewFrame):
                            if self.on_preview:
                                self.on_preview(parsed)
                        elif isinstance(parsed, dict) and self.on_event:
                            self.on_event(parsed)
                    elif self.on_event:
                        data = parse_text_frame(message)
                        if data:
                            self.on_event(data)
            except Exception as exc:  # connection refused, DNS, etc.
                self.last_error = str(exc)
            finally:
                conn = self._conn
                self._conn = None
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            if not self._stop.is_set():
                time.sleep(self.reconnect_delay)
