"""Application configuration and local data directories.

All persisted state lives under %APPDATA%\\ComfyUIGenerator by default.
Set COMFYUI_GENERATOR_HOME to override (portable mode).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from comfyui_generator import APP_ID

PACKAGE_DIR = Path(__file__).resolve().parent.parent
PRESET_DIR = PACKAGE_DIR / "presets"
DEFAULT_PRESET = PRESET_DIR / "illustrious_yixuan_v2.json"


def app_data_dir() -> Path:
    override = os.environ.get("COMFYUI_GENERATOR_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_ID


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _drive_roots() -> list[Path]:
    roots: list[Path] = []
    for letter in "CDEFGHIJ":
        root = Path(f"{letter}:/")
        if root.is_dir():
            roots.append(root)
    return roots


def detect_comfy_main() -> Path | None:
    env = os.environ.get("COMFYUI_MAIN")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/ComfyUI/resources/ComfyUI/main.py",
        Path.home() / "ComfyUI/main.py",
    ]
    for drive in _drive_roots():
        candidates += [
            drive / "Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/main.py",
            drive / "ComfyUI/resources/ComfyUI/main.py",
            drive / "ComfyUI/main.py",
            drive / "ComfyUI_windows_portable/ComfyUI/main.py",
        ]
    return _first_existing(candidates)


def detect_comfy_python(main_py: Path | None) -> Path | None:
    env = os.environ.get("COMFYUI_PYTHON")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    for drive in _drive_roots():
        candidates += [
            drive / "ComfyUIData/.venv/Scripts/python.exe",
            drive / "ComfyUI_windows_portable/python_embeded/python.exe",
        ]
    if main_py:
        root = main_py.parent
        for up in (root, root.parent, root.parent.parent):
            candidates.append(up / ".venv" / "Scripts" / "python.exe")
    return _first_existing(candidates)


def detect_comfy_base(main_py: Path | None) -> Path | None:
    env = os.environ.get("COMFYUI_BASE")
    if env:
        return Path(env)
    for drive in _drive_roots():
        candidate = drive / "ComfyUIData"
        if candidate.is_dir():
            return candidate
    return None


def detect_ollama_exe() -> Path | None:
    env = os.environ.get("OLLAMA_EXE")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    return _first_existing(candidates)


@dataclass
class ComfyConfig:
    mode: str = "auto"  # auto | attach | managed
    host: str = "127.0.0.1"
    port: int = 8000
    python: str = ""
    main_py: str = ""
    base_dir: str = ""
    input_dir: str = ""
    output_dir: str = ""
    user_dir: str = ""
    extra_model_paths: str = ""
    extra_args: list[str] = field(default_factory=list)
    preview_method: str = "latent2rgb"  # none | latent2rgb | taesd | auto
    preview_size: int = 512
    auto_start: bool = True
    restart_on_crash: bool = True
    keep_running_on_exit: bool = False
    startup_timeout: int = 90

    @property
    def base_url(self) -> str:
        host = self.host.strip().rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            return f"{host}:{self.port}" if ":" not in host.split("//", 1)[1] else host
        return f"http://{host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws"

    def resolved_paths(self) -> dict[str, str]:
        base = Path(self.base_dir) if self.base_dir else None
        out = {
            "python": self.python,
            "main_py": self.main_py,
            "base_dir": self.base_dir,
            "input_dir": self.input_dir or (str(base / "input") if base else ""),
            "output_dir": self.output_dir or (str(base / "output") if base else ""),
            "user_dir": self.user_dir or (str(base / "user") if base else ""),
            "extra_model_paths": self.extra_model_paths,
        }
        return out


@dataclass
class OllamaConfig:
    host: str = "127.0.0.1"
    port: int = 11434
    exe: str = ""
    auto_start: bool = True
    default_model: str = ""
    keep_alive: str = "5m"

    @property
    def base_url(self) -> str:
        host = self.host.strip().rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return f"http://{host}:{self.port}"


@dataclass
class GenerationDefaults:
    template: str = ""
    shots: int = 6
    variants: int = 1
    width: int = 1024
    height: int = 1344
    steps: int = 30
    cfg: float = 5.0
    sampler: str = "euler_ancestral"
    scheduler: str = "normal"
    seed_mode: str = "increment"  # increment | fixed | random
    hires_enabled: bool = True
    hires_scale: float = 1.5
    hires_denoise: float = 0.4
    hires_steps: int = 20
    upscaler: str = ""
    mood: str = "bright"
    detailers: list[dict[str, Any]] = field(default_factory=list)
    wildcards: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "dir": ""})


@dataclass
class UIConfig:
    language: str = "zh-CN"  # zh-CN | en-US
    theme: str = "light"


@dataclass
class AppConfig:
    comfy: ComfyConfig = field(default_factory=ComfyConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    generation: GenerationDefaults = field(default_factory=GenerationDefaults)
    ui: UIConfig = field(default_factory=UIConfig)
    storage_root: str = ""

    @property
    def root(self) -> Path:
        return Path(self.storage_root) if self.storage_root else app_data_dir()

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def ensure_dirs(self) -> None:
        for path in (self.root, self.projects_dir, self.profiles_dir, self.logs_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_dataclass(obj: Any, data: dict[str, Any]) -> Any:
    for f in fields(obj):
        if f.name not in data:
            continue
        value = data[f.name]
        current = getattr(obj, f.name)
        if is_dataclass(current) and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(obj, f.name, value)
    return obj


def default_config_path() -> Path:
    return app_data_dir() / "config.json"


def default_config() -> AppConfig:
    main_py = detect_comfy_main()
    python = detect_comfy_python(main_py)
    base = detect_comfy_base(main_py)
    ollama_exe = detect_ollama_exe()

    cfg = AppConfig()
    cfg.comfy.main_py = str(main_py) if main_py else ""
    cfg.comfy.python = str(python) if python else ""
    cfg.comfy.base_dir = str(base) if base else ""
    if base:
        cfg.comfy.input_dir = str(base / "input")
        cfg.comfy.output_dir = str(base / "output")
        cfg.comfy.user_dir = str(base / "user")
    cfg.ollama.exe = str(ollama_exe) if ollama_exe else ""
    cfg.generation.template = str(DEFAULT_PRESET)
    cfg.generation.wildcards = {"enabled": False,
                                "dir": str(Path.cwd() / "wildcards")}
    return cfg


def load_config(path: Path | None = None) -> AppConfig:
    cfg = default_config()
    path = path or default_config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _merge_dataclass(cfg, data)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] failed to load {path}: {exc}", file=sys.stderr)
    return cfg


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def resolve_template(cfg: AppConfig) -> Path:
    candidate = Path(cfg.generation.template) if cfg.generation.template else DEFAULT_PRESET
    if candidate.is_file():
        return candidate
    if DEFAULT_PRESET.is_file():
        return DEFAULT_PRESET
    raise FileNotFoundError("No storyboard template found. Set generation.template in config.")


def load_template(cfg: AppConfig) -> dict[str, Any]:
    path = resolve_template(cfg)
    return json.loads(path.read_text(encoding="utf-8-sig"))
