"""Process lifecycle for ComfyUI (and Ollama when needed).

Only processes started by this application are ever stopped. Attach mode never
touches a server owned by the user.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from comfyui_generator.core.comfy import ComfyClient
from comfyui_generator.core.config import AppConfig, ComfyConfig

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_PROCESS_GROUP = 0x00000200 if os.name == "nt" else 0


class ServiceError(RuntimeError):
    pass


def _pid_on_port(port: int) -> int | None:
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return None
    needle = f":{port}"
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" \
                and parts[1].endswith(needle) and parts[4].isdigit():
            return int(parts[4])
    return None


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True, timeout=15)
    else:  # pragma: no cover
        try:
            os.kill(pid, 15)
        except OSError:
            pass


class ComfyService:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.comfy: ComfyConfig = cfg.comfy
        self._proc: subprocess.Popen | None = None
        self._log_path = cfg.logs_dir / "comfyui.log"
        self._started_at: float | None = None

    # ---------------------------------------------------------------- probing

    @property
    def owned(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def probe(self, timeout: float = 3.0) -> dict[str, Any] | None:
        try:
            client = ComfyClient(self.comfy.base_url, timeout=int(timeout))
            return client.system_stats()
        except Exception:
            return None

    def status(self) -> dict[str, Any]:
        stats = self.probe()
        version = None
        if stats:
            version = ((stats.get("system") or {}).get("comfyui_version"))
        return {
            "running": stats is not None,
            "owned": self.owned,
            "pid": self._proc.pid if self.owned and self._proc else None,
            "version": version,
            "base_url": self.comfy.base_url,
            "log": str(self._log_path),
        }

    # ---------------------------------------------------------------- lifecycle

    def ensure(self) -> str:
        """Return 'attached' or 'started'. May raise ServiceError."""
        if self.probe():
            return "attached"
        mode = (self.comfy.mode or "auto").lower()
        if mode == "attach":
            raise ServiceError(f"ComfyUI is not running at {self.comfy.base_url} (attach mode).")
        if not self.comfy.auto_start:
            raise ServiceError("ComfyUI is not running and auto_start is disabled.")
        return self.start()

    def _build_command(self) -> list[str]:
        c = self.comfy
        paths = c.resolved_paths()
        python = paths["python"]
        main_py = paths["main_py"]
        if not python or not Path(python).is_file():
            raise ServiceError("ComfyUI python not found. Set comfy.python in config.")
        if not main_py or not Path(main_py).is_file():
            raise ServiceError("ComfyUI main.py not found. Set comfy.main_py in config.")
        cmd = [python, main_py]
        if paths["user_dir"]:
            cmd += ["--user-directory", paths["user_dir"]]
        if paths["input_dir"]:
            cmd += ["--input-directory", paths["input_dir"]]
        if paths["output_dir"]:
            cmd += ["--output-directory", paths["output_dir"]]
        if paths["base_dir"]:
            cmd += ["--base-directory", paths["base_dir"]]
        if paths["extra_model_paths"]:
            cmd += ["--extra-model-paths-config", paths["extra_model_paths"]]
        if (c.preview_method or "none").lower() != "none":
            cmd += ["--preview-method", c.preview_method, "--preview-size", str(c.preview_size)]
        cmd += ["--log-stdout", "--listen", c.host, "--port", str(c.port)]
        cmd += list(c.extra_args or [])
        return cmd

    def start(self) -> str:
        if self.probe():
            return "attached"
        cmd = self._build_command()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path, "a", encoding="utf-8", errors="replace")
        log.write("\n\n=== start %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                                  " ".join(shlex.quote(part) for part in cmd)))
        log.flush()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        cwd = self.comfy.base_dir or str(Path(cmd[1]).parent)
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self._proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                      env=env, creationflags=flags)
        self._started_at = time.time()
        self._wait_ready()
        return "started"

    def _wait_ready(self) -> None:
        deadline = time.time() + max(10, self.comfy.startup_timeout)
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise ServiceError("ComfyUI exited during startup.\n" + self.tail_log())
            if self.probe(timeout=2):
                return
            time.sleep(1.0)
        self.stop()
        raise ServiceError("ComfyUI did not become ready in time.\n" + self.tail_log())

    def stop(self, timeout: float = 10.0) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._proc = None
            return
        try:
            proc.terminate()
        except OSError:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                self._proc = None
                return
            time.sleep(0.2)
        _kill_tree(proc.pid)
        self._proc = None

    def restart(self, force_external: bool = False) -> str:
        if self.owned:
            pid = self._proc.pid if self._proc else None
            self.stop()
        else:
            pid = _pid_on_port(self.comfy.port)
            if pid is None:
                return self.start()
            if not force_external:
                raise ServiceError("ComfyUI is running but was not started by this app; "
                                   "restart requires confirmation.")
            _kill_tree(pid)
            deadline = time.time() + 15
            while time.time() < deadline and self.probe(timeout=1):
                time.sleep(0.5)
        return self.start()

    def tail_log(self, lines: int = 40) -> str:
        try:
            data = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(data[-lines:])
        except OSError:
            return ""


class OllamaService:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None

    def probe(self, timeout: float = 3.0) -> bool:
        from comfyui_generator.core.ollama import OllamaClient
        try:
            OllamaClient(self.cfg.ollama.base_url, timeout=timeout).tags()
            return True
        except Exception:
            return False

    def ensure(self) -> str:
        if self.probe():
            return "attached"
        exe = self.cfg.ollama.exe
        if not exe or not Path(exe).is_file():
            raise ServiceError("Ollama is not running and ollama.exe is not configured.")
        if not self.cfg.ollama.auto_start:
            raise ServiceError("Ollama is not running and auto_start is disabled.")
        log_path = self.cfg.logs_dir / "ollama.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "a", encoding="utf-8", errors="replace")
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        self._proc = subprocess.Popen([exe, "serve"], stdout=log, stderr=subprocess.STDOUT,
                                      creationflags=flags)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise ServiceError("Ollama exited during startup.")
            if self.probe(timeout=1):
                return "started"
            time.sleep(1.0)
        raise ServiceError("Ollama did not become ready in time.")
