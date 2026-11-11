"""Read model catalog from the user's opencode configuration.

Only parses the config; it never writes it and never performs network access.
Both ``opencode.json`` and ``opencode.jsonc`` (comments, trailing commas) are
supported.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("OPENCODE_CONFIG", "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        paths.append(Path(xdg) / "opencode")
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    paths.append(home / ".config" / "opencode")
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        paths.append(Path(appdata) / "opencode")
    results: list[Path] = []
    for folder in paths:
        for name in ("opencode.json", "opencode.jsonc"):
            candidate = folder / name
            if candidate.is_file():
                results.append(candidate)
    return results


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    escaped = False
    while i < length:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < length and text[i + 1] == "*":
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def load_opencode_config(path: Path | None = None) -> dict[str, Any]:
    candidates = [path] if path else _candidate_paths()
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            raw = candidate.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for loader in (json.loads, lambda text: json.loads(_strip_json_comments(text))):
            try:
                data = loader(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return {}


def provider_catalog(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return [{provider, name, base_url, api_key, models:[{id, name}]}]."""
    data = cfg if cfg is not None else load_opencode_config()
    providers = data.get("provider") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return []
    catalog: list[dict[str, Any]] = []
    for provider_id, spec in providers.items():
        if not isinstance(spec, dict):
            continue
        options = spec.get("options") if isinstance(spec.get("options"), dict) else {}
        models_spec = spec.get("models") if isinstance(spec.get("models"), dict) else {}
        models: list[dict[str, str]] = []
        for model_id, model_spec in models_spec.items():
            name = model_id
            if isinstance(model_spec, dict):
                name = str(model_spec.get("name") or model_id)
            models.append({"id": str(model_id), "name": name})
        catalog.append({
            "provider": str(provider_id),
            "name": str(spec.get("name") or provider_id),
            "base_url": str(options.get("baseURL") or options.get("base_url") or "").strip(),
            "api_key": str(options.get("apiKey") or options.get("api_key") or "").strip(),
            "models": models,
        })
    return catalog


def iter_models(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Flat list of {provider, provider_name, id, name, base_url, api_key}."""
    rows: list[dict[str, Any]] = []
    for provider in provider_catalog(cfg):
        for model in provider["models"]:
            rows.append({
                "provider": provider["provider"],
                "provider_name": provider["name"],
                "id": model["id"],
                "name": model["name"],
                "base_url": provider["base_url"],
                "api_key": provider["api_key"],
            })
    return rows


def model_choices(cfg: dict[str, Any] | None = None,
                  include_local: bool = False) -> list[tuple[str, str]]:
    """[(label, model_id)] for the external model dropdown."""
    choices: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in iter_models(cfg):
        base = row["base_url"].lower()
        if not include_local and ("127.0.0.1" in base or "localhost" in base):
            continue
        if not row["base_url"]:
            continue
        model_id = row["id"]
        if model_id in seen:
            continue
        seen.add(model_id)
        label = "%s（%s）" % (row["name"], row["provider_name"])
        choices.append((label, model_id))
    return choices


def endpoint_for_model(model_id: str,
                       cfg: dict[str, Any] | None = None) -> dict[str, str]:
    for row in iter_models(cfg):
        if row["id"] == model_id:
            return {"base_url": row["base_url"], "api_key": row["api_key"]}
    return {}
