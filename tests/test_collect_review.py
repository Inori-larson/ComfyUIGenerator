from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import collect_review


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _png(texts: dict[str, str]) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    chunks = [
        collect_review.PNG_SIGNATURE,
        _chunk(b"IHDR", header),
    ]
    for key, value in texts.items():
        chunks.append(_chunk(b"tEXt", key.encode("latin-1") + b"\x00"
                             + value.encode("latin-1", "replace")))
    chunks.append(_chunk(b"IEND", b""))
    return b"".join(chunks)


def test_extract_nodes_from_png_metadata(tmp_path):
    graph = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive tags"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative tags"}},
        "9": {"class_type": "KSampler", "inputs": {"seed": 12345}},
    }
    payload = json.dumps(graph, ensure_ascii=False)
    image = tmp_path / "01_shot_01_00001_.png"
    image.write_bytes(_png({"prompt": payload}))
    texts = collect_review.png_text_chunks(image)
    nodes = collect_review.extract_nodes(texts)
    assert nodes["available"] is True
    assert nodes["node6"] == "positive tags"
    assert nodes["node7"] == "negative tags"
    assert nodes["node9_seed"] == "12345"


def test_collect_counts_images_and_project(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    graph = {
        "6": {"inputs": {"text": "1girl solo, smile"}},
        "7": {"inputs": {"text": "bad quality"}},
        "9": {"inputs": {"seed": 7}},
    }
    (task / "01_shot_01_00001_.png").write_bytes(
        _png({"prompt": json.dumps(graph)}))
    project = {
        "shots": [{"id": "01", "prompt": "1girl solo, smile",
                   "contract_status": "valid",
                   "findings": [{"kind": "shot_stall", "severity": "P2"}]}],
        "outputs": [{"shot_id": "01"}],
    }
    project_path = tmp_path / "project.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    report = collect_review.collect(task, project_path)
    assert report["image_count"] == 1
    assert report["metadata"]["with_prompt"] == 1
    assert report["metadata"]["node6_contains_project_prompt"] == 1
    assert report["project"]["finding_kinds"] == {"shot_stall": 1}
    assert report["project"]["contract_status"] == {"valid": 1}
