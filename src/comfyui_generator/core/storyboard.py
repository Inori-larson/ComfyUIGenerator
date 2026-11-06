"""Ollama storyboard generation: premise -> continuous shot list."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.ai_review import (
    ensure_clothing_gate, run_all_reviews)
from comfyui_generator.core.mechanical import normalize_prompt_text
from comfyui_generator.core.trace import trace_event

PROMPT_CONVERSION_FLASH_MODEL = "deepseek-v4.1-flash"
GENERATION_MODEL = "deepseek-v4.1-flash"
REVIEW_MODEL = "deepseek-v4.1-flash"
def generation_model(_selected_model: str = "") -> str:
    return GENERATION_MODEL
def review_model(_selected_model: str = "") -> str:
    return REVIEW_MODEL
def prompt_conversion_model(_selected_model: str = "") -> str:
    return PROMPT_CONVERSION_FLASH_MODEL
PROMPT_COVERAGE = (
    "覆盖维度：角色身份与外观、服装/裸露状态、当前可见身体部位、姿势、动作、表情、"
    "场景/地点、镜头景别、机位/角度、构图、光线/时间、NSFW 状态。"
)
PRIORITY_RULES = (
    "统一优先级：用户明确要求 > 角色锁定与初始服装 > 已发生剧情/服装状态 > "
    "默认节奏与风格。发生冲突时，以优先级更高的一方为准。\n"
)
INTIMATE_CLOTHING_EVENTS_ZH = (
    "可选的服装破坏/半脱情色元素（按剧情选用，不要每镜都用，也不要无铺垫突然撕毁）："
    "只能对角色当前已有的服装做半脱、拨开、撕破、滑落或挂腿处理，禁止借机新增未设定服装；"
    "例如撕破连裤袜/丝袜/渔网袜/蕾丝袜的裆部、膝盖、大腿或胸口；"
    "把内裤拨到一边或半挂在腿侧；推下胸罩、解开肩带或让胸罩滑落；"
    "破损后衣物仍挂在身上，可隔着破洞抚摸、指交、口交、磨蹭或插入；"
    "事后破损衣物保持挂在腰/腿/手臂，边缘撕裂、潮湿，不要自动复原。"
)
CLOTHING_EVENTS_BRIEF = (
    "可选的服装破坏/半脱：撕破连裤袜/丝袜、拨开内裤、推下胸罩、"
    "破损衣物挂腿；只能用于角色已有服装，不要新增未设定服装，不要每镜都用。"
)
STORY_FLOW_RULES = (
    "用户明确要求的动作类型必须分别写成独立镜头；例如女主自慰、男主对女主口交、"
    "女主对男主口交、吞精，不能只完成其中一部分。"
    "自慰/独处阶段不能几镜就结束，男主不得提前出现。"
    "穿衣或整理衣物后，不得无时间跳跃、场景变化或新事件就再次脱衣；"
    "多轮性爱必须有明确的轮次过渡，不能循环前戏→性交→事后→再脱。"
    "用户没有明确要求新角色时，男主离开后不得再加入陌生男人重复口交或性爱；"
    "二次剧情必须有用户明确要求。"
    "用户没有明确要求第二轮时，第一次射精后不得再次完整重复"
    "口交→前戏→性交→射精；连续事后、整理、走路不得无新信息地堆叠，必须合并推进。"
    "镜头数多于可用剧情节点时，不要循环剧情或重复同一事件；"
    "应在同一场景内扩展当前动作的微节拍：开始、加深、失控、临界、余韵，"
    "以及程度、状态、身体细节、表情、体液和机位变化，用这些细分内容补足镜头。"
)
POSE_DIVERSITY_ZH = (
    "性行为段必须做体位和机位变化：至少安排 5-7 种不同姿势，不要连续重复。"
    "要主动设计能展示女主正面的姿势。"
)
INTIMATE_CLOTHING_EVENTS_TAGS = (
    "可用英文标签示例（只在 TAG 阶段使用，且必须绑定 script 中已有的具体单品）："
    "torn pantyhose, ripped pantyhose, pantyhose pulled down, pantyhose around thighs, "
    "torn panties, panties aside, panties around one leg, bra pull, bra hanging, "
    "broken bra, open shirt, torn shirt, clothes pull, half-off clothes, "
    "torn skirt, torn dress, torn leotard, torn bodysuit, crotchless, "
    "hole in clothes。不要输出无主语的 torn clothes / clothing damage。"
)
BOORU_WORKFLOW = (
    "先在心里拆解，不要把拆解过程写进结果：人数/cast、当前服装结果、姿势、动作、表情、"
    "NSFW、场景、光线、镜头。再严格按此顺序组装标签：cast → 服装/裸露 → 姿势 → 动作 → "
    "表情 → NSFW → 场景 → 光线 → 镜头。已经脱掉的服装标签必须删除。"
    "性行为段每镜换姿势和互动，禁止连续重复同一姿势。情趣服装保留不要全部脱掉，"
    "除非剧情明确要求全裸。适当增加色情细节。" +
    CLOTHING_EVENTS_BRIEF + INTIMATE_CLOTHING_EVENTS_TAGS +
    POSE_DIVERSITY_ZH +
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
                    "cast": {"type": "string"},
                    "present_characters": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "phase": {"type": "string"},
                    "beat": {"type": "string"},
                    "clothing": {"type": "string"},
                    "visible": {"type": "string"},
                    "pose": {"type": "string"},
                    "expression": {"type": "string"},
                    "scene": {"type": "string"},
                    "camera": {"type": "string"},
                    "lighting": {"type": "string"},
                    "nsfw": {"type": "string"},
                    "script": {"type": "string"},
                },
                "required": ["id", "cast", "script"],
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
                    "negative": {"type": "string"},
                    "focus": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["id", "prompt", "negative"],
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
                    "cast": {"type": "string"},
                    "present_characters": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "phase": {"type": "string"},
                    "beat": {"type": "string"},
                    "clothing": {"type": "string"},
                    "scene": {"type": "string"},
                    "camera": {"type": "string"},
                    "nsfw": {"type": "string"},
                    "outline": {"type": "string"},
                },
                "required": ["id", "cast", "outline"],
            },
        }
    },
    "required": ["shots"],
}
OUTLINE_SYSTEM = (
    PRIORITY_RULES +
    "你是二次元 NSFW 剧情大纲和分镜编剧。请按用户剧情生成完整编号分镜大纲，只写中文大纲，不写英文标签。\n"
    "成功标准：\n"
    "1. 按用户要求的总格数生成，id 从 01 连续编到最后一格，不能少、重、跳。\n"
    "2. 每条 outline 必须写清本镜独有剧情：谁出现、做了什么、服装/裸露变化、场景、镜头、光线、NSFW 状态；"
    "用户编号剧情是硬性 Story Contract，必须按顺序全部覆盖并提前分配镜头预算，"
    "女主口交和男主舔阴必须分别出现，不能漏掉或互相替代；"
    + CLOTHING_EVENTS_BRIEF +
    "禁止复制上一镜、禁止只写同一动作、禁止所有镜头重复。\n"
    "3. 大环境/地点/时间/光线必须全程连续；同一大环境内的自然元素、道具、植被、"
    "建筑、家具、天气、光线细节可按剧情自然扩展，不要只写空泛大环境，"
    "也不要每镜随机换一套细节；只有剧情明确移动才换大环境。\n"
    "4. 每个角色都必须遵守角色锁定表：外貌、初始服装、当前服装和裸露状态独立连续；"
    "禁止发明锁定表之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣等；禁止复穿已脱衣物，禁止跳步；"
    "脱衣必须写清是哪个角色、具体哪件初始服装；男主/男性/我脱衣或全裸时必须写清，不能影响女主状态。\n"
    "5. cast 必须写人物数量与性别：用户未明确要求男性时只能 1girl solo；"
    "明确要求双人时才写女主+男主 1girl 1boy；没有出现的角色不得写；"
    "用户明确说前半没有男主或某角色后段才出现时，必须严格遵守出场时机。"
    + STORY_FLOW_RULES + "\n"
    "6. 用户消息中的剧情进度账本、已完成镜头是硬事实；不得重写、重复或回退这些事件。"
    "按起承转合推进，不能从开头几镜后开始循环；每镜只能有一个主行为节拍，"
    "连续动作必须拆成多个镜头；插入后不得无过渡切回自慰、前戏或初遇；"
    "整理衣物或事后余韵后，不得无新事件又重新脱衣/自慰/前戏。\n"
    "7. 节奏循序渐进：前段只试探和轻微接触，中段自慰/勾引/前戏/慢脱，后段才插入；"
    "禁止无铺垫直接全裸或插入。性交中适当保留情趣服装（根据剧情需要调整），"
    "除非用户明确要求全裸；优先写半脱、拨开、撕破、挂腿。"
    + POSE_DIVERSITY_ZH +
    "男主和女主的服装状态必须分别写，男主不能穿女主衣服。\n"
    "outline 只写本镜新推进的剧情节点，不写完整画面；画面细节留给后续 script。\n"
    "每条请同时填写 phase、beat、clothing、scene、camera、nsfw，outline 写完整剧情节点。\n"
    "每条填写 present_characters 数组，只能写角色锁定表中实际出场的 name。\n"
    "只输出 JSON shots[{id,cast,present_characters,phase,beat,clothing,scene,camera,nsfw,outline}]，"
    "不要解释，不要英文标签。"
)
SCRIPT_SYSTEM = (
    PRIORITY_RULES +
    "你是二次元 NSFW 剧情大纲和分镜编剧。先只生成中文分镜脚本，不写英文标签。\n"
    "成功标准（必须全部满足，否则视为失败）：\n"
    "1. 大环境（如果用户有指定则受本条限制，没指定可不受本条限制）：剧情指定的"
    "地点/大环境、时间、光线方向必须连续；同一大环境内的自然元素、道具、植被、"
    "建筑、家具、天气、光线细节可按剧情自然扩展，不要只写空泛大环境，"
    "也不要每镜随机换一套；只有剧情明确移动才换大环境。每镜 script 要写清本镜具体环境细节。\n"
    "2. 每个角色服装只能从各自初始服装开始，禁止发明锁定表之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣等；"
    "禁止复穿已脱衣物，禁止跳步；写清每个角色当前还穿着什么、已脱哪件初始服装；"
    "若初始服装有权重标记：带权重服装是保留核心，允许破坏、半脱、拉下，"
    "并允许在明确过渡动作后从半脱穿回，但绝对不允许全脱或消失；"
    "不带权重的初始服装必须按剧情节奏逐镜逐步脱去，最后一镜前全部脱完，脱掉后不得复穿；"
    "如果剧情要求隔着衣物→手伸进裤袜/内裤→直接摸阴唇/阴蒂，必须逐层写清，"
    "不能只写隔着衣物或一句笼统自慰；"
    "服装有层级：外衣在胸罩外，裤袜在内裤外；外层仍穿着时，手可以从外衣下伸入摸胸，"
    "或从裤袜腰口伸进内裤摸阴部；必须写清是隔着内裤/裤袜，还是手指已进入内层直接接触，"
    "并保留外衣、胸罩、裤袜、内裤的基础穿着状态；"
    "外衣没有脱掉、打开、解开、掀起之前，不能写可见的胸罩、乳房、内裤、"
    "拨开内裤等内衣状态；只能写外衣下的隐藏动作，等外衣明确打开或脱下后再露内衣；"
    "如果外层明确是薄纱/透明/半透明，可以透过外层看到内层，但要写清是隔着外层可见，"
    "不能把内衣写到外层外面；"
    "男主始终无服装、无脸、裸体，不写男主的衬衫、裤装、制服、外套、鞋、内衣等穿着；"
    "男主镜头优先近景、上半身或局部，只有动作确实需要时才写全身；"
    "script 里出现男主服装描述时视为错误，不要沿用，也不要让男主重新穿衣。"
    "性交中适当保留情趣服装（根据剧情需要调整），除非用户明确要求全裸；"
    "优先半脱、拨开、撕破、挂腿，禁止无铺垫直接全裸。"
    "用户明确要求撕破/扯破/剪开/破坏某件服装时，必须在对应阶段真实发生，"
    "不能只用拨到一侧代替。"
    "同一件服装的破损与半脱互斥：裤袜/丝袜破损后只写破洞或撕裂状态，"
    "不再写被拨到一侧、半脱、拉下；自慰或插入直接以破洞为入口。"
    + CLOTHING_EVENTS_BRIEF +
    "性行为、前戏、口交、插入、高潮、射精和余韵必须写清体液与交互："
    "唾液、湿润、阴道汁、潮吹、射精、精液、吞咽、射在身体/脸上等；"
    "不能只写动作，不能整段没有体液反馈。"
    "有男性参与时，性交高潮或结尾默认必须明确男方射精方式："
    "内射、射在身上、口交吞咽或射在脸上至少一种；"
    "没有男性参与时不要凭空加入男性或射精。除非用户明确要求不射精或不体液。"
    "3. 每镜 script 必须覆盖：角色/cast、服装/裸露状态、可见身体部位、姿势动作、表情、"
    "地点、景别、机位/角度、构图、光线时间、NSFW 状态。\n"
    "4. 因果连续：用户消息中的剧情进度账本、已完成镜头是硬事实，"
    "下一镜必须从这些事实自然接上，禁止重写或重复；禁止无故重启动作或换场景；"
    "每镜只能有一个主行为节拍，连续动作必须拆成多个镜头；"
    "插入、高潮、口交、吞咽、整理衣物不得塞进同一镜；"
    "插入后不得无过渡切回自慰、前戏或初遇；"
    "整理衣物或事后余韵后，不得无新事件又重新脱衣/自慰/前戏。"
    + STORY_FLOW_RULES + POSE_DIVERSITY_ZH + "\n"
    "6. 每镜 cast 必须写清人物数量与性别：用户未明确要求男性时只能用 1girl solo；"
    "明确要求双人时才用 1girl 1boy；没有出现的角色不得写进 cast；"
    "用户明确说前半没有男主或某角色后段才出现时，必须严格遵守出场时机；"
    "如果当前镜还不该出现男主，cast 只能写 solo，prompt 也不能出现男性。\n"
    "7. 每镜 script 本身就是该镜的剧情描述，必须写清谁做了什么、发生了什么变化；"
    "禁止复制上一镜、禁止只写身份或服装清单、禁止所有镜头重复同一句。\n"
    "8. 一次生成用户要求的全部镜头，不得只写开头几镜，不得从中间开始循环；"
    "id 必须从 01 连续编到总格数，不能重复、跳号。\n"
    "9. 每镜 script 按模板组织：角色/cast：…；服装：…；可见部位：…；姿势动作：…；"
    "表情：…；场景：…；镜头：…；构图：…；光线时间：…；NSFW：…。\n"
    "script 以 outline 为基础展开，不重新设计剧情，不重复已完成的剧情节点。\n"
    "每条同时填写 phase、beat、clothing、visible、pose、expression、scene、camera、"
    "lighting、nsfw，script 写完整画面描述。\n"
    "每条填写 present_characters 数组，只能写角色锁定表中实际出场的 name。\n"
    "只输出 schema JSON："
    "shots[{id,cast,present_characters,phase,beat,clothing,visible,pose,expression,"
    "scene,camera,lighting,nsfw,script}]，不要解释，不要英文标签。"
)
TAG_SYSTEM = (
    PRIORITY_RULES +
    "你是专业的二次元 NSFW Danbooru 提示词工程师。把给定的中文分镜 script 逐镜转换成英文 Booru prompt。\n"
    "成功标准（必须全部满足）：\n"
    "1. 只输出 schema JSON：shots[{id,prompt,focus}]。\n"
    "2. " + BOORU_WORKFLOW + "\n"
    "3. 保留 script 的全部剧情：服装/裸露、可见身体部位、姿势动作、表情、NSFW、"
    "大环境和环境细节、光线、镜头；不要漏大环境词，也不要只写身份或服装清单。"
    "同一大环境内的自然元素、道具、植被、建筑、家具、天气、光线细节可按剧情自然扩展，"
    "但不要每镜随机换一套。若 script 有撕破、破损、拨开衣物，"
    "必须输出对应状态标签，不能改成普通完整服装。\n"
    "3b. 每个 prompt 只表达一个主行为节拍；如果 script 同时写了多个连续主行为，"
    "只保留当前画面能表现的那一个，禁止把插入、高潮、口交、吞咽、整理衣物叠加在同一 prompt；"
    "如果 script 处于整理衣物或事后余韵，不要输出新的脱衣、自慰或前戏标签。\n"
    "3c. 同一服装类别只能有一个有效状态，不能同时写穿着和脱下；"
    "bra 颜色必须沿用 script/上一镜，不能突然换色或消失；"
    "pantyhose 是连裤袜，不是第二件 panties，禁止 two panties、second panties。"
    "同一服装的破损与半脱互斥；有 torn/ripped/hole 时，"
    "禁止同时输出 pulled aside、around、half-off 等同 key 标签。"
    "初始服装里带权重的单品是保留核心：允许 torn/ripped/hole 破坏，"
    "允许 pulled down、around thighs、panties aside、bra pull 等半脱/拉下，"
    "允许在明确非否定的过渡动作后从半脱穿回；但绝对禁止全脱、removed、消失。"
    "不带权重的初始单品必须按 script 的节奏逐镜脱掉，最后一镜前全部消失，不能复穿。"
    "3d. 如果 script 写了隔着裤袜/内裤 → 手伸进裤袜/内裤 → 直接摸阴唇/阴蒂，"
    "必须逐层写出 hand inside pantyhose、hand inside panties、"
    "fingers on labia/fingers on clitoris；不能只写 hand between legs、"
    "rubbing through pantyhose 或 through clothes。\n"
    "3e. 服装层级：外衣 > 胸罩，裤袜 > 内裤。外层仍完整穿着时，允许手从外衣下伸入"
    "摸胸，或从裤袜腰口伸进内裤摸私处：使用 hand under clothes、hand under shirt、"
    "hand inside bra、hand inside pantyhose、hand inside panties；这只是层内动作，"
    "不等于外层半脱，不能因此删除 uniform/shirt/bra/pantyhose/panties 的基础穿着标签。"
    "隔着内裤/裤袜时写 rubbing through panties/pantyhose，直接接触才写 "
    "fingers on labia/fingers on clitoris。"
    "外衣没有 removed/open/unbuttoned/lifted 时，禁止在 prompt 中出现可见的 "
    "black bra、bra strap visible、one breast out、black lace panties、panties aside；"
    "内衣只能保持隐藏，等外衣明确打开、掀起或脱掉后再出现。"
    "如果外层是 sheer/transparent/see-through 的衬衣或裤袜，允许用 "
    "bra visible through shirt、panties visible through pantyhose、sheer pantyhose "
    "表现半透明下层，但不能写成 bra outside clothes 或 panties over pantyhose。\n"
    "4. 必须按 script 的 cast 写清人数与性别：单人 1girl, solo；女主+我 1girl, 1boy；"
    "每个镜头最多一个男性，永远禁止 2boys、multiple boys、extra boy、second male。"
    "女性默认 1girl, solo；只有用户明确输入两个女性角色时才允许 2girls 或 multiple girls，"
    "否则禁止出现第二个女性、2girls、multiple girls。"
    "禁止出现 cast 之外的 second person、people。"
    "女主 appearance 非空时必须逐字保留发色、瞳色、发型、脸、身材、身体和标志物特征，"
    "每一镜都要写，不能改变、减少或省略；appearance 为空的角色不要自行补充。"
    "男主始终写 nude male、faceless male；"
    "禁止输出任何男装标签，即使 script 写了男主服装也不要沿用；"
    "男主优先近景/上半身/局部，除非动作确实需要，否则不要写 full body。"
    "禁止把女主的裙子、丝袜、高跟鞋或内衣写到男主身上。"
    "有男主身体在画面内时，不要单独写 penis、cock、POV 或 male pov；"
    "只写关系动作：penis in pussy、penis in mouth、hand on penis、penis at entrance；"
    "单写 penis/POV 只用于男主身体完全不可见的镜头。"
    "禁止 two penises、extra penis、second male、two male bodies。"
    "初始服装和情趣衣物默认保留；需要暴露时，用同一件衣物的半脱/破损/拨开标签推进，不要整件删除。"
    "破损/半脱标签必须绑定 script 中已有的具体单品，例如 torn pantyhose、"
    "panties aside、bra pull、pantyhose pulled down；不要输出无主语的 torn clothes、"
    "clothing damage、open clothes 来凭空生成新衣服。同时保留原始服装 tag。"
    "不要写死具体衣物种类；任何被保留的服装都用它自己的半脱/破损状态来露，而不是换成另一种衣服。"
    "已经脱掉的衣物后续不能重新穿上；服装状态只能从完整→半脱/破损→更少，不能倒退；"
    "破损单品不要同时保留同款完整基础标签。"
    "除非剧情明确进入最后全裸阶段，否则不要写 completely nude。"
    "性行为、前戏、口交、插入、高潮、射精、余韵镜头不能只写动作，必须写出对应体液和交互："
    "口交写 saliva、drool、cum in mouth、cum swallowing；插入写 wet pussy、pussy juice、creampie；"
    "高潮写 squirt、orgasm、female ejaculation；射精写 cum、semen、cum on body、cum on face；"
    "每个性相关镜头至少包含一个与当前行为匹配的体液/湿润/吞咽/喷射标签。"
    "如果 script 有射精、内射、吞咽或射在身上，必须写 cum、semen、creampie、"
    "cum in mouth、cum swallowing、cum on body 等对应标签。"
    "重点剧情标签必须与普通标签区分：从当前 prompt 中选 1-5 个最关键的"
    "动作/互动/关键 NSFW 状态/关键服装变化/体液结果写入 focus 数组，"
    "并对这些已存在标签加 (tag:1.2) 权重；基础外观、基础服装、场景、光线、"
    "机位、画风不加权；不要整段加权，不要超过 1.4。\n"
    "5. 标签用标准 Danbooru 词，不写整句英文。\n"
    "6. 每条 prompt 建议 25-45 个标签，复杂场景 50-70，最多 100；英文逗号分隔、去重，不要为凑数堆标签。\n"
    "7. 镜头只用 full body、upper body、close-up、medium shot、wide shot、from above/below/side、"
    "dutch angle、POV、depth of field 等抽象词；禁止 camera、holding camera、lens、tripod、photographer。\n"
    "8. 看向镜头写 looking at viewer，不写 looking at camera。"
    "角色标签以角色锁定表和 script 为准，不要自行补充不存在的外貌或服装。\n"
    "9. 不生成质量/画质标签（masterpiece, best quality, absurdres、ultra-detailed、highres、sharp focus 等）。\n"
    "不要复制任何示例中的具体角色、服装或颜色；所有角色和服装都以当前 script、"
    "角色锁定表和上一镜状态为准。"
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
    PRIORITY_RULES +
    "你是二次元 NSFW 剧情编剧。根据用户自然语言写出完整剧情，不写分镜标签，不写镜头编号。\n"
    "要求：\n"
    "1. 写清开始、发展、转折、高潮、结尾，不能只写开头就循环。\n"
    "2. 根据用户要求的总格数提供足够的剧情事件；每一段都要有独立事件和进展。\n"
    "默认只生成女主单人剧情：只有用户在角色或剧情中明确写出男主、男性、1boy、"
    "“我（男性）”或明确要求双人时，才允许加入男性角色。禁止擅自加入 1boy、男主、"
    "男性手、男性身体、男性影子或男性服装；没有明确要求时统一使用 1girl solo。"
    "如果用户明确说明某角色在某个阶段之后才出现，例如前半没有男主、女主先自慰，"
    "必须严格按该时机写，不能提前让男主出现。"
    + STORY_FLOW_RULES + "\n"
    "叙事节奏以用户剧情为准；用户没有明确节奏时，默认按"
    "气氛铺垫→试探/前戏→性行为→高潮余韵自然推进，避免没铺垫直接全裸或直接插入。"
    "每一步必须有新事件或新进展，不能在同一节拍原地打转。\n"
    "3. 先建立角色锁定表 characters，覆盖剧情中所有实际出场角色：女主、男主、我/男性、配角、"
    "以及多人场景中的每个人。每个角色必须有唯一 name、gender、appearance、initial_clothing。"
    "女主 appearance 写英文 Booru 外貌标签（发色、发型、瞳色、体型、身材、标志物、服装以外的固定特征）；"
    "用户填写的女主“外貌身材”是硬锁定，必须逐字复制，每一镜都要保留。"
    "女主初始服装必须逐字使用，不能添加初始服装之外的单品；"
    "用户没有给出女主服装时，可以一次性建立固定初始服装，之后全片不得更换或发明。"
    "男主/男性/我如果实际出现在画面中，characters 中只写 name 和 gender，"
    "appearance 和 initial_clothing 必须留空字符串；"
    "禁止为男主生成任何外貌、发型、瞳色、脸、身材、服装或内衣。"
    "男主的视觉表现统一由渲染阶段处理为裸体、无脸/头出框。"
    "characters 建立后，全片不得改变女主外貌或女主初始服装归属。\n"
    "4. 服装只从每个角色自己的初始服装单向变化；慢脱、慢调情，不要一开场就全裸；"
    "禁止发明初始服装之外的内衣、内裤、丝袜、胸罩、蕾丝、连体衣或其他衣物；"
    "需要脱掉时只能脱该角色初始服装中明确存在的单品，脱掉的不得再穿回；"
    "性行为中默认至少保留一件情趣服装、内衣、内裤、丝袜或吊带袜，"
    "只有用户明确要求全裸时才允许全裸；优先半脱、拨开、撕破、挂在腿边。"
    "每个角色的裸露状态必须独立连续，"
    "不能男主脱了又穿、女主裸了男主也跟着跳变。\n"
    "5. 大环境、人物关系和人物数量必须前后一致；同一大环境内的自然元素、道具、"
    "植被、建筑、家具、天气、光线细节可按剧情自然扩展，但不要每镜随机换一套；"
    "只有剧情明确移动才换大环境。\n"
    "6. 性行为、前戏、脱衣、高潮等必须写清楚，不要用模糊词或跳过；"
    "性行为必须写唾液、湿润、阴道汁、潮吹、射精、精液、吞咽或射在身体上等体液交互，不能只有动作。"
    + INTIMATE_CLOTHING_EVENTS_ZH +
    "要与挑逗、爱抚、自慰、性行为等场景自然组合，写清哪件衣物破损、位置、当前遮挡或暴露状态。"
    + POSE_DIVERSITY_ZH +
    "有男性参与时，性交高潮或结尾默认必须明确男方射精方式："
    "内射、射在身上、口交吞咽或射在脸上至少一种；"
    "没有男性参与时不要凭空加入男性或射精。除非用户明确要求不射精或不体液。\n"
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
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "beats": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "summary": {"type": "string"},
                    "cast": {"type": "string"},
                    "clothing": {"type": "string"},
                    "scene": {"type": "string"},
                    "nsfw": {"type": "string"},
                },
                "required": ["id", "title", "start", "end", "beats", "summary",
                             "cast", "clothing", "scene", "nsfw"],
            },
        }
    },
    "required": ["acts"],
}
ACT_PLAN_SYSTEM = (
    PRIORITY_RULES +
    "你是连续剧情分幕编剧。把完整剧情按用户要求的总格数拆成若干幕。\n"
    "要求：\n"
    "1. 每幕写清 start/end 镜头范围，最多 30 格；用户总格数超过 30 时，"
    "最后一幕可以少于 30 格。每幕 beats 写 3-6 个按顺序发生的关键节拍，"
    "后一幕不得重复前一幕的 beat。\n"
    "2. 按剧情顺序覆盖全部内容，不能漏掉结尾，不能重复同一事件。\n"
    "3. 每幕 summary 写清：本幕发生什么、谁出现、每个角色的服装/裸露进度、场景、NSFW 进度；"
    "如果有服装破损/撕毁、拨开情趣内裤等情节，也要写清哪个角色、哪件衣物、位置和当前状态；"
    "全片可安排 1-2 次角色已有服装的破损/滑落事件，由剧情自然决定，不强制每镜出现；"
    "下一幕必须能自然接上上一幕。\n"
    "4. cast 写清本幕人物，例如 1girl solo、1girl 1boy；不确定就按剧情写。"
    "用户未明确要求男性时只能写 1girl solo，禁止擅自加入 1boy 或男主。"
    "如果用户指定男主在某个阶段之后才出现，本幕 start/end 和 cast 必须严格遵守，"
    "不能提前让男主进入前面的幕；男主/男性/我只要出场，"
    "就必须与原角色锁定表的外貌、服装和裸露状态一致。\n"
    "5. clothing 写本幕服装起点和终点，必须按角色分别写，只能使用各角色初始服装中存在的单品；"
    "禁止新增初始服装之外的内衣/内裤/丝袜/胸罩/蕾丝；scene 写本幕主场景；nsfw 写本幕情色/性行为进度。\n"
    "6. 节奏必须循序渐进：前段只试探和轻微接触，中段自慰/勾引/前戏/慢脱，后段才插入；"
    "性交中适当保留情趣服装（根据剧情需要调整），除非用户明确要求全裸。"
    "每幕 title 必须概括本幕从头到尾的实际阶段，不能只用开头动作命名；"
    "长剧情必须拆成足够多的幕，单幕建议 6-12 镜，"
    "禁止一幕 20-30 镜把自慰、性交、事后、再会混在同一标题下。"
    + POSE_DIVERSITY_ZH + STORY_FLOW_RULES +
    "男主和女主的服装、裸露状态分别记录，男主不能穿女主衣服。\n"
    "只输出 JSON：{\"acts\":[{\"id\":\"01\",\"title\":\"...\",\"start\":1,\"end\":20,"
    "\"beats\":[\"...\",\"...\"],\"summary\":\"...\",\"cast\":\"...\","
    "\"clothing\":\"...\",\"scene\":\"...\",\"nsfw\":\"...\"}]}，不要解释。\n"
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
    preserve_ai_clothing: bool = True
    max_act_shots: int = 30
    on_partial: Callable[[list[dict[str, str]]], None] | None = None
    log: Callable[[str], None] = field(default=lambda _msg: None)
@dataclass
class CharacterProfile:
    key: str
    name: str = ""
    gender: str = "girl"
    appearance: list[str] = field(default_factory=list)
    initial_clothing: list[str] = field(default_factory=list)
    appearance_locked: bool = False
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
                ("phase", ("phase", "阶段")),
                ("beat", ("beat", "节拍")),
                ("shot_size", ("shot_size", "景别")),
                ("camera_angle", ("camera_angle", "机位", "camera")),
                ("composition", ("composition", "构图")),
                ("continuity_state", ("continuity_state", "连续性状态")),
                ("continuity_scene", ("continuity_scene", "连续性场景")),
                ("keyframe_prompt", ("keyframe_prompt", "起始提示词"))):
            value = _json_field(item, aliases)
            if value:
                shot[key] = value
        expansions = item.get("ai_expansions")
        if isinstance(expansions, list):
            shot["ai_expansions"] = [str(value).strip() for value in expansions
                                     if str(value).strip()]
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
    rows: list[str] = []
    for item in items:
        details = [
            str(item.get(key) or "").strip()
            for key in ("cast", "phase", "clothing", "scene", "nsfw")
            if str(item.get(key) or "").strip()
        ]
        beats = item.get("beats")
        if isinstance(beats, list) and beats:
            details.append("关键节拍：" + "、".join(
                str(beat) for beat in beats if str(beat).strip()))
        rows.append("%s%s" % (
            item.get("summary", ""),
            "（%s）" % "，".join(details) if details else ""))
    return "；".join(rows)
def _story_progress_ledger(shots: list[dict[str, Any]]) -> str:
    if not shots:
        return ""
    counts: dict[str, int] = {}
    stage_rows: list[str] = []
    recent: list[str] = []
    current = ""
    previous = ""
    run_length = 0
    for shot in shots:
        text = str(shot.get("outline") or shot.get("script")
                   or shot.get("prompt") or "").strip()
        label = str(shot.get("phase") or shot.get("beat") or "").strip()
        if not label:
            label = text[:40]
        if label:
            counts[label] = counts.get(label, 0) + 1
            run_length = run_length + 1 if label == previous else 1
            previous = label
            current = label
            stage_rows.append("%s:%s" % (shot.get("id", ""), label))
        else:
            run_length = 0
            previous = ""
        recent.append("%s %s" % (shot.get("id", ""), text[:80]))
    completed = "、".join(
        "%s×%d" % (name, count) for name, count in counts.items()) or "尚未判定"
    loop_guard = ""
    if run_length >= 15:
        loop_guard = (
            "当前阶段已连续 %d 镜，下一镜必须推进到新事件或压缩该阶段，"
            "不能继续原地换词。" % run_length)
    return (
        "剧情进度账本：已完成阶段=%s；当前阶段=%s；最近阶段=%s；最近镜头=%s。"
        "%s续写规则：只能从当前阶段向前推进；不得无理由重复已完成事件；"
        "同一镜只能有一个主节拍，连续动作必须拆成多镜；"
        "如果剧情需要第二次，必须写明过渡、理由和新变化。" % (
            completed,
            current or "未判定",
            "；".join(stage_rows[-8:]),
            "；".join(recent[-4:]),
            loop_guard))
def _with_outline_progress(story_state: str,
                           outline: list[dict[str, Any]]) -> str:
    if not outline:
        return story_state
    ledger = _story_progress_ledger([
        {"id": item.get("id", ""), "phase": item.get("phase", ""),
         "beat": item.get("beat", ""), "outline": item.get("outline", "")}
        for item in outline])
    return "\n".join(part for part in (story_state, ledger) if part)
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
    ledger = _story_progress_ledger(shots)
    return ("全局状态表：场景=%s；服装进度=%s；%s；禁止换场景、复穿已脱衣物、"
            "跳步、突然全裸、改变角色外貌。" % (
                scene or "沿用上一镜", clothing[:400] or "按初始服装", ledger))
def _initial_clothing_tags(premise: str) -> list[str]:
    for line in str(premise or "").splitlines():
        if "初始服装" not in line:
            continue
        parts = re.split(r"[:：]", line, maxsplit=1)
        raw = parts[1] if len(parts) == 2 else line
        return [tag.strip() for tag in re.split(r"[,，、]", raw) if tag.strip()]
    return []
def _has_weight(tag: str) -> bool:
    return bool(_WEIGHT_TAG_RE.search(str(tag or "").strip()))
def wardrobe_weight_policy(premise: str) -> str:
    tags = _initial_clothing_tags(premise)
    if not tags:
        return ""
    weighted = [tag for tag in tags if _has_weight(tag)]
    unweighted = [tag for tag in tags if not _has_weight(tag)]
    if not weighted or not unweighted:
        return ""
    return (
        "服装权重规则：带权重服装是保留核心（%s），不得无故脱掉；"
        "不带权重的初始服装（%s）必须按剧情节奏逐镜逐步脱去，"
        "最后一镜前全部脱完，不能跳步、不能一次性全脱，脱掉后不得复穿。" % (
            ", ".join(weighted), ", ".join(unweighted)))
def normalize_shot_casts(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        cast = str(shot.get("cast") or "").strip()
        if cast:
            shot["cast"] = re.sub(r"\s+", " ", cast)
def renumber_shots(shots: list[dict[str, Any]]) -> None:
    for index, shot in enumerate(shots, 1):
        if isinstance(shot, dict):
            shot["id"] = "%02d" % index
def _clothing_key(tag: str) -> str:
    low = re.sub(r"[_\-]+", " ", str(tag).lower()).strip()
    if low in {"undressing", "dressing", "dress up", "dress down"}:
        return ""
    if "light" in low and "top" in low:
        return ""
    for key, patterns in _CLOTHING_KEYS:
        if any(re.search(pattern, low, re.I) for pattern in patterns):
            return key
    return ""
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
        weighted = re.fullmatch(r"(.+?)\((\d+(?:\.\d+)?)\)", tag)
        if weighted:
            tag = "(%s:%s)" % (weighted.group(1).strip(), weighted.group(2))
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
                 r"(?:^|[\s,，;；])男(?:$|[\s,，;；])|"
                 r"\b(?:penis|cock|testicles|phallus|beard|muscular|abs|"
                 r"pectorals|adam's apple)\b", text):
        return "boy"
    if re.search(r"女主|女性|女孩|女人|少女|1girl|\bgirl\b|\bfemale\b|"
                 r"\bwoman\b|\bwomen\b|她|"
                 r"(?:^|[\s,，;；])女(?:$|[\s,，;；])|"
                 r"\b(?:breasts?|boobs?|pussy|vagina|labia|clitoris|uterus|"
                 r"womb|pantyhose|stockings?|thighhighs?|skirt|dress|bra|"
                 r"panties|lingerie|high heels?|makeup)\b", text):
        return "girl"
    return "other"
def _is_accessory(tag: str) -> bool:
    low = str(tag or "").lower()
    if _clothing_key(tag):
        return False
    return any(pattern in low for pattern in _ACCESSORY_PATTERNS)
def _clean_appearance(tags: list[str]) -> list[str]:
    return [tag for tag in tags
            if tag and tag.lower() not in _CHARACTER_DROP_TAGS
            and not _clothing_key(tag) and not _is_accessory(tag)]
def _normalize_weight_colons(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"\(([^()]+?)\s*[:：]\s*(\d+(?:\.\d+)?)\)",
        r"\1(\2)", value)
    return re.sub(
        r"(?<![(\w])([A-Za-z][A-Za-z0-9 _\-]*?)\s*[:：]\s*(\d+(?:\.\d+)?)",
        r"\1(\2)", value)
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
            appearance=_clean_appearance(_split_tags(appearance_source or "")),
            initial_clothing=_split_tags(clothing_value),
            appearance_locked=bool(explicit_appearance),
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
            if appearance and not strip_appearance and not existing.appearance_locked:
                if not existing.appearance:
                    existing.appearance = appearance
                else:
                    seen = {tag.lower() for tag in existing.appearance}
                    for tag in appearance:
                        if tag.lower() not in seen:
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
def strip_male_profile_details(profiles: list[CharacterProfile]
                               ) -> list[CharacterProfile]:
    for profile in profiles:
        if profile.gender == "boy":
            profile.appearance = []
            profile.initial_clothing = []
    return profiles
def character_bible_text(profiles: list[CharacterProfile]) -> str:
    lines = ["角色锁定表（全片硬约束，任何一镜都不得改变）："]
    for profile in profiles:
        lines.append(
            "- %s（%s）：appearance=%s%s；initial_clothing=%s" % (
                profile.name or profile.key, profile.gender,
                ", ".join(profile.appearance) or "未指定",
                "（用户硬锁定，禁止增删改）" if profile.appearance_locked else "",
                ", ".join(profile.initial_clothing) or "未指定"))
    lines.append(
        "规则：每个出场角色的发色、发型、瞳色、体型、身材、标志物必须与锁定表逐字一致；"
        "用户填写的外貌/身材是硬锁定，任何镜头都必须原样保留，不能更改、减少或遗漏。"
        "男性和女性都适用。每个角色的服装和裸露状态独立连续，脱掉后不得复穿，"
        "不得凭空增加锁定表之外的衣物；没有出现的角色不得写进当前画面。"
        "男主/男性/我只要出现在画面中，就必须保持同一外貌、同一初始服装和同一裸露进度。")
    return "\n".join(lines)
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
def _finalize_generated_story_once(shots: list[dict[str, Any]], premise: str,
                             profiles: list[CharacterProfile] | None = None
                             ) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        prompt = normalize_prompt_text(str(shot.get("prompt") or ""))
        if prompt:
            shot["prompt"] = prompt
        negative = normalize_prompt_text(str(shot.get("negative") or ""))
        if negative:
            shot["negative"] = negative
def finalize_generated_story(shots: list[dict[str, Any]], premise: str,
                             profiles: list[CharacterProfile] | None = None
                             ) -> None:
    _finalize_generated_story_once(shots, premise, profiles)
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
            text = "；".join(
                part for part in (
                    str(item.get("beat") or "").strip(),
                    str(item.get("clothing") or "").strip(),
                    str(item.get("scene") or "").strip(),
                    str(item.get("camera") or "").strip(),
                    str(item.get("nsfw") or "").strip(),
                ) if part)
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
        cast = str(forced_cast or item.get("cast") or "").strip()
        shot = {"id": number, "name": name, "cast": cast, "outline": text}
        present = item.get("present_characters")
        if isinstance(present, list):
            shot["present_characters"] = [
                str(name).strip() for name in present if str(name).strip()]
        for key in ("phase", "beat", "clothing", "scene", "camera", "nsfw"):
            value = str(item.get(key) or "").strip()
            if value:
                shot[key] = value
        outline.append(shot)
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
    clothing_policy = wardrobe_weight_policy(premise)
    if clothing_policy:
        user.append(clothing_policy)
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
        user.append("大环境/附加要求（大环境连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    if prior:
        user.append("上一段大纲（保持剧情方向，禁止重复其动作和句子）：\n" +
                    "\n".join("%s %s" % (item["id"], item["outline"])
                              for item in prior[-4:]))
    user.append("请生成完整编号大纲。每条必须覆盖：身份、服装/裸露、可见部位、姿势动作、"
                "表情、大环境、环境细节、镜头、构图、光线、NSFW、cast。每条 outline 必须不同。"
                "大环境锁定后，同一环境内的自然元素、道具、植被、建筑、家具、天气、"
                "光线细节可按剧情自然扩展；不要只写空泛大环境，也不要每镜随机换一套。")
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
                                           act_summary=act_summary,
                                           story_state=_with_outline_progress(
                                               story_state, outline),
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
                                       act_summary=act_summary,
                                       story_state=_with_outline_progress(
                                           story_state, outline),
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
        user.append("大环境/附加要求（大环境连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    user.append("请先写完整剧情，不要分镜编号，不要英文标签。")
    return [
        {"role": "system", "content": STORY_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
def build_act_plan_messages(story: str, premise: str, total: int,
                            setting: str = "",
                            max_act_shots: int = 30) -> list[dict[str, str]]:
    max_act_shots = max(1, int(max_act_shots))
    acts = max(1, (total + max_act_shots - 1) // max_act_shots)
    user = [
        "完整剧情：\n%s" % story,
        "用户设定：\n%s" % premise,
        "总格数：%d，分成 %d 幕，每幕最多 %d 格" % (
            total, acts, max_act_shots),
    ]
    if setting.strip():
        user.append("大环境/附加要求（大环境连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    return [
        {"role": "system", "content": ACT_PLAN_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
def normalize_acts(raw: dict[str, Any] | list[Any], total: int,
                   story: str) -> list[dict[str, Any]]:
    items = raw.get("acts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not summary:
            continue
        beats = item.get("beats")
        cleaned.append({
            "title": str(item.get("title") or "第%d幕" % (index + 1)).strip(),
            "summary": summary,
            "cast": str(item.get("cast") or "").strip(),
            "clothing": str(item.get("clothing") or "").strip(),
            "scene": str(item.get("scene") or "").strip(),
            "nsfw": str(item.get("nsfw") or "").strip(),
            "beats": [str(beat).strip() for beat in beats
                      if str(beat).strip()] if isinstance(beats, list) else [],
            "start": item.get("start"),
            "end": item.get("end"),
        })
    if not cleaned:
        if not str(story or "").strip():
            return []
        cleaned = [{
            "title": "完整剧情", "summary": str(story).strip(),
            "cast": "", "clothing": "", "scene": "", "nsfw": "",
            "beats": [], "start": 1, "end": total,
        }]
    span = max(1, (total + len(cleaned) - 1) // len(cleaned))
    for index, item in enumerate(cleaned):
        item["id"] = "%02d" % (index + 1)
        try:
            start = int(item.get("start") or 0)
            end = int(item.get("end") or 0)
        except (TypeError, ValueError):
            start = end = 0
        if start < 1 or end > total or start > end:
            start = index * span + 1
            end = min(total, (index + 1) * span)
        item["start"] = start
        item["end"] = end
    cursor = 1
    for item in cleaned:
        if cursor > total:
            break
        start = cursor
        end = max(start, min(total, int(item.get("end") or start)))
        item["start"] = start
        item["end"] = end
        cursor = end + 1
    if cleaned and cursor <= total:
        cleaned[-1]["end"] = total
    return cleaned
def build_premise_act_plan_messages(premise: str, total: int,
                                    setting: str = "",
                                    max_act_shots: int = 30
                                    ) -> list[dict[str, str]]:
    max_act_shots = max(1, int(max_act_shots))
    acts = max(1, (total + max_act_shots - 1) // max_act_shots)
    user = [
        "用户剧情/要求：\n%s" % premise,
        "总格数：%d，请按剧情顺序分成 %d 幕，每幕最多 %d 格" % (
            total, acts, max_act_shots),
        "只规划真正的剧情阶段，不要把用户的写作要求、格式说明或数量要求"
        "当成剧情阶段；每幕必须明确推进，不能重复上一幕的事件。",
    ]
    if setting.strip():
        user.append("大环境/附加要求（大环境连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    return [
        {"role": "system", "content": ACT_PLAN_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
def plan_story_spine(client: OllamaClient, model: str, premise: str,
                     shots: int, setting: str = "", timeout: float = 600.0,
                     log: Callable[[str], None] | None = None,
                     max_act_shots: int = 30
                     ) -> list[dict[str, Any]]:
    raw = client.chat_json(
        model,
        build_premise_act_plan_messages(
            premise, shots, setting, max_act_shots=max_act_shots),
        schema=ACT_PLAN_SCHEMA,
        temperature=0.6,
        num_predict=4096,
        num_ctx=32768,
        keep_alive="5m",
        timeout=timeout,
        retries=2,
    )
    if not isinstance(raw, dict) or not raw.get("acts"):
        return []
    acts = normalize_acts(raw, shots, premise)
    spine = [{
        "summary": act.get("summary", ""),
        "cast": act.get("cast", ""),
        "phase": act.get("title", ""),
        "clothing": act.get("clothing", ""),
        "scene": act.get("scene", ""),
        "nsfw": act.get("nsfw", ""),
        "beats": act.get("beats") or [],
        "start": act.get("start", 1),
        "end": act.get("end", shots),
    } for act in acts]
    if log:
        log("Story acts: " + " | ".join(
            "%d-%d:%s(%s)" % (item["start"], item["end"],
                              str(item["summary"])[:24], item["cast"])
            for item in spine))
    return spine
def generate_full_story_pipeline(client: OllamaClient, premise: str,
                                 options: StoryboardOptions,
                                 initial: list[dict[str, str]],
                                 shots: int) -> list[dict[str, str]]:
    log = options.log
    log("Stage 1/4: writing complete story...")
    story_raw = client.chat_json(
        generation_model(options.model),
        build_story_messages(premise, shots, options.setting),
        schema=STORY_SCHEMA, temperature=options.temperature,
        num_predict=16384, num_ctx=32768, keep_alive=options.keep_alive,
        timeout=max(options.timeout, 600.0), retries=2,
    )
    story = str(story_raw.get("story") or "").strip()
    if not story:
        raise ValueError("Model returned an empty complete story.")
    profiles = strip_male_profile_details(normalize_character_profiles(
        story_raw.get("characters"), premise, options.strip_appearance))
    bible = character_bible_text(profiles)
    log("Character lock: " + " | ".join(
        "%s(%s): %s" % (profile.name, profile.gender,
                        ", ".join(profile.initial_clothing) or "no clothing")
        for profile in profiles))
    log("Stage 2/4: splitting story into acts...")
    act_raw = client.chat_json(
        generation_model(options.model),
        build_act_plan_messages(
            story, premise, shots, options.setting,
            max_act_shots=options.max_act_shots),
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
            client, generation_model(options.model), act_premise, act_size, options.setting,
            chunk=6, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance,
            character_bible=bible,
            act_summary="%s；%s；服装：%s；场景：%s；NSFW：%s" % (
                act["title"], act["summary"], act["clothing"],
                act["scene"], act["nsfw"]),
            story_state=state, start_shot=start, total_shots=shots,
        )
        for offset in range(0, len(outline), options.chunk):
            chunk_outline = outline[offset:offset + options.chunk]
            scripts = [{
                "id": item["id"], "name": item["name"],
                "script": item["outline"], "cast": item.get("cast", ""),
                "phase": str(act.get("title") or ""),
            } for item in chunk_outline]
            chunk_state = _global_story_state(
                act_premise, result, profiles)
            tag_raw = client.chat_json(
                prompt_conversion_model(options.model),
                build_tag_messages(
                    scripts, options.style_positive, options.setting,
                    strip_appearance=options.strip_appearance,
                    cast_hint=str(scripts[0].get("cast") or ""),
                    story_state=chunk_state, character_bible=bible),
                schema=TAG_SCHEMA, temperature=options.temperature,
                num_predict=8192, num_ctx=32768, keep_alive=options.keep_alive,
                timeout=options.timeout, retries=3,
            )
            part = normalize_tagged(tag_raw, scripts)
            chunk_start = len(result)
            result.extend(part)
            _notify_partial(options, result)
            log("Stage 4/4: Act %d +%d shots (%d/%d)" % (
                act_index, len(part), len(result), shots))
            if not part:
                break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    result = result[:shots]
    renumber_shots(result)
    normalize_shot_casts(result)
    run_all_reviews(
        client, review_model(options.model), result, premise,
        batch_size=10, max_passes=2,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles)
    ensure_clothing_gate(
        client, review_model(options.model), result, premise,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles, max_passes=3)
    finalize_generated_story(result, premise)
    return result

def script_from_fields(item: dict[str, Any]) -> str:
    parts = []
    for key, label in _SCRIPT_FIELD_LABELS:
        value = str(item.get(key) or "").strip()
        if value:
            parts.append("%s：%s" % (label, value))
    return "；".join(parts).strip()
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
        script = str(
            item.get("script") or item.get("prompt")
            or script_from_fields(item) or "").strip()
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
        shot = {
            "id": number,
            "name": name,
            "script": script,
            "cast": str(item.get("cast") or "").strip(),
            "outline": "",
        }
        present = item.get("present_characters")
        if isinstance(present, list):
            shot["present_characters"] = [
                str(name).strip() for name in present if str(name).strip()]
        for key in ("phase", "beat", "clothing", "visible", "pose",
                    "expression", "scene", "camera", "lighting", "nsfw"):
            value = str(item.get(key) or "").strip()
            if value:
                shot[key] = value
        scripts.append(shot)
    if not scripts:
        raise ValueError("Model returned no usable Chinese scripts.")
    trace_event("normalized.scripts", scripts)
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
        focus = item.get("focus") or item.get("focus_tags")
        shot = {
            "id": script["id"],
            "name": script["name"],
            "prompt": prompt,
            "negative": raw_prompt(item.get("negative") or ""),
            "focus_tags": [
                str(tag).strip() for tag in focus
                if str(tag).strip()] if isinstance(focus, list) else [],
            "script": script["script"],
            "cast": str(script.get("cast") or "").strip(),
            "phase": str(
                script.get("phase") or script.get("beat")
                or script.get("outline") or script.get("script") or "")[:80],
            "outline": script.get("outline") or script["script"],
        }
        present = script.get("present_characters")
        if isinstance(present, list):
            shot["present_characters"] = [
                str(name).strip() for name in present if str(name).strip()]
        for key in ("beat", "clothing", "visible", "pose", "expression",
                    "scene", "camera", "lighting", "nsfw"):
            value = str(script.get(key) or "").strip()
            if value:
                shot[key] = value
        shots.append(shot)
    if not shots:
        raise ValueError("Model returned no usable tagged shots.")
    trace_event("normalized.tags", shots)
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
    clothing_policy = wardrobe_weight_policy(premise)
    if clothing_policy:
        user.append(clothing_policy)
    if character_bible:
        user.append(character_bible)
    if act_summary:
        user.append("本幕硬性大纲：%s" % act_summary)
    if phase:
        user.append("本幕阶段：%s" % phase)
    if cast_hint:
        user.append("本批起始 cast 参考：%s（后续以逐镜分镜为准）" % cast_hint)
    if story_state:
        user.append(story_state)
    if strip_appearance:
        user.append("已启用角色 LoRA：对使用 LoRA 的角色，不要生成或补充角色外貌和身体特征"
                    "（发色、瞳色、发型、脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责；"
                    "没有 LoRA 的角色必须保留锁定表里的固定外貌。")
    if setting.strip():
        user.append("大环境/附加要求（大环境全程连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    if beats:
        user.append("硬性剧情条目（第 %d 镜必须对应第 %d 条，不得合并、跳过或提前）：\n" %
                    (start, start) + "\n".join(
                        "%d. %s" % (start + index, beat)
                        for index, beat in enumerate(beats)))
    if prior:
        tail = "\n".join("%s %s" % (
            shot.get("id", ""), shot.get("script") or shot.get("prompt", ""))
            for shot in prior[-4:])
        user.append("上一段已完成分镜脚本（保持连续，禁止复穿/跳步/随机换大环境）：\n"
                    + tail)
    user.append("请只输出中文分镜脚本，每镜必须覆盖身份、服装/裸露、可见部位、姿势动作、"
                "表情、大环境、环境细节、镜头、构图、光线、NSFW；从第 %d 镜开始编号。"
                "同一大环境内的自然元素、道具、植被、建筑、家具、天气、光线细节"
                "可按剧情自然扩展，但必须前后连续，不要每镜随机换一套。" % start)
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
    if phase:
        user.append("本幕阶段：%s" % phase)
    if cast_hint:
        user.append("本批起始 cast 参考：%s（逐镜仍以 script 的 cast 为准）"
                    % cast_hint)
    if story_state:
        user.append(story_state)
    if strip_appearance:
        user.append("已启用角色 LoRA：对使用 LoRA 的角色，不要输出角色外貌和身体特征"
                    "（发色、瞳色、发型、脸、肤色、体型、胸围等），这些由 LoRA 和激活标签负责；"
                    "没有 LoRA 的角色必须保留锁定表里的固定外貌。")
    if style_positive.strip():
        user.append("画风：%s" % style_positive.strip())
    if setting.strip():
        user.append("大环境/附加要求（大环境连续，内部细节可自然扩展）：%s" %
                    setting.strip())
    user.append("中文分镜脚本：")
    for script in scripts:
        user.append("id=%s name=%s\n剧情节点=%s\n脚本=%s" % (
            script["id"], script["name"],
            script.get("outline") or script.get("script", ""),
            script["script"]))
    user.append("请逐镜转换成英文 Booru prompt；保留全部剧情/服装/大环境/"
                "环境细节/NSFW；大环境词必须保留，环境细节按 script 保留，"
                "不要每镜随机换一套，不要参考角色标签。")
    return [
        {"role": "system", "content": TAG_SYSTEM},
        {"role": "user", "content": "\n\n".join(user)},
    ]
def _notify_partial(options: StoryboardOptions,
                    shots: list[dict[str, str]]) -> None:
    if options.on_partial is None:
        return
    try:
        options.on_partial([dict(shot) for shot in shots])
    except Exception as exc:
        options.log("Checkpoint save failed: %s" % exc)
def _generate_long_storyboard(client: OllamaClient, premise: str,
                              options: StoryboardOptions,
                              initial: list[dict[str, str]],
                              shots: int) -> list[dict[str, str]]:
    log = options.log
    result: list[dict[str, str]] = initial[:shots]
    profiles = strip_male_profile_details(parse_character_profiles(premise))
    bible = character_bible_text(profiles)
    spine: list[dict[str, Any]] = []
    max_act_shots = max(1, int(options.max_act_shots))
    if not extract_premise_beats(premise):
        spine = plan_story_spine(
            client, generation_model(options.model), premise, shots, options.setting,
            timeout=max(options.timeout, 600.0), log=log,
            max_act_shots=max_act_shots)
    act_total = (shots + max_act_shots - 1) // max_act_shots
    act_index = 0
    while len(result) < shots:
        act_index += 1
        act_start = len(result) + 1
        act = _phase_at(spine, act_start) if spine else {}
        try:
            act_end = int(act.get("end") or 0)
        except (TypeError, ValueError):
            act_end = 0
        if act_end < act_start or act_end > shots:
            act_end = min(shots, act_start + max_act_shots - 1)
        act_size = max(1, act_end - act_start + 1)
        act_summary = _act_summary(spine, act_start, act_end)
        story_state = _global_story_state(premise, result, profiles)
        log("Act %d/%d: shots %d-%d" % (
            act_index, act_total, act_start, act_end))
        outline = plan_storyboard_outline(
            client, generation_model(options.model), premise, act_size, options.setting,
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
            chunk_state = _global_story_state(premise, result, profiles)
            script_raw = client.chat_json(
                generation_model(options.model),
                build_script_messages(
                    premise, len(outline_chunk), options.setting,
                    result, shots, [item["outline"] for item in outline_chunk],
                    strip_appearance=options.strip_appearance,
                    phase=str(outline_chunk[0].get("phase") or ""),
                    cast_hint=str(outline_chunk[0].get("cast") or ""),
                    story_state=chunk_state, act_summary=act_summary,
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
                if outline_chunk[index].get("phase"):
                    script["phase"] = outline_chunk[index]["phase"]
            tag_raw = client.chat_json(
                prompt_conversion_model(options.model),
                build_tag_messages(
                    script_chunk, options.style_positive, options.setting,
                    strip_appearance=options.strip_appearance,
                    phase=str(script_chunk[0].get("phase") or ""),
                    cast_hint=str(script_chunk[0].get("cast") or ""),
                    story_state=chunk_state, character_bible=bible),
                schema=TAG_SCHEMA,
                temperature=options.temperature,
                num_predict=16384,
                num_ctx=32768,
                keep_alive=options.keep_alive,
                timeout=options.timeout,
                retries=3,
            )
            part = normalize_tagged(tag_raw, script_chunk)
            chunk_start = len(result)
            result.extend(part)
            _notify_partial(options, result)
            log("Act %d: +%d shots (%d/%d)" % (act_index, len(part), len(result), shots))
            if not part:
                break
        if len(result) >= shots:
            break
    result = result[:shots]
    renumber_shots(result)
    normalize_shot_casts(result)
    run_all_reviews(
        client, review_model(options.model), result, premise,
        batch_size=10, max_passes=2,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles)
    ensure_clothing_gate(
        client, review_model(options.model), result, premise,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles, max_passes=3)
    finalize_generated_story(result, premise)
    return result

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
        finalize_generated_story(result, premise)
        return result
    if options.full_story and not extract_premise_beats(premise):
        return generate_full_story_pipeline(client, premise, options, result, shots)
    if shots > max(1, int(options.max_act_shots)):
        return _generate_long_storyboard(client, premise, options, result, shots)

    profiles = strip_male_profile_details(parse_character_profiles(premise))
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
        log("Stage 0: planning %d numbered outline entries..." % remaining)
        outline = plan_storyboard_outline(
            client, generation_model(options.model), premise, remaining, options.setting,
            chunk=6, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance, spine=None,
            character_bible=bible)
    if not outline:
        raise ValueError("Model produced no usable storyboard outline.")

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
        chunk_state = _global_story_state(premise, result, profiles)
        script_raw = client.chat_json(
            generation_model(options.model),
            build_script_messages(
                premise, len(outline_chunk), options.setting,
                result, shots, beat_slice,
                strip_appearance=options.strip_appearance,
                phase=str(outline_chunk[0].get("phase") or ""),
                cast_hint=str(outline_chunk[0].get("cast") or ""),
                story_state=chunk_state, character_bible=bible),
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
                if outline_chunk[index].get("phase"):
                    script["phase"] = outline_chunk[index]["phase"]
        log("Stage B: translating shots %d-%d to English tags..." % (
            script_base + offset + 1,
            script_base + offset + len(script_chunk)))
        tag_raw = client.chat_json(
            prompt_conversion_model(options.model),
            build_tag_messages(
                script_chunk, options.style_positive, options.setting,
                strip_appearance=options.strip_appearance,
                phase=str(script_chunk[0].get("phase") or ""),
                cast_hint=str(script_chunk[0].get("cast") or ""),
                story_state=chunk_state, character_bible=bible),
            schema=TAG_SCHEMA,
            temperature=options.temperature,
            num_predict=16384,
            num_ctx=32768,
            keep_alive=options.keep_alive,
            timeout=options.timeout,
            retries=3,
        )
        part = normalize_tagged(tag_raw, script_chunk)
        chunk_start = len(result)
        result.extend(part)
        _notify_partial(options, result)
        log("Stage B: +%d shots (%d/%d)" % (len(part), len(result), shots))
        if not part:
            break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    result = result[:shots]
    renumber_shots(result)
    normalize_shot_casts(result)
    run_all_reviews(
        client, review_model(options.model), result, premise,
        batch_size=10, max_passes=2,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles)
    ensure_clothing_gate(
        client, review_model(options.model), result, premise,
        timeout=max(options.timeout, 600.0), log=options.log,
        profiles=profiles, max_passes=3)
    finalize_generated_story(result, premise)
    return result

_JSON_PROMPT_KEYS = (
    "prompt", "prompt_en", "positive", "tags", "text", "caption",
    "description", "content", "英文提示词",
)

_JSON_PROMPT_ZH_KEYS = ("prompt_zh", "zh", "chinese", "中文", "中文提示词")

_JSON_OUTLINE_KEYS = ("outline", "brief", "summary", "大纲", "中文大纲")

_JSON_ID_KEYS = ("id", "shot_id", "shot", "index", "number", "序号")

_JSON_NAME_KEYS = ("name", "title", "slug", "名称")

_CLOTHING_KEYS = (
    ("fishnet", (r"fishnet", r"net tights", r"网袜", r"渔网袜", r"网眼袜")),
    ("pantyhose", (r"pantyhose", r"tights", r"crotch hole", r"pantyhose hole",
                   r"黑丝", r"白丝", r"丝袜", r"连裤袜")),
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
    ("uniform_top", (r"\b(?:military|dress|uniform|service)\s+(?:top|jacket|coat|shirt)\b",
                     r"\b(?:jacket|top)\s+(?:of|from)\s+(?:a|the)\s+uniform\b",
                     r"军装上衣", r"制服上衣", r"军服上衣")),
    ("skirt", (r"military skirt", r"uniform skirt", r"service skirt", r"skirt",
               r"裙子", r"短裙", r"裙")),
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

_WEIGHT_TAG_RE = re.compile(
    r"\(\s*(?:\d+(?:\.\d+)?|[^()]*?:\s*\d+(?:\.\d+)?)\s*\)\s*$")

_CHARACTER_DROP_TAGS = {
    "她", "他", "我", "你", "女主", "男主", "女性", "男性", "女孩", "男孩",
    "少女", "少年", "角色", "人物", "girl", "boy", "female", "male",
    "1girl", "1boy", "solo", "multiple girls", "multiple boys",
}

_TOP_SECTION_RE = re.compile(
    r"^(?:角色设定|角色标签|角色|人物设定|人物|外貌身材|角色外貌|人物外貌|外貌|"
    r"外形|身材|体型|初始服装|初始装扮|服装|大场景|场景|剧情|故事|额外|画风)"
    r"\s*[:：]")

_ACCESSORY_PATTERNS = (
    "hairclip", "hair clip", "hairpin", "hair pin", "barrette", "hair ornament",
    "hair bow", "hair ribbon", "hairband", "hair band", "headband", "flower",
    "brooch", "earring", "earrings", "earcuff", "ear cuff", "necklace",
    "pendant", "bracelet", "bangle", "ring", "rings", "anklet", "toe ring",
    "watch", "wristwatch", "wristband", "armband", "arm band", "belly chain",
    "body chain", "glasses", "sunglasses", "goggles", "eyepatch", "piercing",
    "piercings", "tiara", "crown", "diadem",
)

_SCRIPT_FIELD_LABELS = (
    ("beat", "动作"),
    ("clothing", "服装"),
    ("visible", "可见部位"),
    ("pose", "姿势"),
    ("expression", "表情"),
    ("scene", "场景"),
    ("camera", "镜头"),
    ("composition", "构图"),
    ("lighting", "光线"),
    ("nsfw", "NSFW"),
)
