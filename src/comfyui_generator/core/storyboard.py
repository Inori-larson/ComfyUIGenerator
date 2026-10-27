"""Ollama storyboard generation: premise -> continuous shot list."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.tags import limit_tags

SHOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["id", "name", "prompt"],
            },
        }
    },
    "required": ["shots"],
}

BEATS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        }
    },
    "required": ["beats"],
}

SYSTEM_PROMPT = (
    "You are a professional NSFW anime storyboard prompt engineer.\n"
    "Task: Generate a multi-panel continuous English prompt in Danbooru style based on the plot given by the user.\n"
    "The following rules must be adhered to, otherwise it will be considered a failure:\n"
    "1. Output ONLY JSON matching the schema, no prose, no markdown.\n"
    "2. Each `prompt` is comma-separated ENGLISH Danbooru tags (up to 200), no sentences.\n"
    "3. The appearance description of the character must remain completely consistent across all grids, with no changes to hair color, eye color, body type, etc.\n"
    "4. The clothing/nudity, posture, movements, expressions, and camera angles must progress and change with the plot, maintaining logical coherence.\n"
    "5. If it is an NSFW scene, it must include accurate NSFW tags (nude, pussy, masturbation, spread legs, etc.), and it is prohibited to avoid, weaken, blur or replace with vague words.\n"
    "6. The beginning must be preceded by: masterpiece, best quality, absurdres, newest."
    "7. Start with shot size (wide shot / medium shot / close-up / full body), then camera angle "
    "(from behind, from side, from above, dutch angle...), then pose/action, expression, location, "
    "time of day, weather, lighting.\n"
    "8. `name` is ascii snake_case, `id` is a two-digit string like \"01\".\n"
    "9. Shots must form ONE continuous arc (establishing -> development -> climax -> ending) with "
    "consistent location and continuity, and vary shot sizes like a manga page."
)


def clean_prompt(text: Any) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"^\s*(prompt|tags|positive)\s*[:：]\s*", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip().strip(",;.")


def slugify(text: Any, fallback: str = "") -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    value = re.sub(r"_+", "_", value)
    return value[:40] or fallback


def normalize(raw: dict[str, Any] | list[Any], wanted: int, fallback_prefix: str,
              start: int = 1, used_names: list[str] | None = None) -> list[dict[str, str]]:
    shots: list[dict[str, str]] = []
    used = {name.lower() for name in (used_names or [])}
    items = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Model response has no 'shots' array.")
    for index, item in enumerate(items[:wanted]):
        if not isinstance(item, dict):
            continue
        prompt = clean_prompt(item.get("prompt") or item.get("tags") or item.get("description"))
        if not prompt:
            continue
        base = slugify(item.get("name") or "%s_%02d" % (fallback_prefix, index + 1),
                       "shot_%02d" % (index + 1))
        name, counter = base, 2
        while name.lower() in used:
            name = "%s_%d" % (base, counter)
            counter += 1
        used.add(name.lower())
        shots.append({"id": "%02d" % (start + len(shots)), "name": name,
                      "prompt": limit_tags(prompt)})
    if not shots:
        raise ValueError("Model returned no usable shots.")
    return shots


@dataclass
class StoryboardOptions:
    model: str
    shots: int = 6
    chunk: int = 12
    temperature: float = 0.8
    num_predict: int = 0
    num_ctx: int = 0
    keep_alive: str = "5m"
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    reference_tags: list[str] = field(default_factory=list)
    log: Callable[[str], None] = field(default=lambda _msg: None)


def build_messages(premise: str, shots: int, character_tags: str, style_positive: str,
                   setting: str, prior: list[dict[str, str]],
                   total: int | None = None,
                   beats: list[str] | None = None,
                   reference_tags: list[str] | None = None) -> list[dict[str, str]]:
    user = [
        "Premise: %s" % premise,
        "Number of shots to write now: %d%s" % (
            shots, (" (part %d-%d of %d)" % (len(prior) + 1, len(prior) + shots, total) if total else "")),
        "Character (already handled, do not describe): %s" % (character_tags or "generic"),
        "Visual style: %s" % (style_positive or ""),
    ]
    if setting.strip():
        user.append("Setting / art direction: %s" % setting.strip())
    if reference_tags:
        user.append(
            "REFERENCE TAGS (complete supported vocabulary; select only the few tags that fit "
            "this shot, never echo the list): %s" % ", ".join(reference_tags))
    if beats:
        user.append("Follow these story beats IN ORDER, exactly one shot per beat:\n" +
                    "\n".join("%d. %s" % (len(prior) + index + 1, beat)
                              for index, beat in enumerate(beats)))
    if prior:
        tail = "; ".join("%s %s" % (shot["id"], shot["prompt"]) for shot in prior[-16:])
        user.append("Shots already written (continue AFTER them):\n" + tail)
        user.append("Do NOT repeat any previous action, camera angle, location beat or shot name. "
                    "Every new shot must advance the story.")
    user.append(
        "Continue this premise as one continuous anime sequence, keeping the same location arc and "
        "escalating emotion. Vary shot sizes. Start numbering from %d." % (len(prior) + 1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user)},
    ]


def _plan_beats(client: OllamaClient, model: str, premise: str, shots: int,
                character_tags: str) -> list[str]:
    messages = [
        {"role": "system", "content":
         "You are a screenwriter. Break a premise into exactly %d ordered story beats. "
         "Each beat is ONE short English sentence describing what happens in one illustration. "
         "Beats must form a continuous arc with no repeated action. Output JSON only." % shots},
        {"role": "user", "content": "Premise: %s\nCharacter: %s" % (premise, character_tags)},
    ]
    raw = client.chat_json(
        model, messages, schema=BEATS_SCHEMA,
        temperature=0.7,
        num_predict=min(8192, 200 + shots * 40),
        num_ctx=min(16384, 2048 + shots * 30),
        keep_alive="5m",
    )
    items = raw.get("beats") if isinstance(raw, dict) else raw
    beats = [clean_prompt(item.get("summary", "")) for item in (items or []) if isinstance(item, dict)]
    beats = [beat for beat in beats if beat]
    if len(beats) < shots:
        beats += ["continue the story"] * (shots - len(beats))
    return beats[:shots]


def generate_storyboard(client: OllamaClient, premise: str,
                        options: StoryboardOptions,
                        initial_shots: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """Generate shots in chunks with beat planning for long stories.

    ``initial_shots`` lets a single-image result become shot 1 of a story; the
    remaining shots are generated with the existing shot as prior context.
    """
    initial = [dict(shot) for shot in (initial_shots or [])]
    shots = max(len(initial), int(options.shots))
    chunk = max(1, int(options.chunk))
    log = options.log
    result: list[dict[str, str]] = initial[:shots]
    if len(result) >= shots:
        return result[:shots]

    beats: list[str] | None = None
    if shots > chunk and not initial:
        log("Planning %d story beats ..." % shots)
        beats = _plan_beats(client, options.model, premise, shots,
                            options.character_tags)

    tries = 0
    max_tries = (shots // chunk) + 4
    while len(result) < shots and tries < max_tries:
        need = min(chunk, shots - len(result))
        beat_slice = beats[len(result):len(result) + need] if beats else None
        messages = build_messages(
            premise, need, options.character_tags, options.style_positive,
            options.setting, result, shots, beat_slice,
            options.reference_tags)
        num_predict = options.num_predict or min(16384, 400 + 220 * need)
        num_ctx = options.num_ctx or min(
            32768, 4096 + 80 * len(result) + 10 * len(options.reference_tags))
        raw = client.chat_json(
            options.model, messages, schema=SHOT_SCHEMA,
            temperature=options.temperature,
            num_predict=num_predict,
            num_ctx=num_ctx,
            keep_alive=options.keep_alive,
        )
        part = normalize(raw, need, slugify(premise, "story") or "story",
                         start=len(result) + 1,
                         used_names=[shot["name"] for shot in result])
        result.extend(part)
        tries += 1
        log("Chunk %d: +%d shots (%d/%d)" % (tries, len(part), len(result), shots))
        if not part:
            break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    return result[:shots]
