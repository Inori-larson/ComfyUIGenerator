"""Ollama storyboard generation: premise -> continuous shot list."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.tags import limit_tags, sanitize_prompt_tags

PROMPT_COVERAGE = (
    "覆盖维度：角色身份与外观、服装/裸露状态、当前可见身体部位、姿势、动作、表情、"
    "场景/地点、镜头景别、机位/角度、构图、光线/时间、NSFW 状态。"
)
BOORU_WORKFLOW = (
    "先在心里拆解，不要把拆解过程写进结果：人数/cast、当前服装结果、姿势、动作、表情、"
    "NSFW、场景、光线、镜头。再严格按此顺序组装标签：cast → 服装/裸露 → 姿势 → 动作 → "
    "表情 → NSFW → 场景 → 光线 → 镜头。服装只写该镜当前结果，不写准备脱的过程：已经脱掉的"
    "服装标签必须删除；半脱用 pulled down、at knees、off shoulder、open clothes；全裸用 "
    "completely nude，并按画面加 pussy、nipples、pussy juice；禁止复穿已脱衣物或提前裸露。"
    "标准动作/表情词优先：standing, sitting on bed, sitting on sofa, lying on back, legs spread, "
    "fingering, finger in pussy, masturbation, hand on breast, breast grab, half-closed eyes, "
    "open mouth, looking at viewer, head back, leaning back, trembling。同一固定场景每镜重复"
    "相同环境词；镜头只用 full body、medium shot、close-up、from side 等抽象词。"
    "同义/冲突清理：hairclip 不写 hairpin，flower brooch 不写 brooch，puritan collar 不写 "
    "peter pan collar，frilled black leotard 不写 romper；completely nude 不能与任何服装标签"
    "同时出现；非性行为段不要无故写 nude/pussy/nipples；一镜只保留一个景别和一套姿势状态。"
    "性行为段每镜换姿势和互动：cowgirl、reverse cowgirl、missionary、doggy style、side sex、"
    "leg lift、standing sex、spooning，配合 eye contact、kiss、hand on waist/neck/hair、"
    "breast grab、holding hands，禁止连续重复同一姿势。"
)
SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "script": {"type": "string"},
                    "cast": {"type": "string"},
                },
                "required": ["id", "name", "script", "cast"],
            },
        }
    },
    "required": ["shots"],
}

TAG_SCHEMA: dict[str, Any] = {
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

OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "cast": {"type": "string"},
                    "outline": {"type": "string"},
                },
                "required": ["id", "name", "cast", "outline"],
            },
        }
    },
    "required": ["shots"],
}

OUTLINE_SYSTEM = (
    "你是二次元 NSFW 剧情大纲和分镜编剧。请按用户剧情生成完整编号分镜大纲，只写中文大纲，不写英文标签。\n"
    "成功标准：\n"
    "1. 按用户要求的总格数生成，id 从 01 连续编到最后一格，不能少、重、跳。\n"
    "2. 每条 outline 必须写清本镜独有剧情：谁出现、做了什么、服装/裸露变化、场景、镜头、光线、NSFW 状态；"
    "禁止复制上一镜、禁止只写同一动作、禁止所有镜头重复。\n"
    "3. 固定场景/建筑/时间/光线必须全程连续，只有剧情明确移动才换地点。\n"
    "4. 初始服装是唯一初始服装，必须原样使用；禁止把它替换成未列出的连衣裙、蕾丝裙或其他服装。"
    "服装只能按初始服装单项递进，禁止复穿已脱衣物，禁止跳步；脱衣必须写清具体脱的是哪件初始服装。"
    "禁止发明 romper、peter pan collar、ruffled romper 等未列出的服装；每条只写该镜最终可见状态，"
    "不写大段准备动作。\n"
    "5. cast 必须写人物数量与性别：单人 1girl solo；女主+我 1girl 1boy；没有出现的角色不得写。\n"
    "6. 按起承转合推进，不能从开头几镜后开始循环。\n"
    "只输出 JSON shots[{id,name,cast,outline}]，不要解释，不要英文标签。"
)

SCRIPT_SYSTEM = (
    "你是二次元 NSFW 剧情大纲和分镜编剧。先只生成中文分镜脚本，不写英文标签。\n"
    "成功标准（必须全部满足，否则视为失败）：\n"
    "1. 固定场景：剧情指定的地点、家具、时间、光线全部格子不得更换；每镜 script 重复写同一场景关键词。\n"
    "2. 服装只能从初始服装标签单向递进：禁止发明未列出的连衣裙/蕾丝裙/其他服装；"
    "禁止复穿已脱衣物，禁止跳步；写清当前还穿着什么、已脱哪件初始服装。"
    "禁止发明 romper、peter pan collar、ruffled romper 等未列出的服装；"
    "每镜只写当前最终状态，不写“准备脱/正在脱”的过程；半脱写清拉到哪里。\n"
    "3. 每镜 script 必须覆盖：角色/cast、服装/裸露状态、可见身体部位、姿势动作、表情、"
    "地点、景别、机位/角度、构图、光线时间、NSFW 状态。\n"
    "4. 因果连续：下一镜必须能从上镜动作自然接上，禁止无故重启动作或换场景。\n"
    "5. 如果剧情有固定场景锁/角色锁/视角角色（如“我”、1boy），必须遵守。\n"
    "6. 每镜 cast 必须写清人物数量与性别：单人用 1girl solo；女主+我同框用 1girl 1boy；"
    "没有出现的角色不得写进 cast。\n"
    "7. 每镜 script 本身就是该镜的剧情描述，必须写清谁做了什么、发生了什么变化；"
    "禁止复制上一镜、禁止只写身份或服装清单、禁止所有镜头重复同一句。\n"
    "8. 一次生成用户要求的全部镜头，不得只写开头几镜，不得从中间开始循环；"
    "id 必须从 01 连续编到总格数，不能重复、跳号。\n"
    "9. 每镜 script 按模板组织：角色/cast：…；服装：…；可见部位：…；姿势动作：…；"
    "表情：…；场景：…；镜头：…；构图：…；光线时间：…；NSFW：…。\n"
    "只输出 schema JSON：shots[{id,name,script,cast}]，不要解释，不要英文标签。"
)

TAG_SYSTEM = (
    "你是专业的二次元 NSFW Danbooru 提示词工程师。把给定的中文分镜 script 逐镜转换成英文 Booru prompt。\n"
    "成功标准（必须全部满足）：\n"
    "1. 只输出 schema JSON：shots[{id,prompt}]，不要解释、不要 markdown、不要中文。\n"
    "2. " + BOORU_WORKFLOW + "\n"
    "3. 保留 script 的全部剧情：服装/裸露、可见身体部位、姿势动作、表情、NSFW、场景、光线、镜头；"
    "不要漏固定场景词，不要只写身份或服装清单。\n"
    "4. 必须按 script 的 cast 写清人数与性别：单人 1girl, solo；女主+我 1girl, 1boy；"
    "禁止出现 cast 之外的 second person、people、multiple boys、multiple girls。"
    "角色身份只写 cast，不写发色、瞳色、发型、脸或身体特征。\n"
    "5. 每个标签尽量短，用标准 Danbooru 词，不写整句英文；动作拆成 sitting on bed、"
    "pulling clothes、looking at viewer 这类标签。\n"
    "6. 每条 prompt 建议 25-45 个标签，复杂场景 50-70，最多 100；英文逗号分隔、去重，不要为凑数堆标签。\n"
    "7. 镜头只用 full body、upper body、close-up、medium shot、wide shot、from above/below/side、"
    "dutch angle、POV、depth of field 等抽象词；禁止 camera、holding camera、lens、tripod、photographer。\n"
    "8. 看向镜头写 looking at viewer，不写 looking at camera。本阶段不接收任何角色标签。\n"
    "9. 不生成质量/画质标签（masterpiece, best quality, absurdres、ultra-detailed、highres、sharp focus 等），"
    "不生成风格标签（anime style、flat color、cel shading、official art 等）。\n"
    "内容示例（只学组织顺序，不要照抄）：坐在床边，双腿分开，手指插入，半闭眼，卧室台灯，夜晚。"
    "→ 1girl, solo, completely nude, pussy, sitting on bed, legs spread, fingering, finger in pussy, "
    "half-closed eyes, bedroom, bed, lamp, night, soft lighting, medium shot。"
)

def clean_prompt(text: Any) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"^\s*(prompt|tags|positive|提示词|标签|正向)\s*[:：]\s*", "", value, flags=re.I)
    return sanitize_prompt_tags(value).strip(",;.")


_TAG_ALIASES = {
    "closeup": "close-up",
    "close up": "close-up",
    "soft light": "soft lighting",
    "side view": "from side",
    "side profile": "from side",
    "back view": "from behind",
    "high angle": "from above",
    "low angle": "from below",
    "holding hands": "hand hold",
    "hairpin": "hairclip",
    "brooch": "flower brooch",
    "doggystyle": "doggy style",
    "tv": "television",
    "peter pan collar": "puritan collar",
    "black romper": "frilled black leotard",
    "ruffled romper": "frilled black leotard",
    "black ruffled romper": "frilled black leotard",
    "frilled romper": "frilled black leotard",
    "romper": "frilled black leotard",
}
_SHOT_SIZE_TAGS = {
    "full body", "upper body", "close-up", "medium shot", "wide shot",
    "portrait",
}
_EXPOSURE_TAGS = {
    "completely nude", "full nude", "nude", "naked", "topless",
    "bottomless", "pussy", "nipples", "breasts out",
}


def _resolve_state_tags(tags: list[str]) -> list[str]:
    lows = {tag.lower() for tag in tags}
    clothing = {tag for tag in tags if _clothing_key(tag)}
    exposure = lows & _EXPOSURE_TAGS
    if clothing and "completely nude" in lows:
        tags = [tag for tag in tags if tag.lower() != "completely nude"]
        lows.discard("completely nude")
    if "fully clothed" in lows and exposure:
        tags = [tag for tag in tags if tag.lower() != "fully clothed"]
        lows.discard("fully clothed")
    if "clothed" in lows and exposure:
        tags = [tag for tag in tags if tag.lower() != "clothed"]
    return tags


def normalize_prompt_tags(prompt: str) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    shot_size = ""
    for token in str(prompt or "").split(","):
        tag = token.strip()
        if not tag:
            continue
        key = re.sub(r"[_\-\s]+", " ", tag.lower()).strip()
        canonical = _TAG_ALIASES.get(key, tag)
        ckey = re.sub(r"[_\-\s]+", " ", canonical.lower()).strip()
        if ckey in seen:
            continue
        if ckey in _SHOT_SIZE_TAGS:
            if shot_size:
                continue
            shot_size = ckey
        seen.add(ckey)
        tags.append(canonical)
    tags = _resolve_state_tags(tags)
    return limit_tags(clean_prompt(", ".join(tags)))


_IDENTITY_WORDS = re.compile(r"\b(?:hair|haired|eyes|eyed)\b", re.I)
_IDENTITY_ACCESSORIES = {
    "hairclip", "hairband", "hair band", "hairpin", "hair pin",
    "hair ribbon", "hair flower", "hair stick", "hair bow",
}
_GUESSED_IDENTITY = {
    "glasses", "eyepatch", "mole", "scar", "tattoo", "horns", "horn",
    "animal ears", "cat ears", "fox ears", "rabbit ears", "tail", "fang",
    "fangs", "heterochromia", "ponytail", "twintails", "braid", "bangs",
    "sidelocks", "ahoge", "choker", "earrings", "necklace", "bracelet",
    "asian", "caucasian", "latina", "dark skin", "white skin", "fair skin",
    "pale skin", "tan", "tanlines", "freckles", "body freckles", "mole under eye",
    "muscular", "muscular female", "abs", "toned", "curvy", "voluptuous",
    "petite", "slim", "wide hips", "narrow waist", "thick thighs",
    "flat chest", "large breasts", "huge breasts", "big breasts",
    "medium breasts", "small breasts", "people", "fancy character",
    "asuka yixuan",
}
_BODY_IDENTITY_PATTERN = re.compile(
    r"\b(?:large|huge|big|medium|small|flat|slim|thick|wide|narrow|curvy|"
    r"voluptuous|muscular|toned|petite|tall|short)\s+"
    r"(?:breasts?|chest|hips?|waist|thighs?|ass|body|figure)\b", re.I)
_CAST_TAGS = {
    "1girl", "1boy", "solo", "2girls", "2boys", "multiple girls",
    "multiple boys", "people", "fancy character", "group",
}
_QUALITY_STYLE_TAGS = {
    "masterpiece", "best quality", "amazing quality", "absurdres",
    "ultra-detailed", "extremely detailed", "highres", "sharp focus",
    "anime style", "official art", "flat color", "cel shading",
}
_IDENTITY_REFERENCE_WORDS = re.compile(
    r"\b(?:hair|haired|eyes?|eyed|skin|face|mole|scar|tattoo|horn|horns|"
    r"ears?|tail|fang|fangs|glasses|eyepatch|brooch|earrings?|necklace|"
    r"choker|hairclip|hairband|hairpin)\b", re.I)


def _is_identity_output_tag(tag: str) -> bool:
    low = str(tag or "").lower().strip()
    if low in {"1girl", "1boy", "yixuan", "solo"}:
        return True
    if (_clothing_key(low) or low in _SCENE_REMOVE
            or low in _QUALITY_STYLE_TAGS):
        return False
    return bool(_IDENTITY_REFERENCE_WORDS.search(low))


def strip_stage1_identity(prompt: str, allowed_text: str = "") -> str:
    """Remove model-guessed hair/eye/identity tags from the plot-only pass."""
    allowed = str(allowed_text or "").lower()
    tags: list[str] = []
    for token in str(prompt or "").split(","):
        tag = token.strip()
        low = tag.lower()
        invented_name = (low.startswith(("cyberpunk", "instrument"))
                         or bool(re.match(r"^yixuan\s+", low))
                         or low in {"none", "null"})
        guessed_identity = (
            bool(_IDENTITY_WORDS.search(low)) and low not in _IDENTITY_ACCESSORIES
        ) or low in _GUESSED_IDENTITY or bool(_BODY_IDENTITY_PATTERN.search(low))
        if (guessed_identity and low not in allowed) or (invented_name and low not in allowed):
            continue
        if tag:
            tags.append(tag)
    return limit_tags(clean_prompt(", ".join(tags)))


def strip_generation_quality(prompt: str) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",")
            if tag.strip() and tag.strip().lower() not in _QUALITY_STYLE_TAGS]
    return limit_tags(clean_prompt(", ".join(tags)))


def detect_cast(source: str, cast_hint: str = "", premise: str = "") -> list[str]:
    context = "\n".join((str(cast_hint or ""), str(source or "")))
    if not context.strip():
        context = str(premise or "")
    female = bool(re.search(r"\b1girl\b|仪玄|她|女性|女人|女孩|girl|female",
                            context, re.I)) or bool(
        re.search(r"仪玄|她|女性|女人|女孩", premise, re.I))
    male = bool(re.search(r"\b1boy\b|我|男性|男人|男孩|boy|male|他|男友|丈夫",
                          context, re.I))
    if not female and not male:
        return []
    if female and male:
        return ["1girl", "1boy"]
    if female:
        return ["2girls"] if re.search(r"\b2girls\b|两个女|双女", context, re.I) else [
            "1girl", "solo"]
    return ["1boy", "solo"]


def apply_cast_state(prompt: str, source: str, cast_hint: str = "",
                     premise: str = "") -> str:
    cast = detect_cast(source, cast_hint, premise)
    if not cast:
        return prompt
    tags = [tag.strip() for tag in str(prompt or "").split(",")
            if tag.strip() and tag.strip().lower() not in _CAST_TAGS]
    return limit_tags(clean_prompt(", ".join(cast + tags)))


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
        parts = [str(item.get(key) or "").strip() for key in (
            "clothing", "body", "pose", "expression", "scene", "camera", "lighting")]
        parts.append(str(item.get("prompt") or item.get("tags")
                         or item.get("description") or "").strip())
        prompt = clean_prompt(", ".join(part for part in parts if part))
        if not prompt:
            continue
        base = slugify(item.get("name") or "%s_%02d" % (fallback_prefix, index + 1),
                       "shot_%02d" % (index + 1))
        name, counter = base, 2
        while name.lower() in used:
            name = "%s_%d" % (base, counter)
            counter += 1
        used.add(name.lower())
        shots.append({
            "id": "%02d" % (start + len(shots)), "name": name,
            "prompt": limit_tags(prompt),
            "script": str(item.get("script") or "").strip(),
            "outline": str(item.get("brief") or item.get("outline") or "").strip(),
            "clothing": str(item.get("clothing") or "").strip(),
            "scene": str(item.get("scene") or "").strip(),
            "pose": str(item.get("pose") or "").strip(),
            "camera": str(item.get("camera") or "").strip(),
        })
    if not shots:
        raise ValueError("Model returned no usable shots.")
    return shots


@dataclass
class StoryboardOptions:
    model: str
    shots: int = 6
    chunk: int = 12
    temperature: float = 0.6
    num_predict: int = 0
    num_ctx: int = 0
    timeout: float = 240.0
    keep_alive: str = "5m"
    setting: str = ""
    character_tags: str = ""
    style_positive: str = ""
    strip_appearance: bool = False
    log: Callable[[str], None] = field(default=lambda _msg: None)


_JSON_PROMPT_KEYS = (
    "prompt", "prompt_en", "positive", "tags", "text", "caption",
    "description", "content", "英文提示词",
)
_JSON_PROMPT_ZH_KEYS = ("prompt_zh", "zh", "chinese", "中文", "中文提示词")
_JSON_OUTLINE_KEYS = ("outline", "brief", "summary", "大纲", "中文大纲")
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
    """Import any reasonable storyboard JSON shape and normalize every shot."""
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
        prompt_zh = _json_field(item, _JSON_PROMPT_ZH_KEYS) or prompt
        outline = _json_field(item, _JSON_OUTLINE_KEYS)
        shot = {
            "id": shot_id,
            "name": name,
            "prompt": prompt,
            "prompt_zh": prompt_zh,
            "outline": outline,
        }
        for key, aliases in (
                ("cast", ("cast", "characters", "人数")),
                ("script", ("script", "分镜脚本")),
                ("phase", ("phase", "阶段"))):
            value = _json_field(item, aliases)
            if value:
                shot[key] = value
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


def extract_premise_beats(premise: str) -> list[str]:
    """Parse numbered plot lines (01. ...) into hard per-shot beats."""
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


def _premise_plot_text(premise: str) -> str:
    lines: list[str] = []
    collecting = False
    for raw in str(premise or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^剧情\s*[:：]", line):
            collecting = True
            rest = re.sub(r"^剧情\s*[:：]\s*", "", line)
            if rest:
                lines.append(rest)
            continue
        if collecting and re.match(
                r"^(?:角色|初始服装|大场景|其它|其他|场景|风格)\s*[:：]", line):
            break
        if collecting:
            lines.append(line)
    return "\n".join(lines).strip()


def _split_story_clauses(premise: str) -> list[str]:
    plot = _premise_plot_text(premise) or str(premise or "")
    parts = [part.strip(" ，,。；;") for part in
             re.split(r"[，,。；;！!？?\n]+", plot)]
    parts = [part for part in parts if part]
    if len(parts) > 8:
        size = (len(parts) + 7) // 8
        parts = ["，".join(parts[index:index + size])
                 for index in range(0, len(parts), size)]
    return parts or ([plot] if plot.strip() else [])


def _story_phase(text: str) -> str:
    if re.search(r"做爱|性交|抽插|插入|交合|内射|sex|vaginal|penetrat", text, re.I):
        return "sex"
    if re.search(r"发现|看到|撞见|走进|出现|进门|被我", text):
        return "discovery"
    if re.search(r"勾引|诱惑|挑逗|主动|靠近|亲吻|抚摸对方", text):
        return "seduction"
    if re.search(r"自慰|手淫|抚摸自己|脱衣|解开|褪下", text):
        return "solo"
    if re.search(r"事后|之后|抱|依偎|睡|余韵", text):
        return "afterglow"
    return "story"


def build_story_spine(premise: str, shots: int) -> list[dict[str, Any]]:
    clauses = _split_story_clauses(premise)
    if not clauses:
        return []
    if len(clauses) > shots:
        size = (len(clauses) + shots - 1) // shots
        clauses = ["，".join(clauses[index:index + size])
                   for index in range(0, len(clauses), size)]
    female = bool(re.search(r"仪玄|她|女性|女人|女孩|1girl|girl", premise, re.I))
    cast = "1girl solo" if female else ""
    spine: list[dict[str, Any]] = []
    for clause in clauses:
        phase = _story_phase(clause)
        male = bool(re.search(r"我|1boy|男孩|男人|男性|男友|丈夫", clause))
        if male:
            cast = "1girl 1boy" if female else "1boy solo"
        if phase == "sex" and female:
            cast = "1girl 1boy" if re.search(r"我|1boy|男孩|男人|男性", clause + premise) else cast
        spine.append({"summary": clause, "cast": cast, "phase": phase})

    weights = []
    for item in spine:
        phase = item["phase"]
        weights.append({
            "story": 0.40, "solo": 0.55, "discovery": 0.75,
            "seduction": 1.00, "sex": 3.50, "afterglow": 0.60,
        }.get(phase, 0.8))
    base = [1] * len(spine)
    remaining = max(0, shots - len(spine))
    total = sum(weights) or 1.0
    raw = [remaining * weight / total for weight in weights]
    counts = [int(value) for value in raw]
    for index in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True):
        if sum(counts) >= remaining:
            break
        counts[index] += 1
    counts = [base[index] + counts[index] for index in range(len(spine))]
    while sum(counts) > shots:
        index = max(range(len(counts)), key=lambda i: counts[i])
        if counts[index] <= 1:
            break
        counts[index] -= 1
    while sum(counts) < shots:
        counts[-1] += 1

    current = 1
    for index, (item, count) in enumerate(zip(spine, counts), 1):
        item["id"] = "%02d" % index
        item["start"] = current
        item["end"] = current + count - 1
        current += count
    return spine


_STATE_CLOTHING = (
    "clothes", "clothing", "outfit", "costume", "uniform", "dress", "gown",
    "kimono", "yukata", "qipao", "cheongsam", "robe", "cloak", "cape",
    "apron", "nightgown", "lingerie", "leotard", "bodysuit", "swimsuit",
    "bikini", "armor", "suit", "blazer", "jacket", "coat", "cardigan",
    "shirt", "blouse", "t-shirt", "sweater", "hoodie", "tank top", "vest",
    "camisole", "crop top", "top", "bra", "bikini top", "skirt", "pants",
    "trousers", "jeans", "shorts", "panties", "underwear", "thong",
    "pantyhose", "legwear", "stockings", "tights", "thighhigh", "leggings", "socks",
    "heels", "shoes", "boots", "sandals", "slippers", "footwear",
    "gloves", "hat", "scarf", "necktie", "belt", "strap", "apron",
    "veil", "mask", "corset", "bustier", "garter", "maid", "nurse",
    "bunny", "cheerleader", "hanfu", "sailor", "gym", "school",
    "wedding", "sports",
)
_STATE_EXPOSURE = (
    "nude", "naked", "topless", "bottomless", "pussy", "anus", "nipples",
    "areola", "areolae", "bare breasts", "breasts out", "completely nude",
    "full nude", "exposed", "undressed",
)
_FULL_NUDE_REMOVE = _STATE_CLOTHING
_EUPHEMISMS = {
    "girl completely nude": "completely nude",
    "completely nude girl": "completely nude",
    "girl fully nude": "completely nude",
    "hand on private parts": "hand on pussy",
    "hand on private area": "hand on pussy",
    "hand on crotch": "hand on pussy",
    "private parts": "pussy",
    "private area": "pussy",
    "crotch": "pussy",
    "down there": "pussy",
    "finger in vagina": "finger in pussy",
    "finger inside pussy": "fingering, finger in pussy",
    "middle finger inserted": "fingering, finger in pussy",
    "quick hand movements": "masturbation",
    "hand movements": "masturbation",
    "love liquid": "pussy juice",
    "body fluid": "pussy juice",
    "vagina": "pussy",
    "vulva": "pussy",
    "bare breasts": "topless",
    "breasts out": "topless",
    "nude upper body": "topless",
    "upper body naked": "topless",
    "full upper body nude": "topless",
    "upper body covered": "",
    "intense expression": "aroused expression",
    "expression of desire": "aroused expression",
    "expression of pleasure": "pleasure",
}
_CLOTHING_KEYS = (
    ("pantyhose", (r"pantyhose", r"黑丝", r"丝袜", r"连裤袜")),
    ("legwear", (r"legwear", r"腿部装饰", r"腿饰", r"袜圈")),
    ("stockings", (r"stockings", r"长筒袜", r"大腿袜")),
    ("thighhigh", (r"thighhigh", r"thigh-high", r"过膝袜")),
    ("leggings", (r"leggings", r"打底裤", r"紧身裤")),
    ("socks", (r"socks", r"袜子")),
    ("panties", (r"panties", r"内裤", r"底裤")),
    ("underwear", (r"underwear", r"内衣")),
    ("thong", (r"thong", r"丁字裤")),
    ("bra", (r"bra", r"胸罩", r"文胸")),
    ("bikini", (r"bikini", r"比基尼")),
    ("swimsuit", (r"swimsuit", r"泳装", r"泳衣")),
    ("blazer", (r"blazer", r"西装")),
    ("jacket", (r"jacket", r"夹克", r"外套")),
    ("coat", (r"coat", r"大衣", r"风衣")),
    ("cardigan", (r"cardigan", r"开衫")),
    ("shirt", (r"shirt", r"衬衫", r"上衣")),
    ("vest", (r"vest", r"马甲", r"背心")),
    ("blouse", (r"blouse", r"女衬衫")),
    ("sweater", (r"sweater", r"毛衣", r"针织衫")),
    ("hoodie", (r"hoodie", r"卫衣")),
    ("tank top", (r"tank top", r"背心")),
    ("camisole", (r"camisole", r"吊带")),
    ("crop top", (r"crop top", r"露脐装")),
    ("top", (r"tight top", r"紧身上衣", r"上衣")),
    ("lingerie", (r"lingerie", r"蕾丝内衣", r"性感内衣")),
    ("leotard", (r"leotard", r"连体衣", r"紧身衣")),
    ("bodysuit", (r"bodysuit", r"连身衣")),
    ("apron", (r"apron", r"围裙")),
    ("veil", (r"veil", r"面纱", r"头纱")),
    ("mask", (r"mask", r"口罩", r"面罩")),
    ("corset", (r"corset", r"束腰")),
    ("bustier", (r"bustier", r"抹胸")),
    ("garter", (r"garter", r"吊袜带")),
    ("maid", (r"maid", r"女仆")),
    ("nurse", (r"nurse", r"护士")),
    ("bunny", (r"bunny", r"兔女郎")),
    ("cheerleader", (r"cheerleader", r"啦啦队")),
    ("hanfu", (r"hanfu", r"汉服")),
    ("sailor", (r"sailor", r"水手服")),
    ("gym", (r"gym", r"运动服")),
    ("school", (r"school", r"校服")),
    ("wedding", (r"wedding", r"婚纱")),
    ("sports", (r"sports", r"运动装")),
    ("dress", (r"dress", r"连衣裙", r"长裙")),
    ("kimono", (r"kimono", r"和服")),
    ("yukata", (r"yukata", r"浴衣")),
    ("qipao", (r"qipao", r"cheongsam", r"旗袍")),
    ("robe", (r"robe", r"长袍")),
    ("uniform", (r"uniform", r"制服", r"校服")),
    ("suit", (r"\bsuit\b", r"套装", r"西服")),
    ("armor", (r"armor", r"盔甲", r"铠甲")),
    ("skirt", (r"skirt", r"裙子", r"短裙")),
    ("pants", (r"pants", r"trousers", r"裤子", r"长裤")),
    ("jeans", (r"jeans", r"牛仔裤")),
    ("shorts", (r"shorts", r"短裤")),
    ("heels", (r"heels", r"高跟鞋")),
    ("boots", (r"boots", r"靴子")),
    ("shoes", (r"shoes", r"鞋")),
    ("sandals", (r"sandals", r"凉鞋")),
    ("slippers", (r"slippers", r"拖鞋")),
    ("gloves", (r"gloves?", r"手套")),
    ("hat", (r"hat", r"帽子")),
    ("scarf", (r"scarf", r"围巾")),
    ("necktie", (r"necktie", r"领带")),
    ("belt", (r"belt", r"腰带")),
)
_SCENE_TAGS = {
    "bedroom": ["bedroom", "bed", "indoors", "double bed", "bedside table",
                "nightstand lamp", "half-open curtains", "window"],
    "living": ["living room", "sofa", "indoors"],
    "room": ["room", "indoors"],
    "bathroom": ["bathroom", "bathtub", "shower", "indoors"],
    "kitchen": ["kitchen", "counter", "indoors"],
    "office": ["office", "desk", "chair", "indoors"],
    "classroom": ["classroom", "desk", "blackboard", "indoors"],
    "hotel": ["hotel", "hotel room", "bed", "indoors"],
    "gym": ["gym", "locker room", "indoors"],
    "onsen": ["onsen", "hot spring", "bath", "outdoors"],
    "shrine": ["shrine", "torii", "outdoors"],
    "dungeon": ["dungeon", "stone wall", "indoors"],
    "stage": ["stage", "spotlight", "indoors"],
    "cafe": ["cafe", "counter", "indoors"],
    "bar": ["bar", "counter", "indoors"],
    "beach": ["beach", "ocean", "sand", "outdoors"],
    "pool": ["pool", "swimming pool", "water", "outdoors"],
    "car": ["car", "vehicle", "indoors"],
    "train": ["train", "train interior", "indoors"],
    "outdoors": ["outdoors", "park", "street", "city", "sky"],
    "roof": ["rooftop", "roof", "outdoors"],
    "alley": ["alley", "backstreet", "outdoors"],
    "hospital": ["hospital", "hospital bed", "iv drip", "indoors"],
    "laboratory": ["laboratory", "lab", "equipment", "indoors"],
    "prison": ["prison", "jail", "cell", "bars", "indoors"],
    "church": ["church", "chapel", "pew", "indoors"],
    "temple": ["temple", "altar", "incense", "indoors"],
    "sauna": ["sauna", "wooden bench", "steam", "indoors"],
    "toilet": ["toilet", "restroom", "bathroom stall", "indoors"],
    "elevator": ["elevator", "lift", "indoors"],
    "stairwell": ["stairwell", "staircase", "stairs", "indoors"],
    "parking": ["parking lot", "garage", "car", "indoors"],
    "warehouse": ["warehouse", "crates", "indoors"],
    "castle": ["castle", "stone hall", "indoors"],
    "cave": ["cave", "stalactite", "outdoors"],
    "tent": ["tent", "camping", "campfire", "outdoors"],
    "festival": ["festival", "lantern", "outdoors"],
    "club": ["nightclub", "club", "neon lights", "indoors"],
    "library": ["library", "bookshelf", "indoors"],
    "meeting": ["meeting room", "conference table", "indoors"],
    "plane": ["airplane", "plane cabin", "seat", "indoors"],
    "boat": ["boat", "yacht", "deck", "outdoors"],
    "forest": ["forest", "trees", "outdoors"],
    "park": ["park", "bench", "trees", "outdoors"],
}
_SCENE_PATTERNS = (
    ("hotel", r"酒店|宾馆|旅馆|hotel"),
    ("hospital", r"医院|病房|病床|诊所|hospital|clinic"),
    ("laboratory", r"实验室|研究所|laboratory|lab\b"),
    ("prison", r"监狱|囚室|监狱|prison|jail"),
    ("church", r"教堂|礼拜堂|church|chapel"),
    ("temple", r"寺庙|寺院|temple"),
    ("sauna", r"桑拿|汗蒸|sauna"),
    ("toilet", r"厕所|卫生间|洗手间|toilet|restroom"),
    ("bathroom", r"浴室|淋浴|浴缸|bathroom|shower|bathtub"),
    ("kitchen", r"厨房|kitchen"),
    ("office", r"办公室|办公桌|office|desk"),
    ("meeting", r"会议室|meeting room|conference"),
    ("classroom", r"教室|课桌|黑板|classroom"),
    ("library", r"图书馆|library"),
    ("gym", r"健身房|更衣室|gym|locker"),
    ("onsen", r"温泉|浴场|onsen|hot spring"),
    ("shrine", r"神社|鸟居|shrine|torii"),
    ("dungeon", r"地下城|地下牢|dungeon"),
    ("stage", r"舞台|聚光灯|stage|spotlight"),
    ("cafe", r"咖啡厅|咖啡馆|cafe"),
    ("bar", r"酒吧|吧台|bar"),
    ("club", r"夜店|俱乐部|nightclub|club"),
    ("beach", r"海滩|沙滩|海边|beach|ocean|sand"),
    ("pool", r"泳池|游泳池|pool"),
    ("car", r"车内|车里|汽车|轿车|car|vehicle"),
    ("train", r"电车|列车|车厢|train"),
    ("plane", r"飞机|机舱|airplane|plane"),
    ("boat", r"船上|游艇|boat|yacht"),
    ("roof", r"天台|屋顶|rooftop|roof"),
    ("alley", r"小巷|后巷|alley|backstreet"),
    ("parking", r"停车场|车库|parking|garage"),
    ("warehouse", r"仓库|warehouse"),
    ("castle", r"城堡|castle"),
    ("cave", r"洞穴|山洞|cave"),
    ("tent", r"帐篷|露营|tent|camping"),
    ("festival", r"祭典|节日|festival"),
    ("forest", r"森林|forest"),
    ("park", r"公园|park"),
    ("elevator", r"电梯|elevator|lift"),
    ("stairwell", r"楼梯|楼道|stairwell|staircase"),
    ("living", r"沙发|sofa|couch|客厅|living room"),
    ("bedroom", r"卧室|床边|床上|床单|床头|双人床|bedroom|bed\b"),
    ("outdoors", r"户外|室外|街道|城市|outdoors|street"),
    ("room", r"房间|室内|room"),
)
_SCENE_REMOVE = {
    "room", "bedroom", "living room", "bed", "sofa", "couch", "indoors",
    "outdoors", "bathroom", "kitchen", "office", "classroom", "hotel",
    "gym", "locker room", "onsen", "shrine", "dungeon", "stage", "cafe",
    "bar", "beach", "ocean", "sand", "pool", "swimming pool", "car",
    "train", "train interior", "rooftop", "roof", "alley", "backstreet",
    "double bed", "bedside table", "nightstand lamp", "half-open curtains",
    "window", "bathtub", "shower", "counter", "desk", "chair", "blackboard",
    "torii", "stone wall", "spotlight", "water", "sky", "white background",
    "simple background", "transparent background", "3d",
}
_SCENE_REMOVE.update(tag for tags in _SCENE_TAGS.values() for tag in tags)
_NSFW_RULES = (
    (r"全裸|裸体|一丝不挂|脱光|光着身子", ("completely nude",)),
    (r"上身.*(裸|裸露)|上身全裸|胸部露出|露出胸部|乳房露出|奶子露出|"
     r"掀开上衣|上衣.*(掀|拉|解)|胸罩.*(拉|解|脱)",
     ("topless", "nipples")),
    (r"下半身.*(裸|露)|下体露出|私处露出|裙子.*(掀|拉)|内裤.*(拉|脱)|"
     r"裤子.*(拉|脱)|下身.*(裸|露)", ("bottomless", "pussy")),
    (r"私处|阴道|阴部|阴户|小穴|小逼|骚逼|鲍鱼|阴蒂|肉缝|下体|胯下",
     ("pussy",)),
    (r"乳头|奶头|揉胸|揉乳|捏乳|舔乳|乳房", ("nipples",)),
    (r"自慰|手淫|手指.*(插|抽|揉|摸)|抽插|扣弄|玩弄自己|摸阴|揉阴",
     ("masturbation", "fingering")),
    (r"中指.*(插|进入)|手指.*(插入|里面)|插入|进进出出",
     ("fingering", "finger in pussy")),
    (r"高潮|绝顶|去了|泄了|痉挛", ("orgasm",)),
    (r"爱液|淫水|蜜汁|体液|潮吹|喷水", ("pussy juice",)),
    (r"白浊|精液|内射|中出|射精|射在", ("cum",)),
    (r"口交|舔.*(肉棒|阴茎|龟头)|深喉", ("oral", "fellatio", "penis")),
    (r"乳交|夹.*肉棒", ("paizuri", "breasts")),
    (r"肛交|肛门|后穴|菊穴", ("anal", "anus")),
    (r"性交|做爱|交合|抽送", ("sex", "vaginal")),
    (r"手交|撸动|套弄", ("handjob", "penis")),
    (r"足交", ("footjob",)),
    (r"捆绑|绑住|束缚|拘束|绳子|手铐|项圈|牵引绳|蒙眼|眼罩",
     ("bondage", "bound", "shibari", "collar", "leash", "blindfold")),
    (r"打屁股|拍打|调教|鞭打", ("spanking", "bdsm")),
    (r"假阳具|振动棒|跳蛋|按摩棒|肛塞|性玩具",
     ("sex toy", "dildo", "vibrator", "butt plug")),
    (r"多人|群交|3P|三人|轮奸", ("group sex", "threesome")),
    (r"百合|女女|两个女人", ("yuri",)),
    (r"扶她|双性", ("futanari",)),
    (r"触手", ("tentacle",)),
    (r"怪物|兽人|魔物", ("monster",)),
    (r"失禁|漏尿|尿", ("urination", "pee")),
    (r"孕妇|怀孕", ("pregnant",)),
    (r"母乳|乳汁|喷奶", ("lactation",)),
    (r"野外露出|公众场合|公共场合|被人看到", ("exhibitionism", "public indecency")),
)


_POSE_RULES = (
    (r"站立|站在|站于|站着|站起|站起身", ("standing",)),
    (r"坐着|坐下|坐在|坐回", ("sitting",)),
    (r"跪|跪下|跪着|跪坐", ("kneeling",)),
    (r"躺|平躺|仰躺|躺在床上|躺下", ("lying",)),
    (r"趴|俯卧|趴在|趴下", ("on stomach",)),
    (r"四肢着地|趴跪|狗爬|俯身跪", ("all fours",)),
    (r"蹲|蹲下|蹲着", ("squatting",)),
    (r"跨坐|骑乘|女上位", ("straddling", "cowgirl")),
    (r"后入|狗爬式|背后位|从背后", ("doggy style", "from behind")),
    (r"正常位|传教士", ("missionary",)),
    (r"侧卧|侧躺|侧身躺", ("lying on side",)),
    (r"双腿分开|张开双腿|M字腿|掰开腿|分开双腿", ("spread legs",)),
    (r"抬腿|腿抬高|双腿抬高|腿举高", ("legs up",)),
    (r"后仰|仰头|头向后|弓背", ("arched back", "head back")),
    (r"前倾|弯腰|俯身|身体前倾", ("leaning forward", "bending over")),
    (r"双手背后|双手被绑|手臂在后|双手反绑", ("arms behind back",)),
    (r"双手叉腰", ("hands on hips",)),
    (r"双臂交叉|抱胸|双手抱胸", ("crossed arms",)),
    (r"看镜头|看着镜头|看向镜头|注视镜头", ("looking at viewer",)),
    (r"闭眼|闭上眼睛", ("closed eyes",)),
    (r"半闭眼|眼睛半闭|半眯眼", ("half-closed eyes",)),
    (r"张嘴|嘴巴微张|开口|微张", ("parted lips",)),
)
_EXPRESSION_RULES = (
    (r"微笑|含笑|笑", ("smile",)),
    (r"坏笑|邪笑|冷笑", ("smirk",)),
    (r"脸红|羞红|红着脸", ("blush",)),
    (r"害羞|羞涩|羞怯", ("shy",)),
    (r"诱惑|妩媚|妖艳|媚惑", ("seductive",)),
    (r"发情|动情|情欲|淫荡", ("aroused", "lustful")),
    (r"呻吟|喘息|娇喘|喘气", ("moaning", "heavy breathing")),
    (r"高潮脸|阿黑颜|翻白眼|失神", ("ahegao", "rolling eyes")),
    (r"吐舌|舌头伸出|伸舌", ("tongue out",)),
    (r"流口水|口水|垂涎", ("drooling", "saliva")),
    (r"满足|餍足|满意", ("satisfied",)),
    (r"迷离|恍惚|失神", ("dazed", "half-closed eyes")),
    (r"哭|眼泪|泪眼", ("tears", "crying")),
    (r"痛苦|难受|疼痛", ("pained",)),
    (r"惊讶|吃惊|震惊", ("surprised",)),
    (r"生气|愤怒|恼怒", ("angry",)),
    (r"平静|冷静|淡然", ("calm",)),
    (r"认真|严肃", ("serious",)),
)
_CAMERA_RULES = (
    (r"全身|全身照|全身像", ("full body",)),
    (r"半身|上半身", ("upper body",)),
    (r"特写|近景|大特写", ("close-up",)),
    (r"中景", ("medium shot",)),
    (r"远景|广角|全景", ("wide shot",)),
    (r"从下往上|仰拍|低角度|低机位", ("from below", "low angle")),
    (r"从上往下|俯拍|高角度|高机位", ("from above", "high angle")),
    (r"侧面|侧视|侧拍", ("from side", "side view")),
    (r"背面|背后|背拍", ("from behind", "back view")),
    (r"正面|正视|正面拍", ("front view",)),
    (r"荷兰角|倾斜构图", ("dutch angle",)),
    (r"第一人称|主观视角|POV", ("pov",)),
    (r"景深|背景虚化|虚化", ("depth of field", "bokeh")),
    (r"鱼眼", ("fisheye",)),
)
_LIGHTING_RULES = (
    (r"柔光|柔和光|柔光箱", ("soft lighting",)),
    (r"暗光|昏暗|低光", ("dim lighting",)),
    (r"暖光|暖色|暖色调", ("warm lighting",)),
    (r"冷光|冷色|冷色调", ("cool lighting",)),
    (r"烛光|蜡烛", ("candlelight",)),
    (r"月光|月色", ("moonlight", "night")),
    (r"阳光|日光|晴朗", ("sunlight", "day")),
    (r"逆光|背光", ("backlighting",)),
    (r"边缘光|轮廓光", ("rim lighting",)),
    (r"霓虹|霓虹灯", ("neon lights",)),
    (r"聚光|聚光灯", ("spotlight",)),
    (r"阴影|明暗对比|强对比", ("shadow", "chiaroscuro")),
    (r"黄昏|日落|傍晚", ("sunset", "dusk")),
    (r"清晨|黎明|早晨", ("dawn", "morning")),
    (r"夜晚|夜间|深夜", ("night",)),
    (r"雨天|下雨|雨中", ("rain",)),
    (r"雪天|下雪|雪中", ("snow",)),
    (r"雾|雾气|大雾", ("fog",)),
)
_BODY_RULES = (
    (r"胸部|乳房|奶子|大胸|巨乳", ("breasts",)),
    (r"乳头|奶头|乳首", ("nipples",)),
    (r"小穴|蜜穴|花穴|肉穴|骚穴|淫穴|阴户|阴部|下体|私处|胯下",
     ("pussy",)),
    (r"阴蒂|肉缝|鲍鱼", ("pussy", "clitoris")),
    (r"后庭|菊花|菊穴|后穴|肛门", ("anus",)),
    (r"臀部|屁股|翘臀|美臀", ("ass",)),
    (r"大腿|大腿根|股间", ("thighs",)),
    (r"脚|足|脚趾|足底", ("feet", "toes")),
    (r"手|手指|指尖", ("hands", "fingers")),
    (r"腹部|肚子|肚脐", ("stomach", "navel")),
    (r"锁骨", ("collarbone",)),
    (r"腋下|腋窝", ("armpits",)),
    (r"舌头|舌", ("tongue",)),
    (r"唾液|口水", ("saliva",)),
    (r"汗水|汗", ("sweat",)),
    (r"泪水|眼泪", ("tears",)),
    (r"肉棒|阴茎|阳具|龟头", ("penis",)),
    (r"精液|白浊", ("cum",)),
)
_BEAT_RULES = _NSFW_RULES + _POSE_RULES + _EXPRESSION_RULES + _CAMERA_RULES + \
    _LIGHTING_RULES + _BODY_RULES


def _nsfw_tags_for_beat(beat: str) -> set[str]:
    result: set[str] = set()
    for pattern, values in _NSFW_RULES:
        if re.search(pattern, beat, re.I):
            result.update(values)
    return result


def _has_tag_word(text: str, words: tuple[str, ...]) -> bool:
    blob = " " + str(text or "").lower().replace("_", " ").replace("-", " ") + " "
    return any(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", blob)
               for word in words)


def summarize_clothing(shot: dict[str, Any]) -> str:
    """Compact state handoff so the next chunk cannot re-dress the character."""
    source = str(shot.get("clothing") or shot.get("prompt") or "")
    tags = [tag.strip() for tag in source.split(",") if tag.strip()]
    wearing = [tag for tag in tags if _has_tag_word(tag, _STATE_CLOTHING)]
    exposed = [tag for tag in tags if _has_tag_word(tag, _STATE_EXPOSURE)]
    parts: list[str] = []
    if wearing:
        parts.append("wearing: " + ", ".join(dict.fromkeys(wearing)))
    if exposed:
        parts.append("exposed: " + ", ".join(dict.fromkeys(exposed)))
    if not parts:
        parts.append("no explicit clothing/exposure state")
    return "; ".join(parts)


def summarize_shot_state(shot: dict[str, Any]) -> str:
    """State handoff for clothing, pose, camera and the previous action."""
    parts = [summarize_clothing(shot)]
    for key in ("scene", "pose", "camera"):
        value = str(shot.get(key) or "").strip()
        if value:
            parts.append("%s: %s" % (key, value))
    brief = str(shot.get("outline") or "").strip()
    if brief:
        parts.append("last scene: " + brief[:120])
    return "; ".join(part for part in parts if part)


def _initial_clothing_tags(premise: str) -> list[str]:
    for line in str(premise or "").splitlines():
        if "初始服装" not in line:
            continue
        parts = re.split(r"[:：]", line, maxsplit=1)
        raw = parts[1] if len(parts) == 2 else line
        return [tag.strip() for tag in re.split(r"[,，、]", raw) if tag.strip()]
    return []


def _clothing_key(tag: str) -> str:
    low = str(tag).lower()
    for key, patterns in _CLOTHING_KEYS:
        if any(re.search(pattern, low, re.I) for pattern in patterns):
            return key
    return ""


def _is_full_nude(beat: str) -> bool:
    return bool(re.search(
        r"全裸|裸体|一丝不挂|脱光|光着身子|completely nude|full nude|fully nude|naked",
        beat, re.I)) and not bool(
        re.search(r"上身.*(全裸|裸体|脱光)", beat))


def _removes_item(beat: str, key: str) -> bool:
    aliases = dict(_CLOTHING_KEYS).get(key, ())
    if not aliases:
        return False
    item = "(?:" + "|".join(aliases) + ")"
    remove = (r"(?:脱掉|脱去|脱下|褪下|褪去|解除|摘下|取下|"
              r"完全脱下|完全褪到|全部脱去|全部脱下)")
    return bool(re.search(
        r"(?:%s).{0,24}%s|%s.{0,24}(?:%s)" % (remove, item, item, remove),
        beat, re.I))


def clothing_states_for_beats(premise: str, beats: list[str]) -> list[set[str]]:
    initial = _initial_clothing_tags(premise)
    if not initial or not beats:
        return []
    known = {}
    for key, _patterns in _CLOTHING_KEYS:
        for tag in initial:
            if _clothing_key(tag) == key:
                known[key] = tag
                break
    accessories = {tag for tag in initial if not _clothing_key(tag)}
    worn = set(initial)
    removed: set[str] = set()
    states: list[set[str]] = []
    for beat in beats:
        only = re.search(r"(?:只剩|只穿)(.*)", beat)
        if _is_full_nude(beat):
            worn = set(accessories)
            removed.update(known.values())
        elif only:
            chosen = set(accessories)
            only_text = only.group(1)
            for key, patterns in _CLOTHING_KEYS:
                tag = known.get(key)
                if (tag and tag not in removed
                        and any(re.search(p, only_text, re.I) for p in patterns)):
                    chosen.add(tag)
            if chosen != accessories:
                for tag in list(worn):
                    if _clothing_key(tag) and tag not in chosen:
                        removed.add(tag)
                worn = chosen
        else:
            one_side = bool(re.search(r"一边|单边|一只|另一只|另一脚|半脱", beat))
            for key, tag in known.items():
                if _removes_item(beat, key):
                    if one_side and key in ("pantyhose", "heels"):
                        continue
                    worn.discard(tag)
                    removed.add(tag)
        states.append(set(worn))
    return states


def _scene_for_beat(beat: str) -> list[str] | None:
    for key, pattern in _SCENE_PATTERNS:
        if re.search(pattern, beat, re.I):
            return list(_SCENE_TAGS[key])
    return None


def scene_states_for_beats(beats: list[str]) -> list[list[str]]:
    current = list(_SCENE_TAGS["room"])
    states: list[list[str]] = []
    for beat in beats:
        found = _scene_for_beat(beat)
        if found:
            current = found
        states.append(list(current))
    return states


def _item_action(beat: str, key: str) -> bool:
    aliases = dict(_CLOTHING_KEYS).get(key, ())
    if not aliases:
        return False
    item = "(?:" + "|".join(aliases) + ")"
    actions = r"褪|脱|拉|勾住|往下|解开|掀|推|滑|扯|摘|取"
    if re.search(r"%s.{0,10}(?:还在|仍穿|仍然|保留)" % item, beat, re.I):
        return False
    if re.search(r"(?:只剩|只穿).{0,24}%s" % item, beat, re.I):
        return False
    return bool(re.search(
        r"(?:%s).{0,24}(?:%s)|(?:%s).{0,24}(?:%s)" %
        (actions, item, item, actions), beat, re.I))


def _has_removal_action(beat: str) -> bool:
    items = "|".join(alias for _key, aliases in _CLOTHING_KEYS
                     for alias in aliases)
    actions = r"褪|脱|拉|勾住|往下|解开|掀|推|滑|扯|摘|取"
    return bool(re.search(
        r"(?:%s).{0,24}(?:%s)|(?:%s).{0,24}(?:%s)" %
        (actions, items, items, actions), beat, re.I))


def apply_story_state(prompt: str, beat: str, worn: set[str],
                      scene: list[str]) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    tags = [tag for tag in tags if not _clothing_key(tag)]
    tags = [tag for tag in tags if tag.lower() not in _SCENE_REMOVE]
    tags = [tag for tag in tags if tag.lower() not in {
        "upper body covered", "upper body naked",
    }]
    covered_lower = bool(re.search(r"盖住下半身|用被子|盖住", beat))
    full_nude = (not any(_clothing_key(tag) for tag in worn)
                 and not covered_lower)
    removal = _has_removal_action(beat)
    beat_tags = _nsfw_tags_for_beat(beat)
    has_pussy = not covered_lower and (full_nude or "pussy" in beat_tags)
    has_nipples = full_nude or "nipples" in beat_tags
    has_topless = "topless" in beat_tags
    if not removal or full_nude:
        tags = [tag for tag in tags if tag.lower() not in {
            "undressing", "clothes pull", "pantyhose pull"}]
    if not has_pussy:
        tags = [tag for tag in tags if tag.lower() != "pussy"]
    if not has_nipples:
        tags = [tag for tag in tags if tag.lower() != "nipples"]
    if re.search(r"靠在床头|坐起|坐起来", beat):
        tags = [tag for tag in tags if tag.lower() not in {
            "lying", "lying down", "lying on side", "legs spread"}]
        tags.append("sitting")
    if not full_nude:
        tags = [tag for tag in tags if tag.lower() not in {
            "completely nude", "nude", "naked", "bottomless"}]
    if full_nude:
        tags = [tag for tag in tags if tag.lower() not in {"topless"}]
        tags.append("completely nude")
    elif has_topless or has_nipples or not any(
            _clothing_key(tag) in ("blazer", "leotard") for tag in worn):
        tags.append("topless")
    if has_pussy:
        tags.append("pussy")
    if has_nipples:
        tags.append("nipples")
    tags.extend(scene)
    identity = [tag for tag in tags if _is_identity_output_tag(tag)]
    rest = [tag for tag in tags if not _is_identity_output_tag(tag)]
    return limit_tags(clean_prompt(
        ", ".join(identity + sorted(worn) + rest)))


_EXPLICIT_SEX_TAGS = {
    "sex", "vaginal", "penis", "penetration", "missionary", "cowgirl",
    "doggy style", "sex from behind", "cum", "creampie",
}
_SEX_OUTERWEAR = {
    "blazer", "jacket", "coat", "cardigan", "sweater", "hoodie",
    "shirt", "blouse", "vest", "apron", "dress",
}


def apply_phase_terms(prompt: str, phase: str, cast: str = "") -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    seen = {tag.lower() for tag in tags}

    def add(*values: str) -> None:
        for value in values:
            if value and value.lower() not in seen:
                seen.add(value.lower())
                tags.append(value)

    if phase == "sex":
        tags = [tag for tag in tags if tag.lower() not in {
            "undressing", "clothes pull", "pantyhose pull", "hugging",
            "holding hands", "touching cheek", "leaning on shoulder"}]
        tags = [tag for tag in tags
                if _clothing_key(tag) not in _SEX_OUTERWEAR]
        seen = {tag.lower() for tag in tags}
        add("sex", "vaginal", "penetration")
        if "1boy" in cast:
            add("penis")
    else:
        tags = [tag for tag in tags if tag.lower() not in _EXPLICIT_SEX_TAGS]
        seen = {tag.lower() for tag in tags}
        if phase == "seduction":
            add("seductive", "looking at viewer", "leaning forward")
    return limit_tags(clean_prompt(", ".join(tags)))


def normalize_shot_terms(prompt: str) -> str:
    """Replace local-model euphemisms with tags the body LoRAs understand."""
    tags: list[str] = []
    for token in str(prompt or "").split(","):
        tag = token.strip().lower()
        tag = _EUPHEMISMS.get(tag, tag)
        if tag:
            tags.append(tag)
    return limit_tags(clean_prompt(", ".join(tags)))


def enforce_beat_terms(prompt: str, beat: str) -> str:
    """Deterministically add required state/action tags from a Chinese beat."""
    text = normalize_shot_terms(prompt)
    tags = [tag.strip() for tag in text.split(",") if tag.strip()]
    seen = {tag.lower() for tag in tags}

    def add(*values: str) -> None:
        for value in values:
            if value and value.lower() not in seen:
                seen.add(value.lower())
                tags.append(value)

    for pattern, values in _BEAT_RULES:
        if re.search(pattern, beat, re.I):
            add(*values)
    full_nude = _is_full_nude(beat)
    if full_nude:
        tags = [tag for tag in tags if not _has_tag_word(tag, _FULL_NUDE_REMOVE)]
        seen = {tag.lower() for tag in tags}
        add("completely nude", "pussy")
    elif re.search(r"上身.*(裸|裸露)|胸部露出|露出胸部", beat):
        add("topless")
    if re.search(r"私处|阴道|下体|私部", beat):
        add("pussy")
        if re.search(r"抚摸|触碰|摸", beat):
            add("hand on pussy")
    if re.search(r"乳头", beat):
        add("nipples")
    if re.search(r"自慰|抽插|手指.*(插|抚摸)", beat):
        add("masturbation", "fingering")
    if re.search(r"高潮", beat):
        add("orgasm")
    if re.search(r"爱液", beat):
        add("pussy juice")
    if not full_nude:
        for key, _aliases in _CLOTHING_KEYS:
            if not _item_action(beat, key):
                continue
            if key in ("pantyhose", "stockings", "thighhigh", "tights", "leggings"):
                add("pantyhose pull")
            elif key == "skirt":
                add("skirt lift")
            elif key == "dress":
                add("dress lift")
            elif key in ("shirt", "blouse", "sweater", "hoodie", "tank top",
                         "camisole", "crop top"):
                add("shirt lift")
            elif key == "bra":
                add("bra pull")
            elif key == "panties":
                add("panties aside")
            else:
                add("clothes pull")
            add("undressing")
            if key == "pantyhose" and re.search(r"大腿", beat):
                add("thighs")
            if key == "pantyhose" and re.search(r"膝盖", beat):
                add("knees")
    if _has_removal_action(beat):
        tags = [tag for tag in tags if tag.lower() not in ("hands on hips", "hands on hip")]
    if re.search(r"靠在床头|坐起|坐起来", beat):
        tags = [tag for tag in tags if tag.lower() not in (
            "lying", "lying down", "lying on side", "legs spread")]
        add("sitting")
    if re.search(r"盖住下半身|用被子", beat):
        tags = [tag for tag in tags
                if tag.lower() not in ("masturbation", "hand on bedsheet")]
        add("blanket", "topless")
    return limit_tags(", ".join(tags))


def normalize_outline(raw: dict[str, Any] | list[Any], wanted: int,
                      fallback_prefix: str, start: int = 1,
                      used_names: list[str] | None = None,
                      forced_cast: str = "") -> list[dict[str, str]]:
    items = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Outline response has no 'shots' array.")
    outline: list[dict[str, str]] = []
    used = {name.lower() for name in (used_names or [])}
    for index, item in enumerate(items[:wanted]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("outline") or item.get("script")
                   or item.get("prompt") or item.get("description") or "").strip()
        if not text:
            continue
        number = "%02d" % (start + len(outline))
        base = slugify(item.get("name") or "%s_%s" % (fallback_prefix, number),
                       "shot_%s" % number)
        name, counter = base, 2
        while name.lower() in used:
            name = "%s_%d" % (base, counter)
            counter += 1
        used.add(name.lower())
        hinted = str(item.get("cast") or "").strip()
        cast = forced_cast or " ".join(detect_cast(text, hinted)) or hinted
        outline.append({"id": number, "name": name, "cast": cast, "outline": text})
    if not outline:
        raise ValueError("Model returned no usable outline.")
    return outline


def build_outline_messages(premise: str, shots: int, setting: str,
                           prior: list[dict[str, str]], total: int,
                           start: int, strip_appearance: bool = False,
                           spine: dict[str, Any] | None = None) -> list[dict[str, str]]:
    user = [
        "剧情：%s" % premise,
        "本次大纲：第 %d-%d 镜，共 %d 镜" % (start, start + shots - 1, total),
    ]
    if spine:
        user.extend([
            "当前硬性阶段：第 %d-%d 镜，阶段内容：%s" % (
                spine.get("start", start), spine.get("end", total),
                spine.get("summary", "")),
            "本阶段 cast 固定为：%s；不得提前进入下一阶段，也不得退回上一阶段。" % (
                spine.get("cast") or "按剧情"),
            "本阶段进度：第 %d/%d 镜开始；每一镜必须比上一镜推进，禁止复制上一镜的"
            "动作、姿势、构图或同一句改写。" % (
                start - int(spine.get("start", start)) + 1,
                int(spine.get("end", total)) - int(spine.get("start", start)) + 1),
        ])
        phase = spine.get("phase", "")
        if phase == "sex":
            user.append("本阶段每一镜都必须是性行为：不要停留在走到床边、脱衣、接吻或拥抱前戏。"
                        "允许保留情趣内衣、紧身衣、丝袜、吊带袜、高跟鞋，可半脱、拉下或用 "
                        "panties aside/off shoulder 等状态标签。每镜必须换一种姿势或互动："
                        "cowgirl、reverse cowgirl、missionary、doggy style、side sex、leg lift、"
                        "standing sex、spooning 等；加入对视、接吻、手扶腰/颈/头发、揉胸、"
                        "十指相扣、抱腰等互动。禁止连续两镜重复同一姿势、机位和动作。")
        elif phase == "discovery":
            user.append("本阶段是男主首次发现/入场：必须写清我进入、看到、撞见；"
                        "从本阶段第一镜开始 cast 就是 1girl 1boy。")
        elif phase == "seduction":
            user.append("本阶段必须主动勾引并完成脱衣前戏：靠近、看镜头、解衣、触碰对方，"
                        "禁止继续单人自慰或停在害羞；允许保留内衣、丝袜、高跟鞋等情趣衣物，"
                        "不要把所有衣物提前脱光。")
        elif phase == "solo":
            user.append("本阶段只允许 1girl solo，男主不得出现。")
        elif phase == "afterglow":
            user.append("本阶段是性行为后的收尾：允许拥抱、依偎、余韵，不要再安排新的脱衣过程。")
    if strip_appearance:
        user.append("已启用角色 LoRA：不要生成或补充角色外貌和身体特征（发色、瞳色、发型、"
                    "脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责。")
    if setting.strip():
        user.append("固定场景/附加要求：%s" % setting.strip())
    if prior:
        user.append("上一段大纲（保持剧情方向，禁止重复其动作和句子）：\n" +
                    "\n".join("%s %s" % (item["id"], item["outline"])
                              for item in prior[-2:]))
    user.append("请生成完整编号大纲。每条必须覆盖：身份、服装/裸露、可见部位、姿势动作、"
                "表情、场景、镜头、构图、光线、NSFW、cast。每条 outline 必须不同。")
    return [
        {"role": "system", "content": OUTLINE_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def plan_storyboard_outline(client: OllamaClient, model: str, premise: str,
                            shots: int, setting: str = "", chunk: int = 6,
                            timeout: float = 600.0,
                            strip_appearance: bool = False,
                            spine: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    outline: list[dict[str, str]] = []
    used_names: list[str] = []
    if spine:
        for entry in spine:
            entry_end = min(shots, int(entry.get("end", shots)))
            while len(outline) < entry_end:
                need = min(chunk, entry_end - len(outline))
                start = len(outline) + 1
                raw = client.chat_json(
                    model,
                    build_outline_messages(premise, need, setting, outline, shots, start,
                                           strip_appearance=strip_appearance, spine=entry),
                    schema=OUTLINE_SCHEMA,
                    temperature=0.6,
                    num_predict=max(4096, min(8192, need * 1200)),
                    num_ctx=32768,
                    keep_alive="5m",
                    timeout=timeout,
                    retries=0,
                )
                part = normalize_outline(
                    raw, need, slugify(premise, "story") or "story",
                    start=start, used_names=used_names,
                    forced_cast=str(entry.get("cast") or ""))
                for item in part:
                    item["phase"] = str(entry.get("phase") or "")
                outline.extend(part)
                used_names.extend(item["name"] for item in part)
                if not part:
                    break
    else:
        max_tries = (shots // max(1, chunk)) + 4
        for _ in range(max_tries):
            if len(outline) >= shots:
                break
            need = min(chunk, shots - len(outline))
            start = len(outline) + 1
            raw = client.chat_json(
                model,
                build_outline_messages(premise, need, setting, outline, shots, start,
                                       strip_appearance=strip_appearance),
                schema=OUTLINE_SCHEMA,
                temperature=0.6,
                num_predict=max(4096, min(8192, need * 1200)),
                num_ctx=32768,
                keep_alive="5m",
                timeout=timeout,
                retries=0,
            )
            part = normalize_outline(raw, need, slugify(premise, "story") or "story",
                                     start=start, used_names=used_names)
            outline.extend(part)
            used_names.extend(item["name"] for item in part)
            if not part:
                break
    if not outline:
        raise ValueError("Model produced no usable outline.")
    return outline[:shots]


def normalize_scripts(raw: dict[str, Any] | list[Any], wanted: int,
                      fallback_prefix: str, start: int = 1,
                      used_names: list[str] | None = None) -> list[dict[str, str]]:
    items = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Script response has no 'shots' array.")
    scripts: list[dict[str, str]] = []
    used = {name.lower() for name in (used_names or [])}
    for index, item in enumerate(items[:wanted]):
        if not isinstance(item, dict):
            continue
        script = str(item.get("script") or item.get("prompt") or "").strip()
        if not script:
            continue
        number = "%02d" % (start + len(scripts))
        base = slugify(item.get("name") or "%s_%s" % (fallback_prefix, number),
                       "shot_%s" % number)
        name, counter = base, 2
        while name.lower() in used:
            name = "%s_%d" % (base, counter)
            counter += 1
        used.add(name.lower())
        scripts.append({
            "id": number,
            "name": name,
            "script": script,
            "cast": str(item.get("cast") or "").strip(),
            "outline": "",
        })
    if not scripts:
        raise ValueError("Model returned no usable Chinese scripts.")
    return scripts


def normalize_tagged(raw: dict[str, Any] | list[Any],
                     scripts: list[dict[str, str]]) -> list[dict[str, str]]:
    items = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Tag response has no 'shots' array.")
    by_id = {str(item.get("id") or ""): item for item in items
             if isinstance(item, dict)}
    shots: list[dict[str, str]] = []
    for index, script in enumerate(scripts):
        item = by_id.get(script["id"])
        if item is None and index < len(items) and isinstance(items[index], dict):
            item = items[index]
        if not item:
            continue
        prompt = clean_prompt(item.get("prompt") or item.get("tags") or "")
        if not prompt:
            continue
        shots.append({
            "id": script["id"],
            "name": script["name"],
            "prompt": limit_tags(prompt),
            "script": script["script"],
            "cast": script.get("cast", ""),
            "phase": script.get("phase", ""),
            "outline": script.get("outline") or script["script"],
        })
    if not shots:
        raise ValueError("Model returned no usable tagged shots.")
    return shots


def build_script_messages(premise: str, shots: int, setting: str,
                           prior: list[dict[str, str]], total: int | None = None,
                           beats: list[str] | None = None,
                           strip_appearance: bool = False,
                           phase: str = "", cast_hint: str = "") -> list[dict[str, str]]:
    start = len(prior) + 1
    user = [
        "剧情：%s" % premise,
        "本次生成镜头数：%d%s" % (
            shots, ("（第 %d-%d 镜，共 %d 镜）" %
                    (start, start + shots - 1, total) if total else "")),
    ]
    if phase:
        user.append("本段阶段：%s；cast 固定：%s。" % (phase, cast_hint or "按剧情"))
        if phase == "sex":
            user.append("本段每一镜都必须是性行为；禁止写走到床边、脱衣、接吻、拥抱或前戏。"
                        "允许保留情趣内衣、紧身衣、丝袜、吊带袜、高跟鞋，可半脱或拉下。"
                        "逐镜写插入、抽送、姿势变化、高潮/余韵；每镜必须换姿势或互动，"
                        "不要连续重复同一姿势、机位和动作。")
        elif phase == "discovery":
            user.append("本段男主必须首次出现并看到/撞见；写清 1girl 1boy。")
        elif phase == "seduction":
            user.append("本段必须主动勾引并完成脱衣前戏，不能继续单人自慰；"
                        "允许保留内衣、丝袜、高跟鞋等情趣衣物，不要提前全部脱光。")
        elif phase == "solo":
            user.append("本段只允许 1girl solo，男主不得出现。")
    if strip_appearance:
        user.append("已启用角色 LoRA：不要生成或补充角色外貌和身体特征（发色、瞳色、发型、"
                    "脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责。")
    if setting.strip():
        user.append("固定场景锁/附加要求（全程硬约束）：%s" % setting.strip())
    if beats:
        user.append("硬性剧情条目（第 %d 镜必须对应第 %d 条，不得合并、跳过或提前）：\n" %
                    (start, start) + "\n".join(
                        "%d. %s" % (start + index, beat)
                        for index, beat in enumerate(beats)))
    if prior:
        tail = "\n".join("%s %s" % (
            shot.get("id", ""), shot.get("script") or shot.get("prompt", ""))
            for shot in prior[-2:])
        user.append("上一段已完成分镜脚本（保持连续，禁止复穿/跳步/换场景）：\n" + tail)
    user.append("请只输出中文分镜脚本，每镜必须覆盖身份、服装/裸露、可见部位、姿势动作、"
                "表情、场景、镜头、构图、光线、NSFW；从第 %d 镜开始编号。" % start)
    return [
        {"role": "system", "content": SCRIPT_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def build_tag_messages(scripts: list[dict[str, str]], style_positive: str = "",
                       setting: str = "", strip_appearance: bool = False,
                       phase: str = "", cast_hint: str = "") -> list[dict[str, str]]:
    user = []
    if phase:
        user.append("本段阶段：%s；cast 固定：%s。" % (phase, cast_hint or "按剧情"))
        if phase == "sex":
            user.append("本段每一镜都必须是性行为：必须输出 sex, vaginal, penis, penetration，"
                        "以及插入/抽送/高潮；禁止输出脱衣、接吻、拥抱或前戏。"
                        "允许保留 lingerie、leotard、pantyhose、stockings、heels 等情趣衣物，"
                        "可用 pulled down、panties aside、off shoulder。每镜加入不同姿势和互动："
                        "cowgirl/reverse cowgirl/missionary/doggy style/side sex/leg lift、"
                        "eye contact、kiss、hand on waist/neck/hair、breast grab、holding hands。")
        elif phase == "discovery":
            user.append("本段男主首次出现，必须保留 1boy。")
        elif phase == "seduction":
            user.append("本段必须是主动勾引并完成脱衣前戏；允许保留内衣、丝袜、高跟鞋等情趣衣物，"
                        "不要提前全部脱光。")
        elif phase == "solo":
            user.append("本段保持 1girl solo，不出现 1boy。")
    if strip_appearance:
        user.append("已启用角色 LoRA：不要输出角色外貌和身体特征（发色、瞳色、发型、脸、"
                    "肤色、体型、胸围等），这些由 LoRA 和激活标签负责。")
    if style_positive.strip():
        user.append("画风：%s" % style_positive.strip())
    if setting.strip():
        user.append("固定场景锁/附加要求：%s" % setting.strip())
    user.append("中文分镜脚本：")
    for script in scripts:
        user.append("id=%s name=%s\n剧情节点=%s\n脚本=%s" % (
            script["id"], script["name"],
            script.get("outline") or script.get("script", ""),
            script["script"]))
    user.append("请逐镜转换成英文 Booru prompt；保留全部剧情/服装/场景/NSFW，"
                "重复固定场景词，不要参考角色标签。")
    return [
        {"role": "system", "content": TAG_SYSTEM},
        {"role": "user", "content": "\n\n".join(user)},
    ]


def generate_storyboard(client: OllamaClient, premise: str,
                        options: StoryboardOptions,
                        initial_shots: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """Generate shots in chunks from the premise and current-run prior shots."""

    initial = [dict(shot) for shot in (initial_shots or [])]
    shots = max(len(initial), int(options.shots))
    chunk = max(1, int(options.chunk))
    log = options.log
    result: list[dict[str, str]] = initial[:shots]
    if len(result) >= shots:
        return result[:shots]

    script_base = len(result)
    remaining = shots - script_base
    premise_beats = extract_premise_beats(premise)
    if premise_beats:
        outline = []
        for index, beat in enumerate(premise_beats[script_base:shots]):
            number = "%02d" % (script_base + index + 1)
            outline.append({
                "id": number,
                "name": "shot_%s" % number,
                "cast": " ".join(detect_cast(beat, "", premise)),
                "outline": beat,
                "phase": _story_phase(beat),
            })
    else:
        spine = build_story_spine(premise, remaining)
        if spine:
            log("Stage 0: story spine -> " + " | ".join(
                "%d-%d:%s(%s)" % (item["start"], item["end"], item["summary"][:16],
                                  item["phase"]) for item in spine))
        log("Stage 0: planning %d numbered outline entries..." % remaining)
        outline = plan_storyboard_outline(
            client, options.model, premise, remaining, options.setting,
            chunk=6, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance, spine=spine or None)
    if not outline:
        raise ValueError("Model produced no usable storyboard outline.")
    story_beats = [item["outline"] for item in outline]
    clothing_states = clothing_states_for_beats(premise, story_beats)
    scene_states = scene_states_for_beats(story_beats)

    chunks: list[tuple[int, list[dict[str, str]]]] = []
    offset = 0
    while offset < len(outline):
        phase = outline[offset].get("phase", "")
        end = offset + 1
        while (end < len(outline) and end - offset < chunk
               and outline[end].get("phase", "") == phase):
            end += 1
        chunks.append((offset, outline[offset:end]))
        offset = end
    for offset, outline_chunk in chunks:
        beat_slice = [item["outline"] for item in outline_chunk]
        log("Stage A: writing scripts for shots %d-%d..." % (
            script_base + offset + 1,
            script_base + offset + len(outline_chunk)))
        script_raw = client.chat_json(
            options.model,
            build_script_messages(
                premise, len(outline_chunk), options.setting,
                result, shots, beat_slice,
                strip_appearance=options.strip_appearance,
                phase=str(outline_chunk[0].get("phase") or ""),
                cast_hint=str(outline_chunk[0].get("cast") or "")),
            schema=SCRIPT_SCHEMA,
            temperature=options.temperature,
            num_predict=8192,
            num_ctx=32768,
            keep_alive=options.keep_alive,
            timeout=options.timeout,
        )
        script_chunk = normalize_scripts(
            script_raw, len(outline_chunk), slugify(premise, "story") or "story",
            start=script_base + offset + 1,
            used_names=[shot["name"] for shot in result])
        for index, script in enumerate(script_chunk):
            if index < len(outline_chunk):
                script["cast"] = outline_chunk[index]["cast"]
                script["outline"] = outline_chunk[index]["outline"]
                script["phase"] = outline_chunk[index].get("phase", "")
        log("Stage B: translating shots %d-%d to English tags..." % (
            script_base + offset + 1,
            script_base + offset + len(script_chunk)))
        tag_raw = client.chat_json(
            options.model,
            build_tag_messages(
                script_chunk, options.style_positive, options.setting,
                strip_appearance=options.strip_appearance,
                phase=str(script_chunk[0].get("phase") or ""),
                cast_hint=str(script_chunk[0].get("cast") or "")),
            schema=TAG_SCHEMA,
            temperature=options.temperature,
            num_predict=8192,
            num_ctx=32768,
            keep_alive=options.keep_alive,
            timeout=options.timeout,
        )
        part = normalize_tagged(tag_raw, script_chunk)
        state_offset = len(result)
        for index, shot in enumerate(part):
            beat = (beat_slice[index]
                    if beat_slice and index < len(beat_slice) else "")
            source = beat or shot.get("outline") or shot.get("script") or ""
            shot["prompt"] = strip_generation_quality(shot["prompt"])
            if options.strip_appearance:
                shot["prompt"] = strip_stage1_identity(
                    shot["prompt"], options.character_tags)
            if source:
                shot["prompt"] = enforce_beat_terms(shot["prompt"], source)
            state_index = state_offset + index
            if (beat and state_index < len(clothing_states)
                    and state_index < len(scene_states)):
                worn = clothing_states[state_index]
                scene = scene_states[state_index]
                shot["prompt"] = apply_story_state(
                    shot["prompt"], beat, worn, scene)
                shot["clothing"] = ", ".join(sorted(worn))
                shot["scene"] = ", ".join(scene)
            shot["prompt"] = apply_cast_state(
                shot["prompt"], shot.get("script") or source,
                shot.get("cast", ""), premise)
            phase = str(shot.get("phase") or _story_phase(source))
            shot["prompt"] = apply_phase_terms(
                shot["prompt"], phase, shot.get("cast", ""))
            shot["prompt"] = normalize_prompt_tags(shot["prompt"])
        result.extend(part)
        log("Stage B: +%d shots (%d/%d)" % (len(part), len(result), shots))
        if not part:
            break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    return result[:shots]
