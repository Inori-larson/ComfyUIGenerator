"""Optional few-shot booru example retrieval for storyboard/single prompts.

Examples are real high-score tag strings used purely as formatting/style
references. They never inject plot, characters, or required content: callers
add them as "do not copy, imitate tag density/combination" references, and any
network/auth failure silently degrades to zero examples.

Two sources are supported:
- yande.re (Moebooru API): anonymous, no Cloudflare JS challenge, default.
- danbooru.donmai.us: larger tag vocabulary but behind a Cloudflare challenge;
  reachable only via a user-provided HTTP proxy (RagConfig.proxy).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DANBOORU_BASE = "https://danbooru.donmai.us/posts.json"
YANDE_BASE = "https://yande.re/post.json"
DEFAULT_UA = "ComfyUIGenerator/1.0 (booru few-shot; contact: local-user)"


@dataclass
class RagExample:
    tags: str
    score: int
    rating: str
    source_query: str
    source: str = ""

    def as_text(self) -> str:
        return self.tags


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    if proxy:
        handler = urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_json(url: str, proxy: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={
        "User-Agent": DEFAULT_UA, "Accept": "application/json"})
    with _opener(proxy).open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _normalize_tags(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


_BLOCKED_EXAMPLE_TERMS = (
    "loli", "shota", "lolicon", "shotacon", "child", "young girl",
    "young boy", "toddler", "underage",
)


def _is_blocked(tags: str) -> bool:
    lowered = " %s " % tags.lower()
    return any((" %s " % term) in lowered for term in _BLOCKED_EXAMPLE_TERMS)


def _danbooru_posts(query: str, *, limit: int, min_score: int,
                    login: str, api_key: str, proxy: str,
                    timeout: float) -> list[RagExample]:
    params: dict[str, str] = {
        "limit": str(max(1, min(200, limit))),
        "tags": "%s score:>=%d" % (query.strip(), max(0, int(min_score))),
    }
    if login and api_key:
        params["login"] = login
        params["api_key"] = api_key
    data = _get_json(DANBOORU_BASE + "?" + urllib.parse.urlencode(params),
                     proxy, timeout)
    examples: list[RagExample] = []
    if not isinstance(data, list):
        return examples
    for post in data:
        if not isinstance(post, dict):
            continue
        try:
            score = int(post.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score < min_score:
            continue
        tags = str(post.get("tag_string_general")
                   or post.get("tag_string") or "").strip()
        normalized = _normalize_tags(tags)
        if tags and not _is_blocked(normalized):
            examples.append(RagExample(
                tags=normalized, score=score,
                rating=str(post.get("rating") or ""),
                source_query=query, source="danbooru"))
    return examples


def _yande_posts(query: str, *, limit: int, min_score: int,
                 proxy: str, timeout: float) -> list[RagExample]:
    # yande.re (Moebooru) does not use danbooru cast-count tags, and anonymous
    # search is restricted to ~2 tags, so queries stay short and score is
    # filtered locally below.
    tag_query = "rating:explicit %s" % query.strip()
    params = urllib.parse.urlencode({"limit": max(1, min(100, limit)),
                                      "tags": tag_query})
    data = _get_json(YANDE_BASE + "?" + params, proxy, timeout)
    examples: list[RagExample] = []
    if not isinstance(data, list):
        return examples
    for post in data:
        if not isinstance(post, dict):
            continue
        try:
            score = int(post.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score < min_score:
            continue
        tags = str(post.get("tags") or "").strip()
        normalized = _normalize_tags(tags)
        if tags and not _is_blocked(normalized):
            examples.append(RagExample(
                tags=normalized, score=score,
                rating=str(post.get("rating") or ""),
                source_query=query, source="yande"))
    return examples


def fetch_examples(query: str, *, login: str = "", api_key: str = "",
                   limit: int = 20, min_score: int = 5,
                   source: str = "yande", proxy: str = "",
                   timeout: float = 30.0) -> list[RagExample]:
    source = (source or "yande").lower()
    if source == "danbooru":
        return _danbooru_posts(
            query, limit=limit, min_score=min_score, login=login,
            api_key=api_key, proxy=proxy, timeout=timeout)
    return _yande_posts(
        query, limit=limit, min_score=min_score, proxy=proxy, timeout=timeout)


def _cache_path(index_dir: Path, source: str, key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                   for ch in key)[:100]
    return index_dir / ("%s_%s.json" % (source, safe))


def examples_for(query: str, *, index_dir: str | Path,
                 source: str = "yande", login: str = "", api_key: str = "",
                 proxy: str = "", limit: int = 20, min_score: int = 5,
                 cache_hours: float = 24.0,
                 log: Callable[[str], None] | None = None) -> list[RagExample]:
    directory = Path(index_dir)
    directory.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(directory, source, query.strip().lower())
    if cache_file.is_file() and cache_hours > 0:
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600.0
        if age_hours <= cache_hours:
            try:
                return [RagExample(**item)
                        for item in json.loads(
                            cache_file.read_text(encoding="utf-8"))]
            except (OSError, json.JSONDecodeError, TypeError):
                pass
    try:
        examples = fetch_examples(
            query, login=login, api_key=api_key, limit=limit,
            min_score=min_score, source=source, proxy=proxy)
    except Exception as exc:
        if log:
            log("范例源 %s 获取失败，本次不使用范例：%s" % (
                source, str(exc)[:200]))
        return []
    try:
        cache_file.write_text(
            json.dumps([e.__dict__ for e in examples], ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass
    return examples


def retrieve_fewshot(queries: str, *, index_dir: str | Path,
                     source: str = "yande", login: str = "", api_key: str = "",
                     proxy: str = "", max_examples: int = 4, limit: int = 20,
                     min_score: int = 5, cache_hours: float = 24.0,
                     log: Callable[[str], None] | None = None) -> list[RagExample]:
    examples: list[RagExample] = []
    seen: set[str] = set()
    query_list = [q.strip() for q in str(queries or "").splitlines() if q.strip()]
    for query in query_list:
        for example in examples_for(
                query, index_dir=index_dir, source=source,
                login=login, api_key=api_key, proxy=proxy,
                limit=limit, min_score=min_score, cache_hours=cache_hours,
                log=log):
            if example.tags in seen:
                continue
            seen.add(example.tags)
            examples.append(example)
            if len(examples) >= max_examples:
                return examples
    return examples


def render_fewshot_block(examples: list[RagExample]) -> str:
    if not examples:
        return ""
    lines = [
        "以下是高分二次元图站帖子的真实标签组合，仅用于学习标签密度、搭配和"
        "状态表达；严禁照抄其中的角色、场景或剧情："]
    for index, example in enumerate(examples, 1):
        lines.append("范例%d（score=%d）：%s" % (
            index, example.score, example.tags))
    return "\n".join(lines)
