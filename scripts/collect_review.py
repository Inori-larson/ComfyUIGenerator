"""Read-only evidence collector for a generation task.

Extracts PNG prompt metadata (nodes 6/7/9), project counts and trace event
counts. It never judges story semantics or rewrites any artifact.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _decode_text_chunk(kind: bytes, payload: bytes) -> tuple[str, str]:
    try:
        if kind == b"tEXt":
            key, separator, value = payload.partition(b"\x00")
            return (key.decode("latin-1"), value.decode("latin-1", "replace")) if separator else ("", "")
        if kind == b"zTXt":
            key, separator, rest = payload.partition(b"\x00")
            if not separator or not rest:
                return "", ""
            value = zlib.decompress(rest[1:])
            return key.decode("latin-1"), value.decode("latin-1", "replace")
        if kind == b"iTXt":
            parts = payload.split(b"\x00", 5)
            if len(parts) < 6:
                return "", ""
            value = parts[5]
            if parts[1] == b"\x01":
                value = zlib.decompress(value)
            return parts[0].decode("latin-1"), value.decode("utf-8", "replace")
    except Exception:
        return "", ""
    return "", ""


def png_text_chunks(path: str | Path) -> dict[str, str]:
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return {}
    position = len(PNG_SIGNATURE)
    texts: dict[str, str] = {}
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        position += length + 12
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            key, value = _decode_text_chunk(kind, payload)
            if key:
                texts[key] = value
        if kind == b"IEND":
            break
    return texts


def extract_nodes(texts: dict[str, str]) -> dict[str, Any]:
    raw = texts.get("prompt") or texts.get("Prompt") or ""
    if not raw:
        return {"available": False}
    try:
        graph = json.loads(raw)
    except (ValueError, TypeError):
        return {"available": False, "parse_error": True}
    if not isinstance(graph, dict):
        return {"available": False, "parse_error": True}

    def node_text(node_id: str) -> str:
        node = graph.get(node_id)
        if not isinstance(node, dict):
            return ""
        inputs = node.get("inputs")
        return str(inputs.get("text") or "") if isinstance(inputs, dict) else ""

    seed_node = graph.get("9")
    seed = ""
    if isinstance(seed_node, dict) and isinstance(seed_node.get("inputs"), dict):
        seed = str(seed_node["inputs"].get("seed") or "")
    return {
        "available": True,
        "node6": node_text("6"),
        "node7": node_text("7"),
        "node9_seed": seed,
    }


def _tag_set(text: str) -> set[str]:
    return {
        token.strip().lower()
        for token in str(text or "").split(",")
        if token.strip()
    }


def _count_kinds(shots: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for shot in shots:
        for item in (shot.get(field) or []):
            if isinstance(item, dict):
                kind = str(item.get("kind") or "")
                if kind:
                    counts[kind] = counts.get(kind, 0) + 1
    return counts


def _count_field(shots: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for shot in shots:
        value = str(shot.get(field) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _trace_counts(log_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not log_dir.is_dir():
        return counts
    for path in sorted(log_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = str(json.loads(line).get("event") or "")
                except (ValueError, TypeError, AttributeError):
                    continue
                if event:
                    counts[event] = counts.get(event, 0) + 1
    return counts


def collect(task_dir: str | Path, project_path: str | Path | None = None,
            log_dir: str | Path | None = None) -> dict[str, Any]:
    task = Path(task_dir)
    images = sorted(task.glob("*.png")) if task.is_dir() else []
    report: dict[str, Any] = {
        "task_dir": str(task),
        "image_count": len(images),
        "metadata": {
            "with_prompt": 0,
            "without_prompt": 0,
            "node6_contains_project_prompt": 0,
        },
        "nodes_sample": {},
    }
    prompt_by_shot: dict[str, str] = {}
    project = None
    if project_path:
        try:
            project = json.loads(
                Path(project_path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            project = None
        if isinstance(project, dict):
            prompt_by_shot = {
                str(shot.get("id") or ""): str(shot.get("prompt") or "")
                for shot in (project.get("shots") or [])
                if isinstance(shot, dict)
            }
    for image in images:
        nodes = extract_nodes(png_text_chunks(image))
        if not nodes.get("available"):
            report["metadata"]["without_prompt"] += 1
            continue
        report["metadata"]["with_prompt"] += 1
        if not report["nodes_sample"]:
            report["nodes_sample"] = {"image": image.name, **nodes}
        shot_tags = _tag_set(prompt_by_shot.get(image.name.split("_", 1)[0]))
        if shot_tags and shot_tags <= _tag_set(nodes["node6"]):
            report["metadata"]["node6_contains_project_prompt"] += 1
    if isinstance(project, dict):
        shots = [shot for shot in (project.get("shots") or [])
                 if isinstance(shot, dict)]
        report["project"] = {
            "shot_count": len(shots),
            "rendered_count": len(project.get("outputs") or []),
            "finding_kinds": _count_kinds(shots, "findings"),
            "contract_finding_kinds": _count_kinds(shots, "contract_findings"),
            "outline_finding_kinds": _count_kinds(shots, "outline_findings"),
            "render_finding_kinds": _count_kinds(shots, "render_findings"),
            "contract_status": _count_field(shots, "contract_status"),
        }
    if log_dir:
        report["trace_events"] = _trace_counts(Path(log_dir))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--project")
    parser.add_argument("--log-dir")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = collect(args.task, args.project, args.log_dir)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
