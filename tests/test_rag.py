from __future__ import annotations

import json
from pathlib import Path

import pytest

from comfyui_generator.core import rag
from comfyui_generator.core.rag import (
    RagExample, examples_for, fetch_examples, render_fewshot_block,
    retrieve_fewshot,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_no_keyword_to_query_mapping():
    assert not hasattr(rag, "select_queries")
    assert not hasattr(rag, "_BEAT_RULES")


def test_fetch_danbooru_parses_posts(monkeypatch):
    posts = [
        {"score": 120, "rating": "e",
         "tag_string_general": "1girl solo nipples pussy"},
        {"score": 1, "tag_string_general": "low score drops"},
        "not-a-dict",
        {},
    ]
    captured = {}

    def fake_get(url, proxy, timeout):
        captured["url"] = url
        return posts

    monkeypatch.setattr(rag, "_get_json", fake_get)
    examples = fetch_examples(
        "fellatio 1boy", source="danbooru", login="u", api_key="k",
        limit=10, min_score=30)
    assert len(examples) == 1
    assert examples[0].source == "danbooru"
    assert "login=u" in captured["url"] and "api_key=k" in captured["url"]


def test_fetch_yande_maps_tags_field(monkeypatch):
    posts = [
        {"score": 40, "rating": "e", "tags": "1girl 1boy sex nipples pussy"},
        {"score": 0, "tags": "low"},
    ]
    monkeypatch.setattr(rag, "_get_json", lambda url, proxy, timeout: posts)
    examples = fetch_examples("sex 1boy", source="yande", min_score=10)
    assert len(examples) == 1
    assert examples[0].source == "yande"


def test_examples_for_caches_and_degrades(tmp_path: Path, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(query, **kwargs):
        calls["n"] += 1
        return [RagExample(tags="1girl nipples", score=9, rating="e",
                           source_query=query, source="yande")]

    monkeypatch.setattr(rag, "fetch_examples", fake_fetch)
    first = examples_for("sex", index_dir=tmp_path, source="yande",
                         cache_hours=1.0, min_score=5)
    second = examples_for("sex", index_dir=tmp_path, source="yande",
                          cache_hours=1.0, min_score=5)
    assert first and second and calls["n"] == 1


def test_retrieve_uses_explicit_queries_only(tmp_path: Path, monkeypatch):
    seen = []

    def fake_fetch(query, **kwargs):
        seen.append(query)
        return [RagExample(tags="1girl %s" % query, score=5, rating="q",
                           source_query=query, source="yande")]

    monkeypatch.setattr(rag, "fetch_examples", fake_fetch)
    examples = retrieve_fewshot("sex\ncowgirl", index_dir=tmp_path,
                                max_examples=4, cache_hours=0.0)
    assert [e.source_query for e in examples] == ["sex", "cowgirl"]
    assert seen == ["sex", "cowgirl"]


def test_retrieve_empty_queries_returns_nothing(tmp_path: Path):
    assert retrieve_fewshot("", index_dir=tmp_path) == []


def test_render_block_caps_and_warns_against_copy(tmp_path: Path, monkeypatch):
    def fake_fetch(query, **kwargs):
        return [RagExample(tags="1girl tag%d" % i, score=5, rating="q",
                           source_query=query, source="yande")
                for i in range(8)]

    monkeypatch.setattr(rag, "fetch_examples", fake_fetch)
    examples = retrieve_fewshot("self", index_dir=tmp_path,
                                max_examples=3, cache_hours=0.0)
    block = render_fewshot_block(examples)
    assert len(examples) == 3
    assert "严禁照抄" in block
