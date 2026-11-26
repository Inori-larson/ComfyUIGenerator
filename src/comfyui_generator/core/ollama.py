"""Compatibility layer: the local LLM backend is now llama.cpp's llama-server.

The Ollama* names are kept so existing call sites and tests keep working; they
delegate to comfyui_generator.core.llama_server.
"""

from __future__ import annotations

import json
import re
from typing import Any

from comfyui_generator.core.llama_server import (
    LlamaServerClient, LlamaServerConfig, LlamaServerError,
    LlamaServerService, llama_server_command,
)

OllamaError = LlamaServerError
OllamaClient = LlamaServerClient
OllamaConfig = LlamaServerConfig
OllamaService = LlamaServerService


def extract_json(text: str) -> str:
    from .external_llm import _first_json_value

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    candidate = _first_json_value(text.strip())
    if candidate == text.strip() and not re.search(r"^[\[{]", candidate):
        raise ValueError("no JSON object found")
    return candidate
