"""Structural validation of the story beats declared by the LLM.

Semantics belong to the AI. This module never parses the premise or assigns
shots to beats by text similarity. It only checks the structure the AI
declared: every beat id used by a shot exists, the beat sequence never goes
backwards, and the last declared beat is reached by the final shot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoryContract:
    beats: list[dict[str, Any]] = field(default_factory=list)

    @property
    def beat_ids(self) -> list[str]:
        return [str(beat.get("id") or "") for beat in self.beats
                if str(beat.get("id") or "")]

    @property
    def has_beats(self) -> bool:
        return len(self.beat_ids) >= 2


def contract_from_generation(raw: Any) -> StoryContract:
    """Read the AI-declared `beats` array; do not infer beats from text."""
    if not isinstance(raw, dict):
        return StoryContract()
    beats = raw.get("beats")
    if not isinstance(beats, list):
        return StoryContract()
    clean = [beat for beat in beats if isinstance(beat, dict)]
    return StoryContract(beats=clean)


def validate_contract(shots: list[dict[str, Any]],
                      contract: StoryContract) -> list[dict[str, Any]]:
    if not contract.has_beats:
        return []
    declared = contract.beat_ids
    known = set(declared)
    sequence: list[str] = []
    for shot in shots:
        beat_id = str(shot.get("beat_id") or "").strip()
        if beat_id and beat_id in known:
            sequence.append(beat_id)
        elif beat_id:
            return [{
                "kind": "contract_unknown_beat",
                "severity": "P2",
                "message": "镜头引用了未声明的 beat：%s" % beat_id,
                "evidence": beat_id,
            }]
    findings: list[dict[str, Any]] = []
    used = set(sequence)
    for beat_id in declared:
        if beat_id not in used:
            findings.append({
                "kind": "contract_event_missing",
                "severity": "P1",
                "message": "AI 声明的 beat 没有对应镜头：%s" % beat_id,
                "evidence": beat_id,
            })
    ranks = {beat_id: index for index, beat_id in enumerate(declared)}
    for previous, current in zip(sequence, sequence[1:]):
        if ranks[current] < ranks[previous]:
            findings.append({
                "kind": "contract_order_violation",
                "severity": "P2",
                "message": "beat 顺序回退：%s → %s" % (previous, current),
                "evidence": "",
            })
            break
    if sequence and sequence[-1] != declared[-1]:
        findings.append({
            "kind": "contract_ending_mismatch",
            "severity": "P1",
            "message": "末镜没有落在最后一个 beat：%s" % declared[-1],
            "evidence": declared[-1],
        })
    return findings
