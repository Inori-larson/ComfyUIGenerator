"""ComfyUI WebSocket preview frame parser.

Binary frame layout (verified against ComfyUI 0.42 server.py / protocol.py):

    [4 bytes big-endian event type][payload]

    event 1 PREVIEW_IMAGE:
        payload = [4 bytes image type, 1=JPEG 2=PNG][image bytes]
    event 3 TEXT:
        payload = UTF-8 JSON object
    event 4 PREVIEW_IMAGE_WITH_METADATA:
        payload = [4 bytes json length][json metadata][image bytes]
        metadata contains prompt_id, node_id, image_type (mime)

The parser never raises on malformed input; it returns None instead so a bad
frame cannot kill the UI thread.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

PREVIEW_IMAGE = 1
UNENCODED_PREVIEW_IMAGE = 2
TEXT = 3
PREVIEW_IMAGE_WITH_METADATA = 4

_IMAGE_TYPES = {1: "JPEG", 2: "PNG"}


@dataclass
class PreviewFrame:
    event: int
    image_type: str
    data: bytes
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_id(self) -> str | None:
        return self.meta.get("prompt_id")

    @property
    def node_id(self) -> str | None:
        value = self.meta.get("node_id")
        return str(value) if value is not None else None

    @property
    def mime(self) -> str:
        return "image/png" if self.image_type == "PNG" else "image/jpeg"

    @property
    def suffix(self) -> str:
        return ".png" if self.image_type == "PNG" else ".jpg"


def parse_binary_frame(payload: bytes) -> PreviewFrame | dict[str, Any] | None:
    """Parse a binary WebSocket frame into a PreviewFrame or a text event dict."""
    if not payload or len(payload) < 4:
        return None
    event = struct.unpack(">I", payload[:4])[0]

    if event == PREVIEW_IMAGE:
        if len(payload) < 8:
            return None
        type_num = struct.unpack(">I", payload[4:8])[0]
        return PreviewFrame(event, _IMAGE_TYPES.get(type_num, "JPEG"), payload[8:])

    if event == PREVIEW_IMAGE_WITH_METADATA:
        if len(payload) < 8:
            return None
        meta_len = struct.unpack(">I", payload[4:8])[0]
        end = 8 + meta_len
        if meta_len <= 0 or len(payload) < end:
            return None
        try:
            meta = json.loads(payload[8:end].decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return None
        if not isinstance(meta, dict):
            return None
        mime = str(meta.get("image_type", "")).lower()
        image_type = "PNG" if "png" in mime else "JPEG"
        return PreviewFrame(event, image_type, payload[end:], meta)

    if event == TEXT:
        try:
            data = json.loads(payload[4:].decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    return None


def parse_text_frame(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
