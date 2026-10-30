"""Ollama storyboard generation: premise -> continuous shot list."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient

PROMPT_COVERAGE = (
    "覆盖维度：角色身份与外观、服装/裸露状态、当前可见身体部位、姿势、动作、表情、"
    "场景/地点、镜头景别、机位/角度、构图、光线/时间、NSFW 状态。"
)
INTIMATE_CLOTHING_EVENTS = (
    "可选的服装破坏/半脱情色元素（按剧情选用，不要每镜都用，也不要无铺垫突然撕毁）："
    "1. 撕破连裤袜/丝袜/渔网袜/蕾丝袜的裆部、膝盖、大腿或胸口，露出内裤、皮肤或私处；"
    "2. 拨开、拉开、扯到一边或撕破情趣内裤/蕾丝内裤/黑色蕾丝内裤/半透明内裤/"
    "丁字裤/C字裤/开裆内裤/珍珠内裤，半挂在腿侧；"
    "3. 扯开衬衫、制服、旗袍、婚纱、连衣裙、紧身衣的纽扣、拉链、肩带或吊带；"
    "4. 推下胸罩、扯断肩带、解开后背扣、撕下乳贴或让无肩带胸罩滑落；"
    "5. 撕破蕾丝手套、臂套、腿环、吊袜带、束腰、连体衣/连裤袜，破洞露出皮肤；"
    "6. 破损后衣物仍挂在身上，隔着破洞抚摸、指交、口交、乳交、磨蹭或插入；"
    "7. 事后破损衣物滑落、挂在腰/腿/手臂，边缘撕裂、潮湿，保持连续不要自动复原。"
    "标签示例：torn pantyhose, ripped pantyhose, torn stockings, torn fishnet, "
    "torn panties, panties aside, lace panties, black lace panties, sheer panties, "
    "lace underwear, lace lingerie, lace bra, lace trim, torn shirt, open shirt, "
    "torn dress, torn skirt, torn leotard, torn bodysuit, broken bra, bra pull, "
    "torn gloves, torn garter, torn corset, clothes torn, ripped clothes, "
    "hole in clothes, crotchless。"
)
BOORU_WORKFLOW = (
    "先在心里拆解，不要把拆解过程写进结果：人数/cast、当前服装结果、姿势、动作、表情、"
    "NSFW、场景、光线、镜头。再严格按此顺序组装标签：cast → 服装/裸露 → 姿势 → 动作 → "
    "表情 → NSFW → 场景 → 光线 → 镜头。已经脱掉的服装标签必须删除。"
    "性行为段每镜换姿势和互动，禁止连续重复同一姿势。情趣服装保留不要全部脱掉，除非剧情明确要求全裸。"
    "表现半脱，适当增加色情细节。" + INTIMATE_CLOTHING_EVENTS +
    "撕破的服装必须保留为状态标签，不能改写成普通完整服装。"
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
    + INTIMATE_CLOTHING_EVENTS +
    "禁止复制上一镜、禁止只写同一动作、禁止所有镜头重复。\n"
    "3. 固定场景/建筑/时间/光线必须全程连续，只有剧情明确移动才换地点。\n"
    "4. 每个角色都必须遵守角色锁定表：外貌、初始服装、当前服装和裸露状态独立连续；"
    "禁止发明锁定表之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣等；禁止复穿已脱衣物，禁止跳步；"
    "脱衣必须写清是哪个角色、具体哪件初始服装；男主/男性/我脱衣或全裸时必须写清，不能影响女主状态。\n"
    "5. cast 必须写人物数量与性别：单人 1girl solo；女主+我/任意男性 1girl 1boy；没有出现的角色不得写。\n"
    "6. 按起承转合推进，不能从开头几镜后开始循环。\n"
    "只输出 JSON shots[{id,name,cast,outline}]，不要解释，不要英文标签。"
)

SCRIPT_SYSTEM = (
    "你是二次元 NSFW 剧情大纲和分镜编剧。先只生成中文分镜脚本，不写英文标签。\n"
    "成功标准（必须全部满足，否则视为失败）：\n"
    "1. 固定场景（如果用户有指定则受本条限制，没指定可不受本条限制）：剧情指定的地点、家具、时间、光线全部格子不得更换；每镜 script 重复写同一场景关键词。\n"
    "2. 每个角色服装只能从各自初始服装开始，禁止发明锁定表之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣等；"
    "禁止复穿已脱衣物，禁止跳步；写清每个角色当前还穿着什么、已脱哪件初始服装；"
    "男主/男性/我脱衣、半裸或全裸时必须写清，不能影响女主状态。"
    + INTIMATE_CLOTHING_EVENTS +
    "3. 每镜 script 必须覆盖：角色/cast、服装/裸露状态、可见身体部位、姿势动作、表情、"
    "地点、景别、机位/角度、构图、光线时间、NSFW 状态。\n"
    "4. 因果连续：下一镜必须能从上镜动作自然接上，禁止无故重启动作或换场景。\n"
    "6. 每镜 cast 必须写清人物数量与性别：单人用 1girl solo；女主+我/其他男性同框用 1girl 1boy；"
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
    "1. 只输出 schema JSON：shots[{id,prompt}]。\n"
    "2. " + BOORU_WORKFLOW + "\n"
    "3. 保留 script 的全部剧情：服装/裸露、可见身体部位、姿势动作、表情、NSFW、场景、光线、镜头；"
    "不要漏固定场景词，不要只写身份或服装清单。若 script 有撕破、破损、拨开衣物，"
    "必须输出对应状态标签，不能改成普通完整服装。\n"
    "4. 必须按 script 的 cast 写清人数与性别：单人 1girl, solo；女主+我 1girl, 1boy；"
    "禁止出现 cast 之外的 second person、people、multiple boys、multiple girls。"
    "角色锁定表里 appearance 非空时必须逐字保留该角色的发色、瞳色、发型、脸和身体特征，"
    "不能改变；appearance 为空的角色不要自行补充。"
    "禁止添加 script 或锁定表之外的内衣、内裤、丝袜、胸罩或蕾丝。\n"
    "5. 标签用标准 Danbooru 词，不写整句英文。\n"
    "6. 每条 prompt 建议 25-45 个标签，复杂场景 50-70，最多 100；英文逗号分隔、去重，不要为凑数堆标签。\n"
    "7. 镜头只用 full body、upper body、close-up、medium shot、wide shot、from above/below/side、"
    "dutch angle、POV、depth of field 等抽象词；禁止 camera、holding camera、lens、tripod、photographer。\n"
    "8. 看向镜头写 looking at viewer，不写 looking at camera。本阶段不接收任何角色标签。\n"
    "9. 不生成质量/画质标签（masterpiece, best quality, absurdres、ultra-detailed、highres、sharp focus 等）。\n"
    "内容示例（只学组织顺序，不要照抄）：坐在床边，双腿分开，手指插入，半闭眼，卧室台灯，夜晚。"
    "→ 1girl, solo, completely nude, pussy, sitting on bed, legs spread, fingering, finger in pussy, "
    "half-closed eyes, bedroom, bed, lamp, night, soft lighting, medium shot。"
)

STORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "story": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "gender": {"type": "string"},
                    "appearance": {"type": "string"},
                    "initial_clothing": {"type": "string"},
                },
                "required": ["name", "gender", "appearance", "initial_clothing"],
            },
        },
    },
    "required": ["story", "characters"],
}

STORY_SYSTEM = (
    "你是二次元 NSFW 剧情编剧。根据用户自然语言写出完整剧情，不写分镜标签，不写镜头编号。\n"
    "要求：\n"
    "1. 写清开始、发展、转折、高潮、结尾，不能只写开头就循环。\n"
    "2. 根据用户要求的总格数提供足够的剧情事件；30 格一幕，每一幕有独立事件和进展。\n"
    "3. 先建立角色锁定表 characters，覆盖剧情中所有实际出场角色：女主、男主、我/男性、配角、"
    "以及多人场景中的每个人。每个角色必须有唯一 name、gender、固定 appearance、initial_clothing。"
    "appearance 写英文 Booru 外貌标签（发色、发型、瞳色、体型、标志物、服装以外的固定特征）；"
    "男性和女性都适用。若角色使用角色 LoRA 且用户没有提供外貌，appearance 可以留空。"
    "用户给出某角色初始服装时必须逐字使用，不能添加该角色初始服装之外的单品；"
    "用户没有给出某角色服装时，可以在 characters 中为该角色一次性建立固定初始服装，"
    "必须用英文 Booru 标签，之后全片不得更换。男主/男性/我如果实际出现在画面中，"
    "也必须在 characters 中建立固定外貌和初始服装。"
    "characters 建立后，全片不得改变角色外貌、发色、瞳色、体型或初始服装归属。\n"
    "4. 服装只从每个角色自己的初始服装单向变化；慢脱、慢调情，不要一开场就全裸；"
    "禁止发明初始服装之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣或其他衣物；"
    "需要脱掉时只能脱该角色初始服装中明确存在的单品，脱掉的不得再穿回；"
    "性行为中可以保留情趣服装，只有剧情后段才少量全裸。每个角色的裸露状态必须独立连续，"
    "不能男主脱了又穿、女主裸了男主也跟着跳变。\n"
    "5. 固定场景、人物关系和人物数量必须前后一致；只有剧情明确移动才换场景。\n"
    "6. 性行为、前戏、脱衣、高潮等必须写清楚，不要用模糊词或跳过。"
    + INTIMATE_CLOTHING_EVENTS +
    "要与挑逗、爱抚、自慰、性行为等场景自然组合，写清哪件衣物破损、位置、当前遮挡或暴露状态。\n"
    "7. 只输出 JSON：{\"story\": \"完整中文剧情\", \"characters\": [{\"name\":\"...\","
    "\"gender\":\"girl/boy\",\"appearance\":\"...\",\"initial_clothing\":\"...\"}]}，"
    "不要解释，不要分镜 JSON。\n"
)

ACT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "cast": {"type": "string"},
                    "clothing": {"type": "string"},
                    "scene": {"type": "string"},
                    "nsfw": {"type": "string"},
                },
                "required": ["id", "title", "summary", "cast", "clothing", "scene", "nsfw"],
            },
        }
    },
    "required": ["acts"],
}

ACT_PLAN_SYSTEM = (
    "你是连续剧情分幕编剧。把完整剧情按用户要求的总格数拆成若干幕。\n"
    "要求：\n"
    "1. 每幕最多 30 格；用户总格数超过 30 时，最后一幕可以少于 30 格。\n"
    "2. 按剧情顺序覆盖全部内容，不能漏掉结尾，不能重复同一事件。\n"
    "3. 每幕 summary 写清：本幕发生什么、谁出现、每个角色的服装/裸露进度、场景、NSFW 进度；"
    "如果有服装破损/撕毁、拨开情趣内裤等情节，也要写清哪个角色、哪件衣物、位置和当前状态；"
    "下一幕必须能自然接上上一幕。\n"
    "4. cast 写清本幕人物，例如 1girl solo、1girl 1boy；不确定就按剧情写。"
    "男主/男性/我只要出场，就必须与原角色锁定表的外貌、服装和裸露状态一致。\n"
    "5. clothing 写本幕服装起点和终点，必须按角色分别写，只能使用各角色初始服装中存在的单品；"
    "禁止新增初始服装之外的内衣/内裤/丝袜/胸罩/蕾丝；scene 写本幕主场景；nsfw 写本幕情色/性行为进度。\n"
    "只输出 JSON：{\"acts\":[{\"id\":\"01\",\"title\":\"...\",\"summary\":\"...\","
    "\"cast\":\"...\",\"clothing\":\"...\",\"scene\":\"...\",\"nsfw\":\"...\"}]}，不要解释。\n"
)


def raw_prompt(text: Any) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"^\s*(prompt|tags|positive|提示词|标签|正向)\s*[:：]\s*", "", value, flags=re.I)
    return value.strip(",;. ")


def slugify(text: Any, fallback: str = "") -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    value = re.sub(r"_+", "_", value)
    return value[:40] or fallback


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
    full_story: bool = False
    on_partial: Callable[[list[dict[str, str]]], None] | None = None
    log: Callable[[str], None] = field(default=lambda _msg: None)


@dataclass
class CharacterProfile:
    key: str
    name: str = ""
    gender: str = "girl"
    appearance: list[str] = field(default_factory=list)
    initial_clothing: list[str] = field(default_factory=list)


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




def build_story_spine(premise: str, shots: int) -> list[dict[str, Any]]:
    clauses = _split_story_clauses(premise)
    if not clauses:
        return []
    if len(clauses) > shots:
        size = (len(clauses) + shots - 1) // shots
        clauses = ["，".join(clauses[index:index + size])
                   for index in range(0, len(clauses), size)]
    spine: list[dict[str, Any]] = []
    for clause in clauses:
        spine.append({"summary": clause, "cast": "", "phase": ""})

    weights = []
    for item in spine:
        phase = item["phase"]
        weights.append({
            "story": 0.90, "solo": 1.10, "discovery": 1.20,
            "seduction": 1.80, "sex": 2.20, "afterglow": 0.70,
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


def _phase_at(spine: list[dict[str, Any]], number: int) -> dict[str, Any]:
    for item in spine:
        if int(item.get("start", 0)) <= number <= int(item.get("end", 0)):
            return item
    return {}


def _act_summary(spine: list[dict[str, Any]], start: int, end: int) -> str:
    items = [item for item in spine
             if int(item.get("end", 0)) >= start and int(item.get("start", 0)) <= end]
    if not items:
        return "本幕承接上一幕，延续剧情主线和服装进度。"
    return "；".join(
        "%s（%s，%s）" % (item.get("summary", ""), item.get("cast", ""),
                         item.get("phase", "")) for item in items)


def _global_story_state(premise: str, shots: list[dict[str, Any]],
                        profiles: list[CharacterProfile] | None = None) -> str:
    if not shots:
        return ("全局状态表：剧情开始；场景按剧情；服装按初始服装顺向递进；"
                "禁止跳场景、复穿、提前裸露、改变角色外貌。")
    last = shots[-1]
    clothing = str(last.get("clothing") or last.get("prompt") or "").strip()
    if profiles and isinstance(last.get("character_states"), dict):
        states = _shot_character_states(last, profiles)
        clothing = "；".join(
            "%s=%s" % (
                profile.name,
                ", ".join(sorted(states.get(profile.key) or set()))
                or ("全裸" if profile.initial_clothing else "未指定"))
            for profile in profiles)
    scene = str(last.get("scene") or "").strip()
    recent = "; ".join(
        "%s %s" % (shot.get("id", ""), str(shot.get("outline") or shot.get("prompt") or "")[:100])
        for shot in shots[-3:])
    return ("全局状态表：场景=%s；服装进度=%s；最近剧情=%s；禁止换场景、复穿已脱衣物、"
            "跳步、突然全裸、改变角色外貌。" % (
                scene or "沿用上一镜", clothing[:400] or "按初始服装", recent))


_CLOTHING_KEYS = (
    ("fishnet", (r"fishnet", r"net tights", r"网袜", r"渔网袜", r"网眼袜")),
    ("pantyhose", (r"pantyhose", r"tights", r"黑丝", r"白丝", r"丝袜",
                   r"连裤袜")),
    ("legwear", (r"legwear", r"腿部装饰", r"腿饰", r"袜圈")),
    ("stockings", (r"\bstockings?\b", r"hold-ups", r"hold ups", r"长筒袜",
                   r"长袜", r"大腿袜", r"吊带袜")),
    ("thighhigh", (r"thighhigh", r"thigh[ -]?highs?", r"over-knee",
                   r"过膝袜")),
    ("leggings", (r"\bleggings?\b", r"打底裤", r"紧身裤")),
    ("socks", (r"\bsocks?\b", r"袜子", r"短袜")),
    ("panties", (r"panties", r"内裤", r"底裤")),
    ("underwear", (r"underwear", r"boxers?", r"briefs?", r"boxer briefs",
                   r"trunks", r"内衣", r"内裤", r"平角裤", r"三角裤")),
    ("thong", (r"thong", r"g-string", r"丁字裤")),
    ("bra", (r"\bbra\b", r"胸罩", r"文胸")),
    ("pasties", (r"pasties", r"nipple covers", r"乳贴")),
    ("bikini", (r"bikini", r"比基尼")),
    ("swimsuit", (r"swimsuit", r"泳装", r"泳衣")),
    ("blazer", (r"blazer", r"西装")),
    ("jacket", (r"jacket", r"parka", r"windbreaker", r"bomber", r"puffer",
                r"夹克", r"外套")),
    ("coat", (r"\bcoat\b(?!\s*(?:hanger|rack))", r"大衣", r"风衣")),
    ("cardigan", (r"cardigan", r"开衫")),
    ("shirt", (r"\bshirt\b", r"tshirt", r"sweatshirt", r"shirtdress", r"衬衫",
               r"上衣", r"T恤", r"t恤", r"短袖", r"长袖")),
    ("vest", (r"\bvests?\b", r"waistcoat", r"马甲", r"背心")),
    ("blouse", (r"blouse", r"女衬衫")),
    ("sweater", (r"sweater", r"jumper", r"pullover", r"turtleneck", r"毛衣",
                 r"针织衫")),
    ("hoodie", (r"hoodie", r"卫衣")),
    ("tank top", (r"tank top", r"背心")),
    ("camisole", (r"camisole", r"吊带")),
    ("crop top", (r"crop top", r"露脐装")),
    ("top", (r"tight top", r"\btop\b", r"紧身上衣", r"上衣")),
    ("lingerie", (r"lingerie", r"babydoll", r"chemise", r"teddy(?!\s*bear)",
                  r"crotchless",
                  r"open-crotch", r"shelf bra", r"蕾丝内衣", r"性感内衣",
                  r"情趣内衣")),
    ("leotard", (r"leotard", r"one-piece", r"连体衣", r"紧身衣")),
    ("bodysuit", (r"bodysuit", r"catsuit", r"unitard", r"连身衣")),
    ("armwear", (r"armlet", r"arm warmers", r"elbow glove", r"wrist cuffs",
                 r"臂环", r"袖套")),
    ("collar", (r"puritan collar", r"choker", r"\bcollar\b", r"颈圈", r"项圈")),
    ("apron", (r"apron", r"围裙")),
    ("veil", (r"veil", r"面纱", r"头纱")),
    ("mask", (r"\bmask\b", r"口罩", r"面罩")),
    ("corset", (r"corset", r"waist cincher", r"束腰")),
    ("bustier", (r"bustier", r"抹胸")),
    ("garter", (r"garter belt", r"suspender belt", r"garter", r"suspenders?",
                r"吊袜带", r"吊带")),
    ("maid", (r"maid outfit", r"maid uniform", r"maid dress",
              r"maid(?!\s*cafe)", r"女仆装")),
    ("nurse", (r"nurse outfit", r"nurse uniform", r"nurse dress", r"护士服")),
    ("bunny", (r"bunny girl", r"bunny suit", r"playboy bunny", r"兔女郎")),
    ("cheerleader", (r"cheerleader outfit", r"cheerleader uniform",
                     r"cheerleader", r"啦啦队")),
    ("hanfu", (r"hanfu", r"汉服")),
    ("sailor", (r"sailor uniform", r"sailor dress", r"sailor outfit",
                r"sailor collar", r"水手服")),
    ("gym", (r"gym uniform", r"gym outfit", r"gym clothes", r"运动服")),
    ("school", (r"school uniform", r"school outfit", r"school clothes",
                r"serafuku", r"校服")),
    ("wedding", (r"wedding dress", r"wedding gown", r"wedding outfit", r"婚纱")),
    ("sports", (r"sports uniform", r"sports outfit", r"sports clothes", r"运动装")),
    ("dress", (r"\bdress\b(?!\s*(?:shirt|shoes?|boots?|pants|trousers))",
               r"sun ?dress", r"连衣裙", r"长裙", r"裙")),
    ("kimono", (r"kimono", r"和服")),
    ("yukata", (r"yukata", r"浴衣")),
    ("qipao", (r"qipao", r"cheongsam", r"旗袍")),
    ("robe", (r"robe", r"长袍")),
    ("uniform", (r"uniform", r"制服", r"校服")),
    ("suit", (r"\bsuit\b(?!\s*(?:pants|trousers|jacket|shirt|shoes?))",
              r"tuxedo", r"套装", r"西服", r"西装")),
    ("armor", (r"armor", r"盔甲", r"铠甲")),
    ("skirt", (r"skirt", r"裙子", r"短裙", r"裙")),
    ("pants", (r"pants(?!less)", r"trousers", r"slacks", r"chinos", r"joggers",
               r"裤子", r"长裤", r"西裤", r"休闲裤", r"运动裤")),
    ("jeans", (r"jeans", r"牛仔裤")),
    ("shorts", (r"shorts", r"短裤")),
    ("heels", (r"\bheels?\b", r"stilettos?", r"pumps?", r"platform heels",
               r"high heels", r"高跟鞋")),
    ("boots", (r"\bboots?\b", r"靴子", r"靴")),
    ("shoes", (r"\bshoes?\b", r"sneakers?", r"trainers?", r"loafers?",
               r"brogues?", r"oxfords?", r"footwear", r"鞋", r"运动鞋", r"皮鞋")),
    ("sandals", (r"\bsandals?\b", r"flip-flops?", r"凉鞋", r"拖鞋")),
    ("slippers", (r"\bslippers?\b", r"拖鞋")),
    ("gloves", (r"\bgloves?\b", r"手套")),
    ("hat", (r"\bhats?\b", r"帽子")),
    ("scarf", (r"\bscarfs?\b", r"\bscarves\b", r"围巾")),
    ("necktie", (r"necktie", r"bowtie", r"bow tie", r"领带", r"领结")),
    ("belt", (r"\bbelts?\b", r"腰带")),
)
_SCENE_TAGS = {
    "bedroom": ["bedroom", "bed", "indoors", "double bed", "bedside table",
                "nightstand lamp", "bed sheet", "pillow", "duvet",
                "half-open curtains", "window"],
    "living": ["living room", "sofa", "couch", "coffee table", "rug",
               "television", "indoors"],
    "room": ["room", "indoors"],
    "home": ["home", "indoors"],
    "study": ["study", "desk", "bookshelf", "desk lamp", "indoors"],
    "dining": ["dining room", "dining table", "chair", "indoors"],
    "dressing": ["dressing room", "wardrobe", "mirror", "clothes rack", "indoors"],
    "closet": ["closet", "wardrobe", "hangers", "indoors"],
    "balcony": ["balcony", "railing", "night city", "outdoors"],
    "garden": ["garden", "flowers", "trees", "outdoors"],
    "laundry": ["laundry room", "washing machine", "indoors"],
    "basement": ["basement", "concrete wall", "indoors"],
    "attic": ["attic", "wooden beams", "indoors"],
    "bathroom": ["bathroom", "bathtub", "shower", "mirror", "towel", "sink", "indoors"],
    "kitchen": ["kitchen", "counter", "cabinets", "refrigerator", "indoors"],
    "office": ["office", "desk", "chair", "computer", "desk lamp", "indoors"],
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
    ("gym", r"健身房|健身区|gym|locker room"),
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
    ("dressing", r"更衣室|衣帽间|dressing room|wardrobe"),
    ("closet", r"衣柜|衣橱|closet"),
    ("balcony", r"阳台|balcony"),
    ("garden", r"花园|庭院|garden"),
    ("laundry", r"洗衣房|laundry"),
    ("basement", r"地下室|basement"),
    ("attic", r"阁楼|attic"),
    ("study", r"书房|study"),
    ("dining", r"餐厅|饭厅|dining room"),
    ("living", r"沙发|sofa|couch|客厅|living room"),
    ("bedroom", r"卧室|床边|床上|床单|床头|双人床|bedroom|bed\b"),
    ("home", r"家里|家中|公寓|住宅|home|apartment"),
    ("outdoors", r"户外|室外|街道|城市|outdoors|street"),
    ("room", r"房间|室内|room"),
)
def _initial_clothing_tags(premise: str) -> list[str]:
    for line in str(premise or "").splitlines():
        if "初始服装" not in line:
            continue
        parts = re.split(r"[:：]", line, maxsplit=1)
        raw = parts[1] if len(parts) == 2 else line
        return [tag.strip() for tag in re.split(r"[,，、]", raw) if tag.strip()]
    return []


def _clothing_key(tag: str) -> str:
    low = str(tag).lower().strip()
    if low in {"undressing", "dressing", "dress up", "dress down"}:
        return ""
    for key, patterns in _CLOTHING_KEYS:
        if any(re.search(pattern, low, re.I) for pattern in patterns):
            return key
    return ""


def _is_full_nude(beat: str) -> bool:
    if (re.search(r"上半身|上身|胸部|腰以上|upper body", beat, re.I)
            and re.search(r"裸露|赤裸|全裸|裸体|脱光|\bnude\b|\bnaked\b", beat, re.I)):
        return False
    return bool(re.search(
        r"全裸|裸体|赤裸|一丝不挂|脱光|光着身子|completely nude|full nude|"
        r"fully nude|\bnude\b|\bnaked\b",
        beat, re.I)) and not bool(
        re.search(r"上身.*(全裸|裸体|脱光)", beat))


_CLOTHING_REMOVE_RE = (
    r"(?:脱掉|脱去|脱下|褪下|褪去|解除|摘下|取下|滑落|脱落|掉下|"
    r"完全脱下|完全褪到|全部脱去|全部脱下|"
    r"takes? off|took off|pulls? off|pulls? down|slips? off|slides? off|"
    r"slid off|slipped? down|steps? out of|removes?|unbuttons?|unzips?|"
    r"peels? off|rips? off|tears? off|falls? off|fell off)"
)


def _removes_item(beat: str, key: str) -> bool:
    aliases = dict(_CLOTHING_KEYS).get(key, ())
    if not aliases:
        return False
    item = "(?:" + "|".join(aliases) + ")"
    return bool(re.search(
        r"(?:%s).{0,24}%s|%s.{0,24}(?:%s)" % (
            _CLOTHING_REMOVE_RE, item, item, _CLOTHING_REMOVE_RE),
        beat, re.I))


def _removes_tag(beat: str, tag: str) -> bool:
    text = str(tag or "").strip().lower()
    if not text:
        return False
    item = re.escape(text)
    if re.match(r"[a-z0-9]", text):
        item = r"\b" + item
    if re.search(r"[a-z0-9]$", text):
        item += r"\b"
    return bool(re.search(
        r"(?:%s).{0,24}%s|%s.{0,24}(?:%s)" % (
            _CLOTHING_REMOVE_RE, item, item, _CLOTHING_REMOVE_RE),
        beat, re.I))


def clothing_states_for_beats(premise: str, beats: list[str],
                              initial_worn: list[str] | None = None) -> list[set[str]]:
    initial = list(initial_worn) if initial_worn is not None else _initial_clothing_tags(premise)
    if not beats:
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


_CHARACTER_DROP_TAGS = {
    "她", "他", "我", "你", "女主", "男主", "女性", "男性", "女孩", "男孩",
    "少女", "少年", "角色", "人物", "girl", "boy", "female", "male",
    "1girl", "1boy", "solo", "multiple girls", "multiple boys",
}
_APPEARANCE_COLORS = {
    "black", "white", "silver", "grey", "gray", "blonde", "blond", "golden",
    "gold", "yellow", "red", "crimson", "pink", "purple", "violet", "blue", "aqua",
    "green", "brown", "orange", "magenta", "multicolored", "two-tone",
}
_HAIR_STYLES = {
    "long", "short", "medium", "bob", "ponytail", "twintails", "braid",
    "braids", "bangs", "hime", "bun", "pixie", "curly", "wavy", "straight",
    "messy", "slicked", "undercut", "mohawk", "ahoge", "drill", "drills",
}


_TOP_SECTION_RE = re.compile(
    r"^(?:角色设定|角色标签|角色|人物设定|人物|初始服装|初始装扮|服装|大场景|场景|"
    r"剧情|故事|额外|画风)\s*[:：]")


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


def _split_tags(text: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in re.split(r"[,，、;；|\n]+", str(text or "")):
        tag = tag.strip(" .")
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def _infer_gender(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts).lower()
    if re.search(r"男主|男性|男孩|男人|少年|青年|1boy|\bboy\b|\bmale\b|"
                 r"\bman\b|\bmen\b|(^|[^其])他|"
                 r"(?:^|[\s,，;；])男(?:$|[\s,，;；])", text):
        return "boy"
    if re.search(r"女主|女性|女孩|女人|少女|1girl|\bgirl\b|\bfemale\b|"
                 r"\bwoman\b|\bwomen\b|她|"
                 r"(?:^|[\s,，;；])女(?:$|[\s,，;；])", text):
        return "girl"
    return "other"


_ACCESSORY_PATTERNS = (
    "hairclip", "hair clip", "hairpin", "hair pin", "barrette", "hair ornament",
    "hair bow", "hair ribbon", "hairband", "hair band", "headband", "flower",
    "brooch", "earring", "earrings", "earcuff", "ear cuff", "necklace",
    "pendant", "bracelet", "bangle", "ring", "rings", "anklet", "toe ring",
    "watch", "wristwatch", "wristband", "armband", "arm band", "belly chain",
    "body chain", "glasses", "sunglasses", "goggles", "eyepatch", "piercing",
    "piercings", "tiara", "crown", "diadem",
)


def _is_accessory(tag: str) -> bool:
    low = str(tag or "").lower()
    if _clothing_key(tag):
        return False
    return any(pattern in low for pattern in _ACCESSORY_PATTERNS)


def _clean_appearance(tags: list[str]) -> list[str]:
    return [tag for tag in tags
            if tag and tag.lower() not in _CHARACTER_DROP_TAGS
            and not _clothing_key(tag) and not _is_accessory(tag)]


def parse_character_profiles(premise: str) -> list[CharacterProfile]:
    role_text = _section_text(premise, ("角色设定：", "角色设定:", "角色标签：",
                                         "角色标签:", "角色：", "角色:",
                                         "人物设定：", "人物设定:", "人物：", "人物:"))
    clothing_text = _section_text(premise, ("初始服装：", "初始服装:", "初始装扮：",
                                             "初始装扮:", "服装：", "服装:"))
    role_entries = _split_character_entries(role_text)
    clothing_entries = _split_character_entries(clothing_text)
    if "" in role_entries:
        named = [label for label in clothing_entries if label]
        if named and named[0] not in role_entries:
            role_entries[named[0]] = role_entries.pop("")
    labels = list(role_entries) + [label for label in clothing_entries if label not in role_entries]
    if not labels:
        labels = [""]
    unlabeled_role = role_entries.get("")
    unlabeled_clothing = clothing_entries.get("")
    profiles: list[CharacterProfile] = []
    for index, label in enumerate(labels):
        appearance_text = role_entries.get(label)
        clothing_value = clothing_entries.get(label)
        if index == 0:
            if appearance_text is None:
                appearance_text = unlabeled_role
            if clothing_value is None:
                clothing_value = unlabeled_clothing
        name = label or ("main" if len(labels) == 1 else "character_%02d" % (index + 1))
        gender = _infer_gender(label, appearance_text or "")
        profiles.append(CharacterProfile(
            key="char_%02d" % (index + 1),
            name=name,
            gender=gender,
            appearance=_clean_appearance(_split_tags(appearance_text or "")),
            initial_clothing=_split_tags(clothing_value),
        ))
    return profiles


def _find_character(profiles: list[CharacterProfile], name: str,
                    gender: str) -> CharacterProfile | None:
    low = str(name or "").strip().lower()
    if low:
        for profile in profiles:
            if profile.name.strip().lower() == low:
                return profile
    if len(profiles) == 1 and profiles[0].gender == "other" and gender != "other":
        return profiles[0]
    matches = [profile for profile in profiles if profile.gender == gender]
    return matches[0] if len(matches) == 1 else None


def normalize_character_profiles(raw: Any, premise: str,
                                 strip_appearance: bool = False
                                 ) -> list[CharacterProfile]:
    profiles = parse_character_profiles(premise)
    items = [item for item in raw if isinstance(item, dict)] \
        if isinstance(raw, list) else []
    if len(profiles) == 1 and profiles[0].gender == "other" and len(items) > 1:
        existing = profiles[0]
        existing_clothing = {tag.lower() for tag in existing.initial_clothing}
        existing_appearance = {tag.lower() for tag in existing.appearance}
        scored: list[tuple[int, int]] = []
        for index, item in enumerate(items):
            clothing = {tag.lower() for tag
                        in _split_tags(_json_text(item.get("initial_clothing")))}
            appearance = {tag.lower() for tag
                          in _split_tags(_json_text(item.get("appearance")))}
            score = 3 * len(clothing & existing_clothing)
            score += 2 * len(appearance & existing_appearance)
            scored.append((score, index))
        best_score, best_index = max(scored, default=(0, 0))
        if best_score:
            items = [items[best_index]] + [
                item for index, item in enumerate(items) if index != best_index]
    for item in items:
        name = _json_text(item.get("name"))
        gender = _infer_gender(_json_text(item.get("gender")), name)
        appearance = _clean_appearance(_split_tags(_json_text(item.get("appearance"))))
        clothing = _split_tags(_json_text(item.get("initial_clothing")))
        if not name and not appearance and not clothing:
            continue
        existing = _find_character(profiles, name, gender)
        if existing:
            if appearance and not strip_appearance:
                if not existing.appearance:
                    existing.appearance = appearance
                else:
                    seen = {tag.lower() for tag in existing.appearance}
                    for tag in appearance:
                        if (tag.lower() not in seen
                                and not _appearance_conflicts(tag, [existing])):
                            existing.appearance.append(tag)
                            seen.add(tag.lower())
            if clothing and not existing.initial_clothing:
                existing.initial_clothing = clothing
            if existing.gender == "other" and gender != "other":
                existing.gender = gender
            continue
        profiles.append(CharacterProfile(
            key="char_%02d" % (len(profiles) + 1),
            name=name or "character_%02d" % (len(profiles) + 1),
            gender=gender,
            appearance=appearance,
            initial_clothing=clothing,
        ))
    if not profiles:
        profiles.append(CharacterProfile(key="char_01", name="main"))
    return profiles


def character_bible_text(profiles: list[CharacterProfile]) -> str:
    lines = ["角色锁定表（全片硬约束，任何一镜都不得改变）："]
    for profile in profiles:
        lines.append(
            "- %s（%s）：appearance=%s；initial_clothing=%s" % (
                profile.name or profile.key, profile.gender,
                ", ".join(profile.appearance) or "未指定",
                ", ".join(profile.initial_clothing) or "未指定"))
    lines.append(
        "规则：每个出场角色的发色、发型、瞳色、体型、标志物必须与锁定表逐字一致；"
        "男性和女性都适用。每个角色的服装和裸露状态独立连续，脱掉后不得复穿，"
        "不得凭空增加锁定表之外的衣物；没有出现的角色不得写进当前画面。"
        "男主/男性/我只要出现在画面中，就必须保持同一外貌、同一初始服装和同一裸露进度。")
    return "\n".join(lines)


def _profile_mentioned(beat: str, profile: CharacterProfile) -> bool:
    text = str(beat or "")
    name = profile.name.strip()
    if name and name.lower() in text.lower():
        return True
    if profile.gender == "boy":
        return bool(re.search(
            r"男主|男角色|男性|男孩|男人|少年|青年|1boy|\bboy\b|\bmale\b|"
            r"\bman\b|\bmen\b|\bhe\b|\bhim\b|\bhis\b|(^|[^其])他|"
            r"(?:^|[\s,，;；])男(?:$|[\s,，;；])", text, re.I))
    if profile.gender == "girl":
        return bool(re.search(
            r"女主|女角色|女性|女孩|女人|少女|1girl|\bgirl\b|\bfemale\b|"
            r"\bwoman\b|\bwomen\b|\bshe\b|\bher\b|\bhers\b|她|"
            r"(?:^|[\s,，;；])女(?:$|[\s,，;；])", text, re.I))
    return False


def _nude_targets(beat: str, profiles: list[CharacterProfile],
                  fallback: list[CharacterProfile] | None = None
                  ) -> list[CharacterProfile]:
    clauses = re.split(r"[，,。；;！!？?\n]+", str(beat or ""))
    allowed = fallback if fallback is not None else profiles
    targets: list[CharacterProfile] = []
    last_mentioned: list[CharacterProfile] = []
    for clause in clauses:
        raw_mentioned = [profile for profile in profiles
                         if _profile_mentioned(clause, profile)]
        mentioned = [profile for profile in raw_mentioned if profile in allowed]
        if raw_mentioned and not mentioned:
            continue
        if not _is_full_nude(clause):
            if mentioned:
                last_mentioned = mentioned
            continue
        if mentioned:
            last_mentioned = mentioned
            targets.extend(mentioned)
        elif last_mentioned:
            targets.extend(last_mentioned)
        else:
            targets.extend(fallback or profiles)
    unique: list[CharacterProfile] = []
    for profile in targets:
        if profile not in unique:
            unique.append(profile)
    return unique


def _only_targets(beat: str, profiles: list[CharacterProfile],
                  fallback: list[CharacterProfile] | None = None
                  ) -> dict[str, str]:
    assignments: dict[str, str] = {}
    last_mentioned: list[CharacterProfile] = []
    allowed = fallback if fallback is not None else profiles
    for clause in re.split(r"[，,。；;！!？?\n]+", str(beat or "")):
        raw_mentioned = [profile for profile in profiles
                         if _profile_mentioned(clause, profile)]
        mentioned = [profile for profile in raw_mentioned if profile in allowed]
        if raw_mentioned and not mentioned:
            continue
        match = re.search(
            r"(?:只剩|仅剩|只穿|仅穿|只留|only wearing|wearing only|only in|"
            r"nothing but|clad only in)\s*(.*)",
            clause, re.I)
        if match:
            targets = mentioned or last_mentioned or fallback or profiles
            for profile in targets:
                assignments.setdefault(profile.key, match.group(1))
            last_mentioned = targets
        elif mentioned:
            last_mentioned = mentioned
    return assignments


def character_states_for_beats(profiles: list[CharacterProfile], beats: list[str],
                               initial_states: dict[str, set[str]] | None = None,
                               presence: list[list[CharacterProfile]] | None = None
                               ) -> list[dict[str, set[str]]]:
    carried = initial_states or {}
    current = {
        profile.key: set(carried[profile.key])
        if profile.key in carried else set(profile.initial_clothing)
        for profile in profiles
    }
    removed = {
        profile.key: set(profile.initial_clothing) - set(current[profile.key])
        for profile in profiles
    }
    states: list[dict[str, set[str]]] = []
    for beat_index, beat in enumerate(beats):
        present = (presence[beat_index]
                   if presence and beat_index < len(presence) else list(profiles))
        all_mentioned = [profile for profile in profiles
                         if _profile_mentioned(beat, profile)]
        targets = [profile for profile in all_mentioned if profile in present]
        if not all_mentioned:
            targets = list(present)
        if all_mentioned and not targets:
            states.append({key: set(tags) for key, tags in current.items()})
            continue
        nude_targets = _nude_targets(beat, profiles, present)
        only_targets = _only_targets(beat, profiles, present)
        for profile in targets:
            key = profile.key
            if profile in nude_targets:
                accessories = {tag for tag in profile.initial_clothing
                               if _is_accessory(tag) and tag not in removed[key]}
                current[key] = set(accessories)
                removed[key].update(tag for tag in profile.initial_clothing
                                    if not _is_accessory(tag))
            elif key in only_targets:
                chosen = {tag for tag in profile.initial_clothing
                          if _is_accessory(tag) and tag not in removed[key]}
                only_text = only_targets[key]
                for tag in profile.initial_clothing:
                    if tag not in removed[key] and tag.lower() in only_text.lower():
                        chosen.add(tag)
                        continue
                    clothing_key = _clothing_key(tag)
                    if (clothing_key and tag not in removed[key]
                            and any(re.search(pattern, only_text, re.I)
                                    for pattern in dict(_CLOTHING_KEYS).get(clothing_key, ()))):
                        chosen.add(tag)
                for tag in list(current[key]):
                    if not _is_accessory(tag) and tag not in chosen:
                        removed[key].add(tag)
                current[key] = chosen
            else:
                one_side = bool(re.search(
                    r"一半|单边|一只|另一边|另一只|一侧|one side|one of", beat, re.I))
                clauses = re.split(r"[，,。；;！!？?\n]+", beat)
                for tag in profile.initial_clothing:
                    clothing_key = _clothing_key(tag)
                    if tag in removed[key]:
                        continue
                    should_remove = False
                    for clause in clauses:
                        if not (_removes_item(clause, clothing_key)
                                or _removes_tag(clause, tag)):
                            continue
                        raw_mentioned = [item for item in profiles
                                         if _profile_mentioned(clause, item)]
                        mentioned = [item for item in raw_mentioned
                                     if item in present]
                        if raw_mentioned and not mentioned:
                            continue
                        if mentioned and profile not in mentioned:
                            continue
                        if not mentioned and profile not in present:
                            continue
                        should_remove = True
                        break
                    if should_remove:
                        if one_side and clothing_key in ("pantyhose", "heels"):
                            continue
                        current[key].discard(tag)
                        removed[key].add(tag)
        states.append({key: set(tags) for key, tags in current.items()})
    return states


def _shot_character_states(shot: dict[str, Any] | None,
                           profiles: list[CharacterProfile]) -> dict[str, set[str]]:
    raw = (shot or {}).get("character_states")
    if isinstance(raw, dict):
        states: dict[str, set[str]] = {}
        for profile in profiles:
            if profile.key not in raw:
                states[profile.key] = set(profile.initial_clothing)
                continue
            value = raw.get(profile.key)
            if isinstance(value, (list, tuple, set)):
                states[profile.key] = {str(tag).strip() for tag in value
                                       if str(tag).strip()}
            elif str(value or "").strip():
                states[profile.key] = {tag.strip() for tag
                                       in str(value).split(",") if tag.strip()}
            else:
                states[profile.key] = set()
        return states
    return {profile.key: set(profile.initial_clothing) for profile in profiles}


def _shot_state_index(shot: dict[str, Any], outline: list[dict[str, Any]],
                      fallback: int) -> int:
    shot_id = str(shot.get("id") or "").strip()
    if shot_id:
        for index, item in enumerate(outline):
            if str(item.get("id") or "").strip() == shot_id:
                return index
    return fallback


def present_character_profiles(profiles: list[CharacterProfile], shot: dict[str, Any],
                               beat: str = "") -> list[CharacterProfile]:
    cast = str((shot or {}).get("cast") or "")
    text = " ".join([beat, str((shot or {}).get("outline") or ""),
                     str((shot or {}).get("script") or "")])
    mentioned = [profile for profile in profiles if _profile_mentioned(text, profile)]
    girl_count = sum(int(value) for value in
                     re.findall(r"(\d+)\s*(?:girl|woman|female)s?", cast, re.I))
    boy_count = sum(int(value) for value in
                    re.findall(r"(\d+)\s*(?:boy|man|male)s?", cast, re.I))
    chosen: list[CharacterProfile] = []
    if girl_count:
        chosen.extend([profile for profile in profiles
                       if profile.gender == "girl" and profile in mentioned][:girl_count])
        if len(chosen) < girl_count:
            chosen.extend([profile for profile in profiles
                           if profile.gender == "girl" and profile not in chosen
                           ][:girl_count - len(chosen)])
    if boy_count:
        chosen.extend([profile for profile in profiles
                       if profile.gender == "boy" and profile in mentioned][:boy_count])
        if len([profile for profile in chosen if profile.gender == "boy"]) < boy_count:
            chosen.extend([profile for profile in profiles
                           if profile.gender == "boy" and profile not in chosen
                           ][:boy_count - len([item for item in chosen
                                               if item.gender == "boy"])])
    if chosen:
        return chosen
    if mentioned:
        return mentioned
    if re.search(r"\bsolo\b", cast, re.I) and profiles:
        return profiles[:1]
    return profiles


def _appearance_words(tag: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z-]*", str(tag).lower()))


def _appearance_colors(tag: str) -> set[str]:
    return _appearance_words(tag) & _APPEARANCE_COLORS


def _appearance_styles(tag: str) -> set[str]:
    return _appearance_words(tag) & _HAIR_STYLES


def _locked_appearance(profile: CharacterProfile,
                       kind: str) -> tuple[set[str], set[str]]:
    colors: set[str] = set()
    styles: set[str] = set()
    pattern = r"\beyes?\b" if kind == "eyes" else r"\bhair\b"
    for tag in profile.appearance:
        if not re.search(pattern, tag, re.I):
            continue
        colors.update(_appearance_colors(tag))
        if kind == "hair":
            styles.update(_appearance_styles(tag))
    return colors, styles


_FULL_NUDE_RE = re.compile(
    r"^(?:completely nude|fully nude|full nude|completely naked|fully naked|"
    r"full naked|nude|naked)$", re.I)


def _is_fully_nude(profile: CharacterProfile, states: dict[str, set[str]]) -> bool:
    worn = states.get(profile.key) or set()
    if not profile.initial_clothing:
        return False
    return all(_is_accessory(tag) for tag in worn)


def _appearance_conflicts(tag: str, present: list[CharacterProfile]) -> bool:
    low = str(tag or "").lower()
    if (low.strip() == "black eye" or _clothing_key(tag)
            or "hairclip" in low or "hair ornament" in low
            or "hair bow" in low or "hair ribbon" in low or "pubic hair" in low):
        return False
    for kind, pattern in (("hair", r"\bhair\b"), ("eyes", r"\beyes?\b")):
        if not re.search(pattern, low, re.I):
            continue
        tag_colors = _appearance_colors(low)
        tag_styles = _appearance_styles(low) if kind == "hair" else set()
        locked_colors = [_locked_appearance(profile, kind)[0] for profile in present]
        locked_colors = [colors for colors in locked_colors if colors]
        if tag_colors and locked_colors:
            if not any(tag_colors & colors for colors in locked_colors):
                return True
        if kind == "hair" and tag_styles:
            locked_styles = [_locked_appearance(profile, kind)[1]
                             for profile in present]
            locked_styles = [styles for styles in locked_styles if styles]
            if locked_styles and not any(tag_styles & styles
                                         for styles in locked_styles):
                return True
    return False


def apply_character_state(prompt: str, profiles: list[CharacterProfile],
                          states: dict[str, set[str]],
                          present: list[CharacterProfile] | None = None) -> str:
    present = present or profiles
    worn: set[str] = set()
    for profile in present:
        worn.update(states.get(profile.key) or set())
    wardrobe = {tag for profile in profiles for tag in profile.initial_clothing}
    tags = [tag.strip() for tag in apply_story_state(prompt, worn, wardrobe).split(",")
            if tag.strip()]
    tags = [tag for tag in tags if not _appearance_conflicts(tag, present)]
    nude_flags = [_is_fully_nude(profile, states) for profile in present]
    if nude_flags and any(nude_flags) and not all(nude_flags):
        tags = [tag for tag in tags if not _FULL_NUDE_RE.match(tag)]
    elif nude_flags and all(nude_flags):
        if not any(_FULL_NUDE_RE.match(tag) for tag in tags):
            tags.append("completely nude")
    seen = {tag.lower() for tag in tags}
    for profile in present:
        for tag in profile.appearance:
            key = tag.lower()
            if key and key not in seen:
                seen.add(key)
                tags.append(tag)
    return ", ".join(tags)


def _scene_for_beat(beat: str) -> list[str] | None:
    for key, pattern in _SCENE_PATTERNS:
        if re.search(pattern, beat, re.I):
            return list(_SCENE_TAGS[key])
    return None


def scene_states_for_beats(beats: list[str],
                           initial_scene: list[str] | None = None) -> list[list[str]]:
    current = list(initial_scene) if initial_scene else list(_SCENE_TAGS["room"])
    states: list[list[str]] = []
    for beat in beats:
        found = _scene_for_beat(beat)
        if found:
            current = found
        states.append(list(current))
    return states


_CLOTHING_DAMAGE_WORDS = (
    "torn", "ripped", "broken", "damaged", "panties aside",
    "clothes at waist", "pulled down", "pulled aside", "at knees",
    "off shoulder", "unbuttoned", "open shirt", "open clothes",
    "open jacket", "open robe", "half-off", "half off", "slid down",
    "partially removed",
)


def _is_clothing_state_tag(tag: str) -> bool:
    low = str(tag or "").lower()
    return any(word in low for word in _CLOTHING_DAMAGE_WORDS)


def apply_story_state(prompt: str, worn: set[str],
                      wardrobe: set[str] | None = None) -> str:
    tags = [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()]
    worn_keys = {_clothing_key(tag) for tag in worn if _clothing_key(tag)}
    worn_lowers = {tag.lower() for tag in worn}
    wardrobe_lowers = {tag.lower() for tag in (wardrobe or ())}
    has_clothing = any(not _is_accessory(tag) for tag in worn)
    kept: list[str] = []
    for tag in tags:
        clothing_key = _clothing_key(tag)
        in_wardrobe = tag.lower() in wardrobe_lowers
        if not clothing_key and not in_wardrobe:
            if not _is_clothing_state_tag(tag) or has_clothing:
                kept.append(tag)
            continue
        if _is_clothing_state_tag(tag):
            if clothing_key in worn_keys or tag.lower() in worn_lowers:
                kept.append(tag)
    tags = kept
    clothing = sorted(worn)
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags + clothing:
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return ", ".join(result)


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
        cast = forced_cast or hinted
        outline.append({"id": number, "name": name, "cast": cast, "outline": text})
    if not outline:
        raise ValueError("Model returned no usable outline.")
    return outline


def build_outline_messages(premise: str, shots: int, setting: str,
                           prior: list[dict[str, str]], total: int,
                           start: int, strip_appearance: bool = False,
                           spine: dict[str, Any] | None = None,
                           act_summary: str = "",
                           story_state: str = "",
                           character_bible: str = "") -> list[dict[str, str]]:
    user = [
        "剧情：%s" % premise,
        "本次大纲：第 %d-%d 镜，共 %d 镜" % (start, start + shots - 1, total),
    ]
    if character_bible:
        user.append(character_bible)
    if act_summary:
        user.append("本幕硬性大纲：只写本幕，不写前面或下一幕。%s" % act_summary)
    if story_state:
        user.append(story_state)
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
    if strip_appearance:
        user.append("已启用角色 LoRA：对使用 LoRA 的角色，不要生成或补充角色外貌和身体特征"
                    "（发色、瞳色、发型、脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责；"
                    "没有 LoRA 的角色必须保留锁定表里的固定外貌。")
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
                            spine: list[dict[str, Any]] | None = None,
                            act_summary: str = "", story_state: str = "",
                            character_bible: str = "",
                            start_shot: int = 1,
                            total_shots: int | None = None) -> list[dict[str, str]]:
    outline: list[dict[str, str]] = []
    used_names: list[str] = []
    total = int(total_shots or shots)
    if spine:
        for entry in spine:
            entry_end = min(shots, int(entry.get("end", shots)))
            while len(outline) < entry_end:
                need = min(chunk, entry_end - len(outline))
                start = start_shot + len(outline)
                raw = client.chat_json(
                    model,
                    build_outline_messages(premise, need, setting, outline, total, start,
                                           strip_appearance=strip_appearance, spine=entry,
                                           act_summary=act_summary, story_state=story_state,
                                           character_bible=character_bible),
                    schema=OUTLINE_SCHEMA,
                    temperature=0.6,
                    num_predict=max(4096, min(8192, need * 1200)),
                    num_ctx=32768,
                    keep_alive="5m",
                    timeout=timeout,
                    retries=2,
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
            start = start_shot + len(outline)
            raw = client.chat_json(
                model,
                build_outline_messages(premise, need, setting, outline, total, start,
                                       strip_appearance=strip_appearance,
                                       act_summary=act_summary, story_state=story_state,
                                       character_bible=character_bible),
                schema=OUTLINE_SCHEMA,
                temperature=0.6,
                num_predict=max(4096, min(8192, need * 1200)),
                num_ctx=32768,
                keep_alive="5m",
                timeout=timeout,
                retries=2,
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


def build_story_messages(premise: str, total: int,
                         setting: str = "") -> list[dict[str, str]]:
    user = ["用户剧情：\n%s" % premise, "目标总格数：%d" % total]
    if setting.strip():
        user.append("固定场景/附加要求：%s" % setting.strip())
    user.append("请先写完整剧情，不要分镜编号，不要英文标签。")
    return [
        {"role": "system", "content": STORY_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def build_act_plan_messages(story: str, premise: str, total: int,
                            setting: str = "") -> list[dict[str, str]]:
    acts = max(1, (total + MAX_ACT_SHOTS - 1) // MAX_ACT_SHOTS)
    user = [
        "完整剧情：\n%s" % story,
        "用户设定：\n%s" % premise,
        "总格数：%d；请拆成 %d 幕，每幕最多 %d 格。" % (
            total, acts, MAX_ACT_SHOTS),
    ]
    if setting.strip():
        user.append("固定场景/附加要求：%s" % setting.strip())
    return [
        {"role": "system", "content": ACT_PLAN_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]


def normalize_acts(raw: dict[str, Any] | list[Any], total: int,
                   story: str) -> list[dict[str, Any]]:
    items = raw.get("acts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []
    expected = max(1, (total + MAX_ACT_SHOTS - 1) // MAX_ACT_SHOTS)
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not summary:
            continue
        cleaned.append({
            "title": str(item.get("title") or "第%d幕" % (index + 1)).strip(),
            "summary": summary,
            "cast": str(item.get("cast") or "").strip(),
            "clothing": str(item.get("clothing") or "").strip(),
            "scene": str(item.get("scene") or "").strip(),
            "nsfw": str(item.get("nsfw") or "").strip(),
        })
    if len(cleaned) < expected:
        clauses = _split_story_clauses(story) or [story]
        size = max(1, (len(clauses) + expected - 1) // expected)
        fallback = ["，".join(clauses[index:index + size])
                    for index in range(0, len(clauses), size)]
        for index in range(len(cleaned), expected):
            summary = fallback[index] if index < len(fallback) else cleaned[-1]["summary"]
            cleaned.append({
                "title": "第%d幕" % (index + 1), "summary": summary,
                "cast": "", "clothing": "", "scene": "", "nsfw": "",
            })
    if len(cleaned) > expected:
        merged = cleaned[:expected - 1]
        merged.append({
            "title": cleaned[expected - 1]["title"],
            "summary": "；".join(item["summary"] for item in cleaned[expected - 1:]),
            "cast": cleaned[-1]["cast"], "clothing": cleaned[-1]["clothing"],
            "scene": cleaned[-1]["scene"], "nsfw": cleaned[-1]["nsfw"],
        })
        cleaned = merged
    for index, item in enumerate(cleaned):
        item["id"] = "%02d" % (index + 1)
        item["start"] = index * MAX_ACT_SHOTS + 1
        item["end"] = min(total, (index + 1) * MAX_ACT_SHOTS)
    return cleaned


def generate_full_story_pipeline(client: OllamaClient, premise: str,
                                 options: StoryboardOptions,
                                 initial: list[dict[str, str]],
                                 shots: int) -> list[dict[str, str]]:
    log = options.log
    log("Stage 1/4: writing complete story...")
    story_raw = client.chat_json(
        options.model,
        build_story_messages(premise, shots, options.setting),
        schema=STORY_SCHEMA, temperature=options.temperature,
        num_predict=16384, num_ctx=32768, keep_alive=options.keep_alive,
        timeout=max(options.timeout, 600.0), retries=2,
    )
    story = str(story_raw.get("story") or "").strip()
    if not story:
        raise ValueError("Model returned an empty complete story.")
    profiles = normalize_character_profiles(
        story_raw.get("characters"), premise, options.strip_appearance)
    bible = character_bible_text(profiles)
    log("Character lock: " + " | ".join(
        "%s(%s): %s" % (profile.name, profile.gender,
                        ", ".join(profile.initial_clothing) or "no clothing")
        for profile in profiles))
    log("Stage 2/4: splitting story into acts...")
    act_raw = client.chat_json(
        options.model,
        build_act_plan_messages(story, premise, shots, options.setting),
        schema=ACT_PLAN_SCHEMA, temperature=options.temperature,
        num_predict=8192, num_ctx=32768, keep_alive=options.keep_alive,
        timeout=max(options.timeout, 600.0), retries=2,
    )
    acts = normalize_acts(act_raw, shots, story)
    if not acts:
        raise ValueError("Model produced no usable act plan.")
    result = list(initial[:shots])
    act_premise = premise + "\n\n完整剧情：\n" + story
    for act_index, act in enumerate(acts, 1):
        if len(result) >= shots:
            break
        start = int(act["start"])
        end = int(act["end"])
        if start <= len(result):
            start = len(result) + 1
        act_size = max(1, end - start + 1)
        state = _global_story_state(premise, result, profiles)
        log("Stage 3/4: refining Act %d/%d, shots %d-%d..." % (
            act_index, len(acts), start, end))
        outline = plan_storyboard_outline(
            client, options.model, act_premise, act_size, options.setting,
            chunk=6, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance,
            character_bible=bible,
            act_summary="%s；%s；服装：%s；场景：%s；NSFW：%s" % (
                act["title"], act["summary"], act["clothing"],
                act["scene"], act["nsfw"]),
            story_state=state, start_shot=start, total_shots=shots,
        )
        beats = [item["outline"] for item in outline]
        carried = _shot_character_states(result[-1], profiles) if result else None
        beat_presence = [
            present_character_profiles(profiles, {"cast": item.get("cast", "")}, beat)
            for item, beat in zip(outline, beats)]
        character_states = character_states_for_beats(
            profiles, beats, carried, beat_presence)
        scene_states = scene_states_for_beats(beats)
        for offset in range(0, len(outline), options.chunk):
            chunk_outline = outline[offset:offset + options.chunk]
            scripts = [{
                "id": item["id"], "name": item["name"],
                "script": item["outline"], "cast": item.get("cast", ""),
            } for item in chunk_outline]
            tag_raw = client.chat_json(
                options.model,
                build_tag_messages(
                    scripts, options.style_positive, options.setting,
                    strip_appearance=options.strip_appearance,
                    cast_hint=str(scripts[0].get("cast") or ""),
                    story_state=state, character_bible=bible),
                schema=TAG_SCHEMA, temperature=options.temperature,
                num_predict=8192, num_ctx=32768, keep_alive=options.keep_alive,
                timeout=options.timeout, retries=3,
            )
            part = normalize_tagged(tag_raw, scripts)
            for index, shot in enumerate(part):
                state_index = _shot_state_index(shot, outline, offset + index)
                if state_index < len(character_states):
                    states = character_states[state_index]
                    beat = beats[state_index] if state_index < len(beats) else ""
                    present = present_character_profiles(profiles, shot, beat)
                    shot["prompt"] = apply_character_state(
                        shot["prompt"], profiles, states, present)
                    worn = set()
                    for profile in present:
                        worn.update(states.get(profile.key) or set())
                    shot["clothing"] = ", ".join(sorted(worn))
                    shot["characters"] = ", ".join(
                        profile.name for profile in present)
                    shot["character_states"] = {
                        profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                        for profile in profiles}
                if state_index < len(scene_states):
                    shot["scene"] = ", ".join(scene_states[state_index])
            result.extend(part)
            _notify_partial(options, result)
            log("Stage 4/4: Act %d +%d shots (%d/%d)" % (
                act_index, len(part), len(result), shots))
            if not part:
                break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    return result[:shots]


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
        prompt = raw_prompt(item.get("prompt") or item.get("tags") or "")
        if not prompt:
            continue
        shots.append({
            "id": script["id"],
            "name": script["name"],
            "prompt": prompt,
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
                           phase: str = "", cast_hint: str = "",
                           story_state: str = "", act_summary: str = "",
                           character_bible: str = "") -> list[dict[str, str]]:
    start = len(prior) + 1
    user = [
        "剧情：%s" % premise,
        "本次生成镜头数：%d%s" % (
            shots, ("（第 %d-%d 镜，共 %d 镜）" %
                    (start, start + shots - 1, total) if total else "")),
    ]
    if character_bible:
        user.append(character_bible)
    if act_summary:
        user.append("本幕硬性大纲：%s" % act_summary)
    if story_state:
        user.append(story_state)
    if strip_appearance:
        user.append("已启用角色 LoRA：对使用 LoRA 的角色，不要生成或补充角色外貌和身体特征"
                    "（发色、瞳色、发型、脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责；"
                    "没有 LoRA 的角色必须保留锁定表里的固定外貌。")
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
                       phase: str = "", cast_hint: str = "",
                       story_state: str = "", character_bible: str = "") -> list[dict[str, str]]:
    user = []
    if character_bible:
        user.append(character_bible)
    if story_state:
        user.append(story_state)
    if strip_appearance:
        user.append("已启用角色 LoRA：对使用 LoRA 的角色，不要输出角色外貌和身体特征"
                    "（发色、瞳色、发型、脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责；"
                    "没有 LoRA 的角色必须保留锁定表里的固定外貌。")
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


MAX_ACT_SHOTS = 30


def _notify_partial(options: StoryboardOptions,
                    shots: list[dict[str, str]]) -> None:
    if options.on_partial is None:
        return
    try:
        options.on_partial([dict(shot) for shot in shots])
    except Exception as exc:
        options.log("Checkpoint save failed: %s" % exc)


def _shot_clothing(shot: dict[str, Any] | None) -> list[str]:
    if not shot:
        return []
    return [tag.strip() for tag in str(shot.get("clothing") or "").split(",")
            if tag.strip()]


def _shot_scene(shot: dict[str, Any] | None) -> list[str]:
    if not shot:
        return []
    return [tag.strip() for tag in str(shot.get("scene") or "").split(",")
            if tag.strip()]


def _generate_long_storyboard(client: OllamaClient, premise: str,
                              options: StoryboardOptions,
                              initial: list[dict[str, str]],
                              shots: int) -> list[dict[str, str]]:
    log = options.log
    result: list[dict[str, str]] = initial[:shots]
    profiles = parse_character_profiles(premise)
    bible = character_bible_text(profiles)
    spine = build_story_spine(premise, shots)
    act_total = (shots + MAX_ACT_SHOTS - 1) // MAX_ACT_SHOTS
    act_index = 0
    while len(result) < shots:
        act_index += 1
        act_start = len(result) + 1
        act_size = min(MAX_ACT_SHOTS, shots - len(result))
        act_end = act_start + act_size - 1
        act_summary = _act_summary(spine, act_start, act_end)
        story_state = _global_story_state(premise, result, profiles)
        log("Act %d/%d: shots %d-%d (max %d per act)" % (
            act_index, act_total, act_start, act_end, MAX_ACT_SHOTS))
        outline = plan_storyboard_outline(
            client, options.model, premise, act_size, options.setting,
            chunk=3, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance,
            act_summary=act_summary, story_state=story_state,
            character_bible=bible,
            start_shot=act_start, total_shots=shots)
        for item in outline:
            try:
                number = int(item.get("id", "0"))
            except (TypeError, ValueError):
                continue
            phase = _phase_at(spine, number)
            item["phase"] = str(phase.get("phase") or "")
            if phase.get("cast"):
                item["cast"] = str(phase["cast"])
        story_beats = [item["outline"] for item in outline]
        last_shot = result[-1] if result else None
        carried = _shot_character_states(last_shot, profiles) if last_shot else None
        beat_presence = [
            present_character_profiles(profiles, {"cast": item.get("cast", "")}, beat)
            for item, beat in zip(outline, story_beats)]
        character_states = character_states_for_beats(
            profiles, story_beats, carried, beat_presence)
        scene_states = scene_states_for_beats(
            story_beats, initial_scene=_shot_scene(last_shot) or None)
        chunks: list[tuple[int, list[dict[str, str]]]] = []
        offset = 0
        while offset < len(outline):
            phase = outline[offset].get("phase", "")
            end = offset + 1
            while (end < len(outline) and end - offset < options.chunk
                   and outline[end].get("phase", "") == phase):
                end += 1
            chunks.append((offset, outline[offset:end]))
            offset = end
        for offset, outline_chunk in chunks:
            beat_slice = [item["outline"] for item in outline_chunk]
            script_raw = client.chat_json(
                options.model,
                build_script_messages(
                    premise, len(outline_chunk), options.setting,
                    result, shots, beat_slice,
                    strip_appearance=options.strip_appearance,
                    phase=str(outline_chunk[0].get("phase") or ""),
                    cast_hint=str(outline_chunk[0].get("cast") or ""),
                    story_state=story_state, act_summary=act_summary,
                    character_bible=bible),
                schema=SCRIPT_SCHEMA,
                temperature=options.temperature,
                num_predict=16384,
                num_ctx=32768,
                keep_alive=options.keep_alive,
                timeout=options.timeout,
                retries=3,
            )
            script_chunk = normalize_scripts(
                script_raw, len(outline_chunk), slugify(premise, "story") or "story",
                start=act_start + offset,
                used_names=[shot["name"] for shot in result])
            for index, script in enumerate(script_chunk):
                if index < len(outline_chunk):
                    script["cast"] = outline_chunk[index]["cast"]
                    script["outline"] = outline_chunk[index]["outline"]
                    script["phase"] = outline_chunk[index].get("phase", "")
            tag_raw = client.chat_json(
                options.model,
                build_tag_messages(
                    script_chunk, options.style_positive, options.setting,
                    strip_appearance=options.strip_appearance,
                    phase=str(script_chunk[0].get("phase") or ""),
                    cast_hint=str(script_chunk[0].get("cast") or ""),
                    story_state=story_state, character_bible=bible),
                schema=TAG_SCHEMA,
                temperature=options.temperature,
                num_predict=16384,
                num_ctx=32768,
                keep_alive=options.keep_alive,
                timeout=options.timeout,
                retries=3,
            )
            part = normalize_tagged(tag_raw, script_chunk)
            for index, shot in enumerate(part):
                state_index = _shot_state_index(shot, outline, offset + index)
                beat = (story_beats[state_index]
                        if state_index < len(story_beats) else "")
                if (beat and state_index < len(character_states)
                        and state_index < len(scene_states)):
                    states = character_states[state_index]
                    present = present_character_profiles(profiles, shot, beat)
                    shot["prompt"] = apply_character_state(
                        shot["prompt"], profiles, states, present)
                    worn = set()
                    for profile in present:
                        worn.update(states.get(profile.key) or set())
                    shot["clothing"] = ", ".join(sorted(worn))
                    shot["characters"] = ", ".join(
                        profile.name for profile in present)
                    shot["character_states"] = {
                        profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                        for profile in profiles}
                    shot["scene"] = ", ".join(scene_states[state_index])
            result.extend(part)
            _notify_partial(options, result)
            log("Act %d: +%d shots (%d/%d)" % (act_index, len(part), len(result), shots))
            if not part:
                break
        if len(result) >= shots:
            break
    return result[:shots]


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
    if options.full_story and not extract_premise_beats(premise):
        return generate_full_story_pipeline(client, premise, options, result, shots)
    if shots > MAX_ACT_SHOTS:
        return _generate_long_storyboard(client, premise, options, result, shots)

    profiles = parse_character_profiles(premise)
    bible = character_bible_text(profiles)
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
                "cast": "",
                "outline": beat,
                "phase": "",
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
            strip_appearance=options.strip_appearance, spine=spine or None,
            character_bible=bible)
    if not outline:
        raise ValueError("Model produced no usable storyboard outline.")
    story_beats = [item["outline"] for item in outline]
    carried = _shot_character_states(result[-1], profiles) if result else None
    beat_presence = [
        present_character_profiles(profiles, {"cast": item.get("cast", "")}, beat)
        for item, beat in zip(outline, story_beats)]
    character_states = character_states_for_beats(
        profiles, story_beats, carried, beat_presence)
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
                cast_hint=str(outline_chunk[0].get("cast") or ""),
                character_bible=bible),
            schema=SCRIPT_SCHEMA,
            temperature=options.temperature,
            num_predict=16384,
            num_ctx=32768,
            keep_alive=options.keep_alive,
            timeout=options.timeout,
            retries=3,
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
                cast_hint=str(script_chunk[0].get("cast") or ""),
                character_bible=bible),
            schema=TAG_SCHEMA,
            temperature=options.temperature,
            num_predict=16384,
            num_ctx=32768,
            keep_alive=options.keep_alive,
            timeout=options.timeout,
            retries=3,
        )
        part = normalize_tagged(tag_raw, script_chunk)
        state_offset = len(result)
        for index, shot in enumerate(part):
            state_index = _shot_state_index(shot, outline, state_offset + index)
            beat = (story_beats[state_index]
                    if state_index < len(story_beats) else "")
            if (beat and state_index < len(character_states)
                    and state_index < len(scene_states)):
                states = character_states[state_index]
                present = present_character_profiles(profiles, shot, beat)
                shot["prompt"] = apply_character_state(
                    shot["prompt"], profiles, states, present)
                worn = set()
                for profile in present:
                    worn.update(states.get(profile.key) or set())
                shot["clothing"] = ", ".join(sorted(worn))
                shot["characters"] = ", ".join(
                    profile.name for profile in present)
                shot["character_states"] = {
                    profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                    for profile in profiles}
                shot["scene"] = ", ".join(scene_states[state_index])
        result.extend(part)
        _notify_partial(options, result)
        log("Stage B: +%d shots (%d/%d)" % (len(part), len(result), shots))
        if not part:
            break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    return result[:shots]
