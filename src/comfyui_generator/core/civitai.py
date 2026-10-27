"""Fallback lookup of author trigger words on Civitai (civitai.red).

Only used when a LoRA has no safetensors ``__metadata__`` tags. Finds the
model id from bundled metadata / link files, then tries the Civitai API and
finally the model page (``__NEXT_DATA__`` / "trigger words" sections).
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComfyUIGenerator/0.1"
DEFAULT_BASE = "https://civitai.red"
FALLBACK_BASE = "https://civitai.com"


def _sidecar_jsons(path: Path) -> list[dict[str, Any]]:
    candidates = [
        path.with_name(path.stem + ".metadata.json"),
        path.with_suffix(".civitai.info"),
        path.with_suffix(".json"),
    ]
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            result.append(data)
    return result


def find_model_ids(path: str | Path) -> tuple[int | None, int | None]:
    """Return (model_id, version_id) from metadata or link files."""
    path = Path(path)
    model_id: int | None = None
    version_id: int | None = None

    def pick(value: Any) -> int | None:
        try:
            number = int(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    for data in _sidecar_jsons(path):
        civitai = data.get("civitai") if isinstance(data.get("civitai"), dict) else {}
        version_id = version_id or pick(civitai.get("modelVersionId")) or pick(data.get("modelVersionId"))
        model_id = model_id or pick(civitai.get("modelId")) or pick(data.get("modelId"))
        if not model_id and isinstance(data.get("model"), dict):
            model_id = pick(data["model"].get("id"))
        if not version_id:
            version_id = pick(data.get("versionId"))
        if not version_id and "id" in data and "sha256" in data:
            version_id = pick(data.get("id"))

    if not model_id or not version_id:
        for candidate in (path.with_suffix(".txt"), path.with_name(path.stem + ".txt"),
                          path.with_name("链接.txt")):
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            match = re.search(r"/models/(\d+)", text)
            if match and not model_id:
                model_id = int(match.group(1))
            match = re.search(r"/model-versions/(\d+)", text)
            if match and not version_id:
                version_id = int(match.group(1))
    return model_id, version_id


def _request(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _dedupe(words: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for word in words:
        word = html.unescape(str(word)).strip().strip(",")
        word = re.sub(r"\s+", " ", word)
        if word and word.lower() not in seen:
            seen.add(word.lower())
            result.append(word)
    return result


def _split_words(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_split_words(item))
        return result
    text = str(value)
    return [part.strip() for part in re.split(r"[,\n;；，]", text) if part.strip()]


def words_from_payload(payload: Any, version_id: int | None = None) -> list[str]:
    words: list[str] = []
    if not isinstance(payload, dict):
        return words
    if payload.get("trainedWords"):
        words.extend(_split_words(payload["trainedWords"]))
    versions = payload.get("modelVersions")
    if isinstance(versions, list):
        for version in versions:
            if not isinstance(version, dict):
                continue
            if version_id and version.get("id") not in (None, version_id):
                continue
            words.extend(_split_words(version.get("trainedWords")))
            if not words and version.get("description"):
                words.extend(_trigger_section(str(version["description"])))
    if not words and payload.get("description"):
        words.extend(_trigger_section(str(payload["description"])))
    return _dedupe(words)


def _trigger_section(text: str) -> list[str]:
    words: list[str] = []
    pattern = re.compile(r"(?is)(?:trigger\s*words?|activation\s*words?|激活词|触发词)\s*[:：]?\s*(.{0,600})")
    for match in pattern.finditer(text):
        chunk = match.group(1)
        chunk = re.split(r"\n\s*\n|<br\s*/?>", chunk)[0]
        words.extend(_split_words(re.sub(r"<[^>]+>", " ", chunk)))
    return words


def _find_trained_words(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "trainedWords":
                found.extend(_split_words(value))
            elif isinstance(value, (dict, list)):
                _find_trained_words(value, found)
    elif isinstance(node, list):
        for value in node:
            _find_trained_words(value, found)


def words_from_html(page: str) -> list[str]:
    words: list[str] = []
    match = re.search(r'(?is)<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', page)
    if match:
        try:
            data = json.loads(match.group(1))
            _find_trained_words(data, words)
        except Exception:
            pass
    if not words:
        for match in re.finditer(r'"trainedWords"\s*:\s*(\[[^\]]*\])', page):
            try:
                words.extend(_split_words(json.loads(match.group(1))))
            except Exception:
                continue
    if not words:
        text = re.sub(r"<[^>]+>", " ", page)
        text = html.unescape(text)
        words.extend(_trigger_section(text))
    return _dedupe(words)


def fetch_words_for_path(path: str | Path, base: str = DEFAULT_BASE,
                          timeout: float = 8.0) -> tuple[list[str], str]:
    """Return (trigger_words, source_url). Empty list means not found."""
    model_id, version_id = find_model_ids(path)
    if not model_id and not version_id:
        return [], ""
    bases = []
    for candidate in (base.rstrip("/"), FALLBACK_BASE):
        if candidate and candidate not in bases:
            bases.append(candidate)

    for api_base in bases:
        if version_id:
            url = "%s/api/v1/model-versions/%d" % (api_base, version_id)
            try:
                payload = json.loads(_request(url, timeout).decode("utf-8", "replace"))
                words = words_from_payload(payload, version_id)
                if words:
                    return words, url
            except Exception:
                pass
        if model_id:
            url = "%s/api/v1/models/%d" % (api_base, model_id)
            try:
                payload = json.loads(_request(url, timeout).decode("utf-8", "replace"))
                words = words_from_payload(payload, version_id)
                if words:
                    return words, url
            except Exception:
                pass

    for page_base in bases:
        if not model_id:
            break
        url = "%s/models/%d" % (page_base, model_id)
        try:
            page = _request(url, timeout).decode("utf-8", "replace")
            words = words_from_html(page)
            if words:
                return words, url
        except Exception:
            continue
    return [], ""
