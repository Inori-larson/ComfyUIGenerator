import json
import struct

from comfyui_generator.core.preview import (
    PREVIEW_IMAGE,
    PREVIEW_IMAGE_WITH_METADATA,
    TEXT,
    PreviewFrame,
    parse_binary_frame,
    parse_text_frame,
)


def test_parse_unencoded_preview_event_one():
    payload = struct.pack(">I", PREVIEW_IMAGE) + struct.pack(">I", 1) + b"jpeg-bytes"
    frame = parse_binary_frame(payload)
    assert isinstance(frame, PreviewFrame)
    assert frame.image_type == "JPEG"
    assert frame.data == b"jpeg-bytes"
    assert frame.prompt_id is None
    assert frame.suffix == ".jpg"


def test_parse_preview_with_metadata_event_four():
    meta = {"prompt_id": "pid-1", "node_id": "9", "image_type": "image/png"}
    raw_meta = json.dumps(meta).encode()
    payload = (
        struct.pack(">I", PREVIEW_IMAGE_WITH_METADATA)
        + struct.pack(">I", len(raw_meta))
        + raw_meta
        + b"png-bytes"
    )
    frame = parse_binary_frame(payload)
    assert isinstance(frame, PreviewFrame)
    assert frame.image_type == "PNG"
    assert frame.prompt_id == "pid-1"
    assert frame.node_id == "9"
    assert frame.data == b"png-bytes"
    assert frame.mime == "image/png"


def test_parse_text_event():
    payload = struct.pack(">I", TEXT) + b'{"type":"executing","data":{"node":"9"}}'
    event = parse_binary_frame(payload)
    assert event == {"type": "executing", "data": {"node": "9"}}


def test_malformed_frames_are_ignored():
    assert parse_binary_frame(b"") is None
    assert parse_binary_frame(b"\x00") is None
    assert parse_binary_frame(struct.pack(">I", PREVIEW_IMAGE)) is None
    assert parse_binary_frame(struct.pack(">I", PREVIEW_IMAGE_WITH_METADATA) + b"\x00") is None
    meta = struct.pack(">I", 4) + b"nope"
    assert parse_binary_frame(struct.pack(">I", PREVIEW_IMAGE_WITH_METADATA) + meta) is None


def test_parse_text_frame():
    assert parse_text_frame('{"type":"progress"}') == {"type": "progress"}
    assert parse_text_frame("not json") is None
    assert parse_text_frame("[1,2]") is None
