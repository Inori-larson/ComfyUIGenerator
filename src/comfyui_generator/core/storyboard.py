"""Storyboard generation: premise -> one direct shot list."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.mechanical import (
    normalize_prompt_text,
    normalize_english_prompt_text,
)
from comfyui_generator.core.trace import trace_event

PROMPT_COVERAGE = (
    "覆盖维度：角色身份与外观、服装/裸露状态、当前可见身体部位、姿势、动作、表情、"
    "场景/地点、镜头景别、机位/角度、构图、光线/时间、NSFW 状态。"
)

BOORU_WORKFLOW = (
    "按 cast -> 服装/裸露 -> 姿势 -> 动作 -> 表情 -> NSFW -> 场景 -> 光线 -> 镜头"
    "的顺序组装标签；已经脱掉的服装标签必须删除；每镜换姿势和互动，不连续重复。"
)

STORYBOARD_SYSTEM = (
    "你是二次元 NSFW 剧情分镜编剧。请根据用户剧情，一次直接生成完整分镜。\n"
    "要求：\n"
    "1. 按用户指定的镜数生成，id 从 01 连续编号到最后一镜，不能少、重、跳。\n"
    "2. 每镜的 prompt 只写英文 Danbooru 标签，用英文逗号分隔；镜头之间的剧情、"
    "服装、动作、场景自然连贯，并按顺序覆盖用户剧情中的全部情节。\n"
    "3. 大场景必须严格使用用户给出的场景（例如“大场景：电影院”就整片都在电影院），"
    "禁止换成其他地点或另起场景；只有剧情明确写出移动时才换场景；"
    "同一场景内可以自然扩展家具、光线、天气等细节。用户没有给场景时才自行设定并保持一致。\n"
    "4. 服装只能使用用户给出的初始服装里实际列出的单品，禁止发明或添加初始服装之外的"
    "衣物、内衣、丝袜、裤袜、鞋、配饰等；颜色、材质、款式必须与初始服装完全一致，"
    "不能更换颜色、改色或替换成同类其他款式。\n"
    "5. 情趣服装（丝袜、裤袜、高跟鞋、内裤等）只允许破坏、半脱、拨开或挂腿，"
    "不允许全脱或消失。\n"
    "6. 非情趣服装（外套、制服、上衣、裙子、裤子等）必须按剧情逐步脱掉："
    "不能一开场就全裸，也不能一次脱完；每镜只脱一件或一个层级，"
    "从外到内依次进行。\n"
    "7. 服装状态必须连贯、逐镜递进，禁止跳变：已脱下、半脱或破损的衣物不得无故复原；"
    "还没脱的不能突然消失；相邻镜头之间不能反复穿脱或来回变化破损位置。\n"
    "8. 体液状态（精液、淫水、唾液、汗等）也必须连贯：一旦出现就保留在对应部位或"
    "逐渐累积、变化，直到剧情明确清理；不能在相邻镜头无故消失；未发生对应行为前"
    "不能提前出现。\n"
    "9. 只输出 JSON：{\"shots\":[{\"id\":\"01\",\"prompt\":\"英文标签\"}]}，不要中文描述，不要解释。"
)

STORYBOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["id", "prompt"],
            },
        }
    },
    "required": ["shots"],
}


def _scene_from_premise(premise: str) -> str:
    for line in str(premise or "").splitlines():
        stripped = line.strip()
        for label in ("大场景", "场景"):
            if not stripped.startswith(label):
                continue
            remainder = stripped[len(label):]
            if not remainder or remainder[0] in "：: ":
                return remainder.lstrip("：: ").strip()
    return ""


def build_storyboard_messages(premise: str, total: int,
                              setting: str = "",
                              strip_appearance: bool = False
                              ) -> list[dict[str, str]]:
    user = [
        "用户剧情：\n%s" % premise,
        "目标镜数：%d" % total,
    ]
    scene = _scene_from_premise(premise)
    if scene:
        user.append(
            "本片大场景固定为『%s』：全部镜头都必须在这个场景里，"
            "不得更换地点或另起场景；只有剧情明确写出移动时才换。" % scene)
    if setting.strip():
        user.append("附加要求：%s" % setting.strip())
    if strip_appearance:
        user.append("已启用角色 LoRA：不要生成角色发色、瞳色、发型、脸、身体特征或角色名；"
                    "这些由 LoRA 和激活标签负责，只写剧情画面。")
    user.append("请一次生成全部 %d 镜。" % total)
    return [
        {"role": "system", "content": STORYBOARD_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


@dataclass
class StoryboardOptions:
    model: str
    shots: int = 6
    temperature: float = 0.6
    num_predict: int = 0
    num_ctx: int = 0
    timeout: float = 240.0
    keep_alive: str = "5m"
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    strip_appearance: bool = False
    full_story: bool = False
    on_partial: Callable[[list[dict[str, str]]], None] | None = None
    log: Callable[[str], None] = field(default=lambda _msg: None)


def raw_prompt(text: Any) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"^\s*(prompt|tags|positive|提示词|标签|正向)\s*[:：]\s*",
                   "", value, flags=re.I)
    return value.strip(",;. ")


def slugify(text: Any, fallback: str = "") -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    value = re.sub(r"_+", "_", value)
    return value[:40] or fallback


def normalize_shots(raw: Any, wanted: int) -> list[dict[str, str]]:
    items = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Response has no 'shots' array.")
    shots: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prompt = normalize_english_prompt_text(raw_prompt(item.get("prompt")))
        if not prompt:
            continue
        number = "%02d" % (len(shots) + 1)
        shot = {
            "id": str(item.get("id") or number).strip() or number,
            "name": "shot_%s" % number,
            "prompt": prompt,
        }
        expansions = item.get("ai_expansions")
        if isinstance(expansions, list):
            values = [str(v).strip() for v in expansions if str(v).strip()]
            if values:
                shot["ai_expansions"] = values
        keyframe = str(item.get("keyframe_prompt") or "").strip()
        if keyframe:
            shot["keyframe_prompt"] = keyframe
        shots.append(shot)
    if not shots:
        raise ValueError("Model returned no usable shots.")
    renumber_shots(shots)
    return shots[:wanted] if wanted else shots


def renumber_shots(shots: list[dict[str, Any]]) -> None:
    for index, shot in enumerate(shots, 1):
        if isinstance(shot, dict):
            shot["id"] = "%02d" % index
            shot["name"] = "shot_%02d" % index


def normalize_shot_casts(shots: list[dict[str, Any]]) -> None:
    return None


def extract_premise_beats(premise: str) -> list[str]:
    beats: dict[int, str] = {}
    for line in str(premise or "").splitlines():
        match = re.match(r"^\s*(\d{1,2})\s*[.、)]\s*(.+?)\s*$", line)
        if not match:
            continue
        number = int(match.group(1))
        text = match.group(2).strip()
        if text:
            beats[number] = text
    if not beats:
        return []
    return [beats[number] for number in sorted(beats)]


def _section_text(premise: str, labels: tuple[str, ...]) -> str:
    lines = str(premise or "").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        for label in labels:
            if not stripped.startswith(label):
                continue
            text = stripped[len(label):].lstrip("：: ").strip()
            extra = []
            for following in lines[index + 1:]:
                following_text = following.strip()
                if not following_text:
                    continue
                if _TOP_SECTION_RE.match(following_text):
                    break
                extra.append(following_text)
            return "\n".join([text] + extra).strip()
    return ""


def _normalize_weight_colons(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"\(([^()]+?)\s*[:：]\s*(\d+(?:\.\d+)?)\)",
        r"\1(\2)", value)
    return re.sub(
        r"(?<![(\w])([A-Za-z][A-Za-z0-9 _\-]*?)\s*[:：]\s*(\d+(?:\.\d+)?)",
        r"\1(\2)", value)


def _split_tags(text: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in re.split(r"[,，、;；|\n]+", str(text or "")):
        tag = tag.strip(" .")
        weighted = re.fullmatch(r"(.+?)\((\d+(?:\.\d+)?)\)", tag)
        if weighted:
            tag = "(%s:%s)" % (weighted.group(1).strip(), weighted.group(2))
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def _split_character_entries(text: str) -> dict[str, str]:
    value = str(text or "").strip()
    if not value:
        return {}
    parts = [part.strip() for part in re.split(
        r"[；;\n]|[，,、](?=[^，,、:：；;\n]{1,24}[:：])", value)
        if part.strip()]
    entries: dict[str, str] = {}
    for part in parts:
        match = re.match(r"^([^:：]{1,24})[:：]\s*(.+)$", part)
        if match:
            entries[match.group(1).strip()] = match.group(2).strip()
        elif len(parts) == 1:
            entries[""] = part
    if not entries:
        entries[""] = value
    return entries


def _infer_gender(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts).lower()
    if re.search(r"男主|男性|男孩|男人|少年|青年|1boy|\bboy\b|\bmale\b|"
                 r"\bman\b|\bmen\b|(?:penis|cock)\b", text):
        return "boy"
    if re.search(r"女主|女性|女孩|女人|少女|1girl|\bgirl\b|\bfemale\b|"
                 r"\bwoman\b|\bwomen\b|她", text):
        return "girl"
    return "other"


@dataclass
class CharacterProfile:
    key: str
    name: str = ""
    gender: str = "girl"
    appearance: list[str] = field(default_factory=list)
    initial_clothing: list[str] = field(default_factory=list)
    appearance_locked: bool = False


def parse_character_profiles(premise: str) -> list[CharacterProfile]:
    role_text = _section_text(premise, ("角色设定：", "角色设定:", "角色标签：",
                                        "角色标签:", "角色：", "角色:",
                                        "人物设定：", "人物设定:", "人物：", "人物:"))
    clothing_text = _normalize_weight_colons(_section_text(
        premise, ("初始服装：", "初始服装:", "初始装扮：",
                  "初始装扮:", "服装：", "服装:")))
    appearance_text = _normalize_weight_colons(_section_text(
        premise, ("外貌身材：", "外貌身材:", "角色外貌：", "角色外貌:",
                  "人物外貌：", "人物外貌:", "外貌：", "外貌:", "外形：", "外形:")))
    body_text = _section_text(premise, ("身材：", "身材:", "体型：", "体型:"))
    if body_text:
        appearance_text = "\n".join(part for part in (appearance_text, body_text)
                                    if part)
    role_entries = _split_character_entries(role_text)
    clothing_entries = _split_character_entries(clothing_text)
    appearance_entries = _split_character_entries(appearance_text)
    if "" in role_entries:
        named = [label for label in list(clothing_entries) + list(appearance_entries)
                 if label]
        if named and named[0] not in role_entries:
            role_entries[named[0]] = role_entries.pop("")
    labels = list(role_entries)
    for entries in (clothing_entries, appearance_entries):
        labels.extend(label for label in entries if label not in labels)
    if not labels:
        labels = [""]
    unlabeled_role = role_entries.get("")
    unlabeled_clothing = clothing_entries.get("")
    unlabeled_appearance = appearance_entries.get("")
    profiles: list[CharacterProfile] = []
    for index, label in enumerate(labels):
        role_value = role_entries.get(label)
        clothing_value = clothing_entries.get(label)
        explicit_appearance = appearance_entries.get(label)
        if index == 0:
            if role_value is None:
                role_value = unlabeled_role
            if clothing_value is None:
                clothing_value = unlabeled_clothing
            if explicit_appearance is None:
                explicit_appearance = unlabeled_appearance
        name = label or ("main" if len(labels) == 1 else "character_%02d" % (index + 1))
        gender = _infer_gender(label, role_value or "", explicit_appearance or "")
        appearance_source = explicit_appearance if explicit_appearance else role_value
        profiles.append(CharacterProfile(
            key="char_%02d" % (index + 1),
            name=name,
            gender=gender,
            appearance=_split_tags(appearance_source or ""),
            initial_clothing=_split_tags(clothing_value),
            appearance_locked=bool(explicit_appearance),
        ))
    return profiles


# --------------------------------------------------------------------------- #
# JSON import (tolerant of many shapes)
# --------------------------------------------------------------------------- #

_JSON_PROMPT_KEYS = (
    "prompt", "prompt_en", "positive", "tags", "text", "caption",
    "description", "content", "英文提示词",
)
_JSON_ID_KEYS = ("id", "shot_id", "shot", "index", "number", "序号")
_JSON_NAME_KEYS = ("name", "title", "slug", "名称")


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        for key in ("text", "prompt", "value", "content", "tags", "caption",
                    "description"):
            text = _json_text(value.get(key))
            if text:
                return text
        return ""
    return str(value).strip()


def _json_field(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _json_text(item.get(key))
        if text:
            return text
    return ""


def _json_shot_number(value: Any, fallback: str) -> str:
    text = _json_text(value)
    if text.isdigit() and len(text) < 3:
        return "%02d" % int(text)
    return text or fallback


def _looks_like_shot(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, dict):
        return False
    return any(key in value for key in _JSON_PROMPT_KEYS)


def _json_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        return [data] if data.strip() else []
    if not isinstance(data, dict):
        return []
    for key in ("shots", "storyboard", "scenes", "frames", "data", "result",
                "output", "items", "分镜"):
        if key in data:
            found = _json_items(data[key])
            if found:
                return found
    if _looks_like_shot(data):
        return [data]
    values = list(data.values())
    if values and all(isinstance(value, (dict, str, list, tuple))
                      for value in values):
        mapped: list[Any] = []
        for key, value in data.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                mapped.append(item)
            elif isinstance(value, (list, tuple)):
                prompt = ", ".join(str(tag).strip() for tag in value
                                   if str(tag).strip())
                if prompt:
                    mapped.append({"id": key, "prompt": prompt})
            elif value.strip():
                mapped.append({"id": key, "prompt": value})
        if mapped:
            return mapped
    for value in values:
        if isinstance(value, (dict, list)):
            found = _json_items(value)
            if found:
                return found
    return []


def shots_from_json(data: Any, fallback_prefix: str = "shot") -> list[dict[str, str]]:
    items = _json_items(data)
    if not items:
        raise ValueError(
            "JSON 里没有找到分镜。支持数组、包含 shots/storyboard/scenes 的对象，"
            "或按镜号映射的对象。")
    shots: list[dict[str, str]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            item = {"prompt": item}
        elif isinstance(item, (list, tuple)):
            item = {"prompt": ", ".join(str(tag).strip() for tag in item
                                        if str(tag).strip())}
        if not isinstance(item, dict):
            continue
        prompt = _json_field(item, _JSON_PROMPT_KEYS)
        if not prompt:
            continue
        number = "%02d" % (index + 1)
        shot_id = _json_shot_number(_json_field(item, _JSON_ID_KEYS), number)
        name = _json_field(item, _JSON_NAME_KEYS) or slugify(
            prompt, "%s_%s" % (fallback_prefix, number))
        description = _json_field(item, ("description", "outline", "script"))
        shot = {
            "id": shot_id,
            "name": name,
            "prompt": prompt,
            "description": description,
        }
        expansions = item.get("ai_expansions")
        if isinstance(expansions, list):
            values = [str(v).strip() for v in expansions if str(v).strip()]
            if values:
                shot["ai_expansions"] = values
        keyframe = _json_field(item, ("keyframe_prompt",))
        if keyframe:
            shot["keyframe_prompt"] = keyframe
        shots.append(shot)
    if not shots:
        raise ValueError("JSON 里没有可用的分镜 prompt。")
    return shots


def premise_from_json(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("premise", "story", "plot", "description", "剧情", "前提"):
        value = _json_text(data.get(key))
        if value:
            return value
    for key in ("data", "result", "storyboard", "output"):
        if isinstance(data.get(key), dict):
            value = premise_from_json(data[key])
            if value:
                return value
    return ""


def finalize_generated_story(shots: list[dict[str, Any]], premise: str,
                             profiles: list[CharacterProfile] | None = None
                             ) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        prompt = normalize_prompt_text(str(shot.get("prompt") or ""))
        if prompt:
            shot["prompt"] = prompt


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

def generate_storyboard(client: Any, premise: str,
                        options: StoryboardOptions,
                        initial_shots: list[dict[str, str]] | None = None,
                        client_override: Any = None,
                        model_override: str = "") -> list[dict[str, str]]:
    initial = [dict(shot) for shot in (initial_shots or [])]
    total = max(len(initial), int(options.shots))
    log = options.log

    if len(initial) >= total:
        result = initial[:total]
        finalize_generated_story(result, premise)
        return result

    messages = build_storyboard_messages(
        premise, total, options.setting,
        strip_appearance=options.strip_appearance)
    num_predict = max(8192, int(options.num_predict or 0), total * 400)
    raw = client.chat_json(
        options.model, messages,
        schema=STORYBOARD_SCHEMA,
        temperature=options.temperature,
        num_predict=min(num_predict, 32768),
        num_ctx=int(options.num_ctx or 32768),
        keep_alive=options.keep_alive,
        timeout=max(options.timeout, 600.0),
        retries=1,
    )
    result = normalize_shots(raw, total)
    if options.on_partial is not None:
        try:
            options.on_partial([dict(shot) for shot in result])
        except Exception as exc:
            log("Checkpoint save failed: %s" % exc)
    finalize_generated_story(result, premise)
    trace_event("storyboard.done", result)
    return result


_TOP_SECTION_RE = re.compile(
    r"^(?:角色设定|角色标签|角色|人物设定|人物|外貌身材|角色外貌|人物外貌|外貌|"
    r"外形|身材|体型|初始服装|初始装扮|服装|大场景|场景|剧情|故事|额外|画风)"
    r"\s*[:：]")
