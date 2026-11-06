"""Shared pytest fixtures and test doubles."""

from __future__ import annotations

from typing import Any

import pytest


class ScriptedLLMClient:
    """Duck-typed stand-in for the external/ollama client.

    Responses are either:
    - an ordered list popped per chat_json call, or
    - a dispatch mapping keyed by the schema (by required key tuple) or stage.
    """

    def __init__(self, responses: Any = None):
        if isinstance(responses, dict):
            self.dispatch = dict(responses)
            self.queue = []
        else:
            self.dispatch = {}
            self.queue = list(responses or [])
        self.calls: list[tuple[str, list[dict[str, str]], dict[str, Any]]] = []

    @staticmethod
    def _key(schema: Any) -> tuple[str, ...]:
        if isinstance(schema, dict):
            return tuple(sorted(schema.get("required") or ()))
        return ()

    def add(self, response: dict[str, Any]) -> None:
        self.queue.append(response)

    def chat_json(self, model: str, messages: list[dict[str, str]],
                  **kwargs: Any) -> dict[str, Any]:
        self.calls.append((model, messages, kwargs))
        key = self._key(kwargs.get("schema"))
        if key in self.dispatch:
            value = self.dispatch[key]
        elif () in self.dispatch:
            value = self.dispatch[()]
        elif self.queue:
            value = self.queue.pop(0)
        else:
            raise AssertionError(
                "ScriptedLLMClient has no response for call %d (schema=%s)" % (
                    len(self.calls), kwargs.get("schema")))
        if callable(value):
            value = value(model, messages, **kwargs)
        return value

    @property
    def models(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def llm():
    return ScriptedLLMClient([])


def pass_verdict(ids: list[str]) -> dict[str, Any]:
    return {"shots": [{"id": sid, "valid": True, "issues": []} for sid in ids]}


def fail_verdict(shot_id: str, issues: list[str], *, prompt: str = "",
                 negative: str = "", script: str = "",
                 cast: str = "", phase: str = "", beat: str = "",
                 clothing: str = "", scene: str = "", camera: str = "",
                 nsfw: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": shot_id, "valid": False, "issues": list(issues),
    }
    for key, value in (
            ("prompt", prompt), ("negative", negative), ("script", script),
            ("cast", cast), ("phase", phase), ("beat", beat),
            ("clothing", clothing), ("scene", scene), ("camera", camera),
            ("nsfw", nsfw)):
        if value:
            item[key] = value
    return {"shots": [item]}
