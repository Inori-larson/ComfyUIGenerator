"""Booru tag database: optional danbooru.csv/alias lookup and shipped layer vocab.

The tag database is an *audit* aid only. It canonicalises documented alias
tags and answers whether a tag is a known danbooru tag. It never invents or
injects semantic content into prompts; callers decide what to do with results.

The shipped layering vocabulary lives in presets/tagdb/layering.json and is
loaded even when no danbooru.csv export is configured, so clothing layer
validation works fully offline.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from comfyui_generator.core.config import PRESET_DIR

LAYER_PATH = PRESET_DIR / "tagdb" / "layering.json"


def _normalise_tag(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    return " ".join(text.split())


@dataclass
class TagDatabase:
    known: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    layers: dict[str, list[str]] = field(default_factory=dict)

    def has_table(self) -> bool:
        return bool(self.known)

    def is_known(self, tag: str) -> bool:
        core = _normalise_tag(tag)
        if not core:
            return True
        return core in self.known or _normalise_tag(self.canonical(core)) in self.known

    def canonical(self, tag: str) -> str:
        return self.aliases.get(_normalise_tag(tag), str(tag or "").strip())

    def canonical_map(self, tags: list[str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for tag in tags:
            target = self.canonical(tag)
            if target and target != tag:
                mapping[tag] = target
        return mapping

    def layer_vocab(self) -> dict[str, list[str]]:
        return self.layers


def _read_tag_csv(path: Path) -> tuple[set[str], dict[str, str]]:
    known: set[str] = set()
    aliases: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            name = _normalise_tag(row[0])
            if not name:
                continue
            known.add(name)
            if len(row) >= 4 and row[3].strip():
                for alias in row[3].split(","):
                    alias_key = _normalise_tag(alias)
                    if alias_key:
                        aliases.setdefault(alias_key, row[0].strip())
    return known, aliases


def _read_alias_csv(path: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            alias_key = _normalise_tag(row[0])
            target = row[1].strip()
            if alias_key and target:
                aliases.setdefault(alias_key, target)
    return aliases


def load_layers(path: str | Path | None = None) -> dict[str, list[str]]:
    target = Path(path) if path else LAYER_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    layers: dict[str, list[str]] = {}
    for key, values in raw.items():
        if isinstance(values, list):
            layers[key] = [_normalise_tag(v) for v in values if str(v).strip()]
    return layers


def load_tag_database(csv_path: str | Path | None = None,
                      alias_path: str | Path | None = None,
                      layer_path: str | Path | None = None) -> TagDatabase:
    """Load danbooru.csv + tag_aliases.csv when available; always load layers.

    Missing or malformed files degrade to an offline database that still
    contains only the shipped layering vocabulary.
    """
    known: set[str] = set()
    aliases: dict[str, str] = {}
    if csv_path:
        tag_file = Path(csv_path)
        if tag_file.is_file():
            try:
                known, csv_aliases = _read_tag_csv(tag_file)
                aliases.update(csv_aliases)
            except (OSError, csv.Error):
                known, aliases = set(), {}
    if alias_path:
        alias_file = Path(alias_path)
        if alias_file.is_file():
            try:
                aliases.update(_read_alias_csv(alias_file))
            except (OSError, csv.Error):
                pass
    return TagDatabase(known=known, aliases=aliases, layers=load_layers(layer_path))


@lru_cache(maxsize=8)
def cached_tag_database(csv_path: str = "", alias_path: str = "") -> TagDatabase:
    return load_tag_database(csv_path or None, alias_path or None)
