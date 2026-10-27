"""Read LoRA tags directly from bundled safetensors metadata.

No filtering, no thresholds: every tag found in ``ss_tag_frequency`` (plus
trigger/title fields) is listed so the user can decide what to keep.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any, Iterable

STYLE_HINTS = ("style", "screencap", "artstyle", "art_style", "aesthetic", "hrf", "sysdeep")
TRIGGER_KEYS = (
    "modelspec.trigger_phrase", "modelspec.trigger_words", "ss_trigger_words",
    "trigger_words", "activation text", "ss_activation_text", "trigger",
)


def _clean_tag(tag: str) -> str:
    tag = tag.replace("\ufeff", "").strip().strip(",")
    return re.sub(r"\s+", " ", tag)


def _as_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_as_tags(item))
        return items
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (list, dict)):
            return _as_tags(parsed)
    except Exception:
        pass
    return [part.strip() for part in re.split(r"[,\n;；，]", text) if part.strip()]


def read_safetensors_metadata(path: str | Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            if size <= 0 or size > 64 * 1024 * 1024:
                return {}
            header = json.loads(handle.read(size))
        meta = header.get("__metadata__") or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def _sidecar(path: Path) -> tuple[list[str], str]:
    triggers: list[str] = []
    description = ""
    candidates = [
        path.with_name(path.stem + ".metadata.json"),
        path.with_suffix(".civitai.info"),
        path.with_suffix(".json"),
        path.with_suffix(".txt"),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".txt":
                for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and "http://" not in line and "https://" not in line and len(line) < 200:
                        triggers.extend(_as_tags(line))
                continue
            data = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("trainedWords", "activation text", "activation_text",
                    "trigger_words", "triggers"):
            triggers.extend(_as_tags(data.get(key)))
        civitai = data.get("civitai") or {}
        if isinstance(civitai, dict):
            triggers.extend(_as_tags(civitai.get("trainedWords")))
            for key in ("description", "notes"):
                if civitai.get(key):
                    description += "\n" + str(civitai[key])
            model = civitai.get("model") or {}
            if isinstance(model, dict) and model.get("description"):
                description += "\n" + str(model["description"])
        for key in ("description", "modelDescription", "notes"):
            if data.get(key):
                description += "\n" + str(data[key])
        tags = data.get("tags")
        if isinstance(tags, list):
            triggers.extend(_as_tags(tags))
    return triggers, description


def _tag_counts(meta: dict[str, Any]) -> dict[str, int]:
    raw = meta.get("ss_tag_frequency")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    counts: dict[str, int] = {}
    if not isinstance(data, dict):
        return counts
    for value in data.values():
        if not isinstance(value, dict):
            continue
        for tag, count in value.items():
            cleaned = _clean_tag(str(tag))
            if not cleaned:
                continue
            try:
                counts[cleaned] = counts.get(cleaned, 0) + int(count)
            except (TypeError, ValueError):
                continue
    return counts


def _description_triggers(description: str) -> list[str]:
    triggers: list[str] = []
    for line in description.splitlines():
        low = line.lower()
        if "trigger" in low or "激活" in line or "触发" in line:
            part = re.split(r"[:：]", line, maxsplit=1)
            if len(part) == 2:
                triggers.extend(_as_tags(part[1]))
    return triggers


def is_style_lora(path: str | Path) -> bool:
    """Classify a LoRA by filename hints (style / screencap / hrf ...)."""
    blob = Path(str(path)).name.lower()
    return any(hint in blob for hint in STYLE_HINTS)


def extract_tags(meta: dict[str, Any], filename: str = "") -> list[str]:
    """Return every tag from metadata, ordered by frequency. No filtering."""
    triggers: list[str] = []
    for key in TRIGGER_KEYS:
        triggers.extend(_as_tags(meta.get(key)))
    triggers.extend(_description_triggers(str(meta.get("modelspec.description") or "")))
    title = _clean_tag(str(meta.get("modelspec.title") or ""))

    counts = _tag_counts(meta)
    ordered: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        tag = _clean_tag(tag)
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            ordered.append(tag)

    for tag in triggers:
        add(tag)
    if title and (title.lower() in {tag.lower() for tag in counts} or
                  any(title.lower() == tag.lower() for tag in triggers)):
        add(title)
    for tag, _count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        add(tag)
    return ordered


def _dedupe(words: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for word in words:
        word = _clean_tag(word)
        if word and word.lower() not in seen:
            seen.add(word.lower())
            result.append(word)
    return result


def _explicit_triggers(meta: dict[str, Any]) -> list[str]:
    triggers: list[str] = []
    for key in TRIGGER_KEYS:
        triggers.extend(_as_tags(meta.get(key)))
    triggers.extend(_description_triggers(str(meta.get("modelspec.description") or "")))
    return _dedupe(triggers)


def identity_tags(meta: dict[str, Any], filename: str,
                  reference: list[str]) -> list[str]:
    lower_ref = {tag.lower(): tag for tag in reference}
    triggers = [tag for tag in _explicit_triggers(meta) if tag.lower() in lower_ref]
    title = _clean_tag(str(meta.get("modelspec.title") or ""))
    if title and title.lower() in lower_ref:
        triggers.append(lower_ref[title.lower()])
    stem = Path(filename).stem.lower()
    for candidate in (stem, stem.replace("-", "_"), stem.replace("_", "-")):
        if candidate in lower_ref:
            triggers.append(lower_ref[candidate])
            break
    if not triggers:
        parens = [tag for tag in reference if "(" in tag or ")" in tag]
        if parens:
            counts = _tag_counts(meta)
            parens.sort(key=lambda tag: counts.get(tag, 0), reverse=True)
            triggers.append(parens[0])
    return _dedupe(triggers)[:5]


def default_activation(meta: dict[str, Any], filename: str,
                       reference: list[str]) -> list[str]:
    """Small default prompt subset; the full list stays available as reference.

    No content filtering: trigger fields first, then title/stem if they are
    actual tags, otherwise the first 12 reference tags.
    """
    lower_ref = {tag.lower(): tag for tag in reference}
    triggers = _explicit_triggers(meta)
    if triggers:
        return triggers[:12]

    title = _clean_tag(str(meta.get("modelspec.title") or ""))
    if title and title.lower() in lower_ref:
        return [lower_ref[title.lower()]]

    stem = Path(filename).stem.lower()
    for candidate in (stem, stem.replace("-", "_"), stem.replace("_", "-")):
        if candidate in lower_ref:
            return [lower_ref[candidate]]

    counts = _tag_counts(meta)
    ordered = sorted(reference, key=lambda tag: counts.get(tag, 0), reverse=True)
    return ordered[:12]


def lora_tag_info(path: str | Path, online: bool = False, civitai_base: str = "",
                  fetcher=None) -> dict[str, Any]:
    path = Path(path)
    meta = read_safetensors_metadata(path)
    reference = extract_tags(meta, path.name)
    if reference:
        return {
            "reference": reference,
            "triggers": default_activation(meta, path.name, reference),
            "identity": identity_tags(meta, path.name, reference),
            "source": "safetensors 内置元数据",
        }

    if online:
        try:
            if fetcher is None:
                from comfyui_generator.core.civitai import fetch_words_for_path
                fetcher = fetch_words_for_path
            words, source = fetcher(str(path), civitai_base or "https://civitai.red")
            if words:
                reference = _dedupe(words)
                return {
                    "reference": reference,
                    "triggers": default_activation(meta, path.name, reference),
                    "identity": identity_tags(meta, path.name, reference),
                    "source": "Civitai：%s" % source,
                }
        except Exception:
            pass

    sidecar_triggers, _description = _sidecar(path)
    reference = _dedupe(sidecar_triggers)
    if reference:
        return {
            "reference": reference,
            "triggers": default_activation(meta, path.name, reference),
            "identity": identity_tags(meta, path.name, reference),
            "source": "LoRA 伴随文件",
        }
    return {"reference": [], "triggers": [], "identity": [], "source": "未找到标签"}


def tags_for_lora(path: str | Path, online: bool = False, civitai_base: str = "",
                  fetcher=None) -> tuple[str, str]:
    info = lora_tag_info(path, online=online, civitai_base=civitai_base, fetcher=fetcher)
    return ", ".join(info["reference"]), info["source"]


def preset_tags(lora_name: str, extra_dirs: Iterable[str | Path] = ()) -> str:
    """Kept for template/preset inspection; tag sync no longer uses it."""
    from comfyui_generator.core.config import PRESET_DIR

    if not lora_name:
        return ""
    target = Path(str(lora_name).replace("\\", "/")).name
    seen: set[Path] = set()
    for directory in [PRESET_DIR, *extra_dirs]:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            if path in seen:
                continue
            seen.add(path)
            try:
                config = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            loras = config.get("loras")
            names = []
            if isinstance(loras, list):
                names = [item.get("name") for item in loras if isinstance(item, dict)]
            elif config.get("lora"):
                names = [config["lora"].get("name")]
            matched = lora_name in names or any(
                Path(str(name).replace("\\", "/")).name == target for name in names if name)
            if matched:
                tags = (config.get("character") or {}).get("tags") or ""
                if tags.strip():
                    return tags
    return ""
