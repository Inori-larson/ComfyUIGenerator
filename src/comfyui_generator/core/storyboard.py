"""Ollama storyboard generation: premise -> continuous shot list."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.trace import trace_event

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
                    "focus": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
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
    "fingers on labia/fingers on clitoris。\n"
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


def _format_issue_log(title: str, issues: Any) -> str:
    values = [" ".join(str(item).split()) for item in (issues or [])
              if str(item).strip()]
    if not values:
        return title
    first = values[0][:120]
    if len(values) == 1:
        return "%s：%s" % (title, first)
    return "%s：%s（另 %d 项）" % (title, first, len(values) - 1)


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
    "beach": ["beach", "ocean", "sea", "shore", "seaside", "sand",
              "rocky shore", "waves", "outdoors"],
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
    ("beach", r"海滩|沙滩|海边|海岸|海面|海风|海水|海浪|海平线|浪花|"
              r"沙地|礁石|beach|ocean|sea\b|shore|coast|sand"),
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


_WEIGHT_TAG_RE = re.compile(
    r"\(\s*(?:\d+(?:\.\d+)?|[^()]*?:\s*\d+(?:\.\d+)?)\s*\)\s*$")


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


def _end_keep_tags(tags: list[str], profile: CharacterProfile | None = None
                   ) -> set[str]:
    weighted = {tag for tag in tags if _has_weight(tag)}
    if weighted:
        return weighted
    if profile is not None:
        return {tag for tag in tags if _is_accessory(tag)}
    return {tag for tag in tags if not _clothing_key(tag)}


def normalize_shot_casts(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        script = str(shot.get("script") or shot.get("outline") or "")
        cast = normalize_cast(str(shot.get("cast") or ""), script)
        if cast:
            shot["cast"] = cast


def renumber_shots(shots: list[dict[str, Any]]) -> None:
    for index, shot in enumerate(shots, 1):
        if isinstance(shot, dict):
            shot["id"] = "%02d" % index


def normalize_cast(cast: str, script: str = "") -> str:
    value = str(cast or "").strip()
    script_text = str(script or "")
    if (re.search(r"\b1girl\s+solo\b", script_text, re.I)
            and not re.search(
                r"\b(?:1boy|2boys|male|boy)\b|男主",
                script_text, re.I)):
        return "1girl solo"
    text = "%s %s" % (value, script_text)
    low = text.lower()
    boy = bool(re.search(
        r"(?:1boy|2boys|男主|男性|男人|我|你)", text, re.I))
    many_girls = bool(re.search(
        r"(?:2girls|multiple girls|two girls|两个女|两名女)", text, re.I))
    cast_without_boy = re.sub(
        r"(?:1boy|2boys|男主|男性|男人|我|你|solo|\+)", "", value,
        flags=re.I).strip()
    girl = bool(re.search(
        r"(?:1girl|2girls|女主|女性|女孩|她)", text, re.I)) or bool(
        cast_without_boy)
    if many_girls:
        return "2girls" + (" 1boy" if boy else "")
    if boy and girl:
        return "1girl 1boy"
    if boy:
        return "1boy solo"
    if girl:
        return "1girl solo"
    return value


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


_LOWER_BODY_CLOTHING = {
    "fishnet", "pantyhose", "legwear", "stockings", "thighhigh", "leggings",
    "socks", "panties", "underwear", "thong", "bikini", "skirt", "pants",
    "jeans", "shorts", "heels", "boots", "shoes", "sandals", "slippers",
    "garter",
}
_UPPER_BODY_CLOTHING = {
    "bra", "shirt", "vest", "blazer", "jacket", "coat", "cardigan",
    "blouse", "sweater", "hoodie", "tank top", "camisole", "crop top",
    "top", "corset", "bustier", "necktie", "scarf", "collar",
}
_INTIMATE_CLOTHING = {
    "bra", "panties", "underwear", "thong", "lingerie", "pasties", "bikini",
    "swimsuit", "leotard", "bodysuit", "corset", "bustier", "garter",
    "pantyhose", "stockings", "thighhigh", "fishnet", "legwear",
}
_TOPLESS_REMOVE = _UPPER_BODY_CLOTHING - {"necktie", "scarf", "collar"}
_BOTTOMLESS_REMOVE = {
    "panties", "underwear", "thong", "bikini", "skirt", "pants", "jeans",
    "shorts",
}


def _only_scope(text: str) -> str:
    if re.search(r"上半身|上身|upper body", str(text or ""), re.I):
        return "upper"
    if re.search(r"下半身|下身|lower body", str(text or ""), re.I):
        return "lower"
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
    r"(?:脱掉|脱去|脱下|褪下|褪去|完全脱下|完全褪到|全部脱去|全部脱下|"
    r"takes? off|took off|pulls? off|steps? out of|removes?|"
    r"peels? off|rips? off|tears? off)"
)
_CLOTHING_RESTORE_RE = (
    r"(?:穿回|穿好|拉回|拉上|提上|整理好|整理|扣好|扣上|拨回|拨正|"
    r"复位|盖上|遮住|put back on|pulls? (?:it )?back|pulls? (?:it )?up|"
    r"adjusts?|fixes?|covers?|tucks?|restores?|dress(?:es|ed)?)"
)
_NEGATION_RE = re.compile(
    r"(?:未|没|没有|不|别|无需|不用|not|never|without|no)\s*$", re.I)


def _is_negated(text: str, index: int) -> bool:
    return bool(_NEGATION_RE.search(text[max(0, index - 8):index]))


def _restores_item(beat: str, key: str) -> bool:
    aliases = dict(_CLOTHING_KEYS).get(key, ())
    if not aliases:
        return False
    item = "(?:" + "|".join(aliases) + ")"
    text = str(beat or "")
    pattern = re.compile(
        r"(?:%s).{0,24}%s|%s.{0,24}(?:%s)" % (
            _CLOTHING_RESTORE_RE, item, item, _CLOTHING_RESTORE_RE),
        re.I)
    marker_re = re.compile(_CLOTHING_RESTORE_RE, re.I)
    for match in pattern.finditer(text):
        if _is_negated(text, match.start()):
            continue
        marker = marker_re.search(match.group(0))
        if marker and _is_negated(text, match.start() + marker.start()):
            continue
        return True
    return False


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
    for beat_index, beat in enumerate(beats):
        only = re.search(r"(?:只剩|只穿)(.*)", beat)
        if _is_full_nude(beat):
            near_end = beat_index >= max(0, len(beats) - 2)
            if near_end:
                worn = _end_keep_tags(initial)
                removed.update(tag for tag in known.values()
                               if tag not in worn)
            else:
                for key, tag in list(known.items()):
                    if (_removes_item(beat, key)
                            or _removes_tag(beat, tag)):
                        worn.discard(tag)
                        removed.add(tag)
        elif only:
            chosen = set(accessories)
            only_text = only.group(1)
            for key, patterns in _CLOTHING_KEYS:
                tag = known.get(key)
                if (tag and tag not in removed
                        and any(re.search(p, only_text, re.I) for p in patterns)):
                    chosen.add(tag)
            if chosen != accessories:
                scope = _only_scope(beat)
                kept = set(chosen)
                for tag in list(worn):
                    clothing_key = _clothing_key(tag)
                    if tag in chosen:
                        continue
                    if (scope == "upper"
                            and clothing_key in _LOWER_BODY_CLOTHING):
                        kept.add(tag)
                    elif (scope == "lower"
                          and clothing_key in _UPPER_BODY_CLOTHING):
                        kept.add(tag)
                    elif clothing_key:
                        removed.add(tag)
                worn = kept
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
_APPEARANCE_SKIP_NOUNS = {
    "ornament", "clip", "hairclip", "bow", "ribbon", "tie", "glasses",
    "earrings", "earring", "piercing", "tattoo", "scar",
}
_APPEARANCE_SKIP_PREFIXES = ("pubic", "hairclip", "hair ornament")
_BODY_TRAIT_GROUPS = (
    ("chest", ("flat chest", "small breasts", "medium breasts", "large breasts",
               "huge breasts", "gigantic breasts")),
    ("height", ("petite", "short", "tall", "very tall")),
    ("build", ("skinny", "slim", "slender", "curvy", "thick", "chubby", "fat",
               "muscular", "toned")),
    ("skin", ("pale skin", "fair skin", "light skin", "tan skin", "dark skin",
              "brown skin")),
)


_TOP_SECTION_RE = re.compile(
    r"^(?:角色设定|角色标签|角色|人物设定|人物|外貌身材|角色外貌|人物外貌|外貌|"
    r"外形|身材|体型|初始服装|初始装扮|服装|大场景|场景|剧情|故事|额外|画风)"
    r"\s*[:：]")


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


def _only_mentions_clothing(text: str) -> bool:
    value = str(text or "")
    if any(re.search(pattern, value, re.I)
           for _key, patterns in _CLOTHING_KEYS for pattern in patterns):
        return True
    return any(re.search(pattern, value, re.I)
               for pattern in _ACCESSORY_PATTERNS)


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
                near_end = beat_index >= max(0, len(beats) - 2)
                if near_end:
                    keep = _end_keep_tags(
                        profile.initial_clothing, profile)
                    current[key] = {
                        tag for tag in profile.initial_clothing
                        if tag in keep and tag not in removed[key]}
                    removed[key].update(
                        tag for tag in profile.initial_clothing
                        if tag not in keep)
                else:
                    for tag in list(current[key]):
                        clothing_key = _clothing_key(tag)
                        if (_removes_item(beat, clothing_key)
                                or _removes_tag(beat, tag)):
                            current[key].discard(tag)
                            removed[key].add(tag)
            elif (key in only_targets
                  and _only_mentions_clothing(only_targets[key])):
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
                scope = _only_scope(beat)
                kept = set(chosen)
                for tag in current[key]:
                    clothing_key = _clothing_key(tag)
                    if tag in chosen:
                        continue
                    if (scope == "upper"
                            and clothing_key in _LOWER_BODY_CLOTHING):
                        kept.add(tag)
                    elif (scope == "lower"
                          and clothing_key in _UPPER_BODY_CLOTHING):
                        kept.add(tag)
                    elif not _is_accessory(tag):
                        removed[key].add(tag)
                current[key] = kept
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
    present = (shot or {}).get("present_characters")
    if isinstance(present, list):
        wanted = {str(name).strip().lower() for name in present
                  if str(name).strip()}
        chosen = [profile for profile in profiles
                  if profile.name.lower() in wanted or profile.key.lower() in wanted]
        if chosen:
            return chosen
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


def _appearance_key(tag: str) -> str:
    return re.sub(r"\s+", " ", str(tag).lower().replace("_", " ")
                  .replace("-", " ")).strip()


_APPEARANCE_COLOR_RE = re.compile(
    r"\b(?:red|pink|blonde|white|silver|blue|purple|orange|green|brown|"
    r"black|grey|gray|golden|amber|violet|cyan|magenta|multicolored|"
    r"heterochromia)\b", re.I)


def _appearance_group(tag: str) -> tuple[str, set[str]] | None:
    low = _appearance_key(tag)
    if not low or any(prefix in low for prefix in _APPEARANCE_SKIP_PREFIXES):
        return None
    words = re.findall(r"[a-z][a-z-]*", low)
    if not words or words[-1] in _APPEARANCE_SKIP_NOUNS:
        return None
    if words[-1] == "eyes" and not _APPEARANCE_COLOR_RE.search(low):
        return None
    return words[-1], set(words[:-1])


_FULL_NUDE_RE = re.compile(
    r"^(?:completely nude|fully nude|full nude|completely naked|fully naked|"
    r"full naked|nude|naked)$", re.I)


def _spaced_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", str(tag).lower().replace("_", " ")
                  .replace("-", " ")).strip()


def _is_full_nude_tag(tag: str) -> bool:
    return bool(_FULL_NUDE_RE.match(_spaced_tag(tag)))


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
    group = _appearance_group(tag)
    if group:
        noun, modifiers = group
        for profile in present:
            same = [
                item for item in (_appearance_group(value)
                                  for value in profile.appearance)
                if item is not None and item[0] == noun
            ]
            if not same:
                continue
            if not modifiers:
                continue
            if any(modifiers & locked for _name, locked in same):
                return False
            if any(not locked for _name, locked in same):
                continue
            return True
    key = _appearance_key(tag)
    for _group, terms in _BODY_TRAIT_GROUPS:
        if key not in terms:
            continue
        locked = [
            _appearance_key(tag) for profile in present
            for tag in profile.appearance
            if _appearance_key(tag) in terms
        ]
        if locked and key not in locked:
            return True
        break
    return False


def filter_locked_appearance(tags: list[str], locked: list[str]) -> list[str]:
    """Drop appearance tags that would conflict with an explicit locked look."""
    locked_profile = CharacterProfile(
        key="locked", appearance=[tag for tag in locked if tag])
    return [tag for tag in tags if not _appearance_conflicts(tag, [locked_profile])]


def _shot_clothing_details(shot: dict[str, Any] | None,
                           profiles: list[CharacterProfile]
                           ) -> dict[str, set[str]]:
    raw = (shot or {}).get("clothing_details")
    if not isinstance(raw, dict):
        return {profile.key: set() for profile in profiles}
    result: dict[str, set[str]] = {}
    for profile in profiles:
        value = raw.get(profile.key)
        if isinstance(value, (list, tuple, set)):
            result[profile.key] = {str(tag).strip() for tag in value if str(tag).strip()}
        elif str(value or "").strip():
            result[profile.key] = {tag.strip() for tag in str(value).split(",")
                                   if tag.strip()}
        else:
            result[profile.key] = set()
    return result


def _detail_tag_key(tag: str) -> str:
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", _spaced_tag(tag))
    return " ".join(sorted(words))


def _detail_family(tag: str) -> str:
    low = _spaced_tag(tag)
    if any(word in low for word in _DAMAGE_WORDS):
        return "damage"
    if _is_clothing_state_tag(tag) or any(
            word in low for word in _HALF_OFF_WORDS):
        return "state"
    return "other"


def update_clothing_details(profiles: list[CharacterProfile],
                            states: dict[str, set[str]],
                            present: list[CharacterProfile], prompt: str,
                            previous: dict[str, set[str]] | None = None,
                            script: str = ""
                            ) -> dict[str, set[str]]:
    result = {
        profile.key: set((previous or {}).get(profile.key) or set())
        for profile in profiles
    }
    worn_by_profile = {
        profile.key: {_clothing_key(tag) for tag in (states.get(profile.key) or set())
                      if _clothing_key(tag)}
        for profile in present
    }
    owners: dict[str, list[CharacterProfile]] = {}
    for profile in present:
        for key in worn_by_profile[profile.key]:
            owners.setdefault(key, []).append(profile)

    def owner(profile: CharacterProfile, key: str) -> bool:
        candidates = owners.get(key) if key else [
            item for item in present if worn_by_profile[item.key]]
        return bool(candidates) and candidates[0].key == profile.key

    reset_to_full = _script_resets_to_full(script)
    for profile in present:
        worn_keys = worn_by_profile[profile.key]
        previous_tags = []
        if not reset_to_full:
            for tag in result[profile.key]:
                key = _clothing_key(tag)
                if key:
                    if key in worn_keys and owner(profile, key):
                        previous_tags.append(tag)
                elif worn_keys and owner(profile, ""):
                    previous_tags.append(tag)
        current_tags = []
        for tag in _split_tags(prompt):
            if not _is_clothing_state_tag(tag):
                continue
            if reset_to_full and any(
                    word in tag.lower().replace("_", " ")
                    for word in _HALF_OFF_WORDS):
                continue
            key = _clothing_key(tag)
            if ((key and key in worn_keys) or (not key and worn_keys)) \
                    and owner(profile, key):
                current_tags.append(tag)
        current_families = {
            (_clothing_key(tag), _detail_family(tag))
            for tag in current_tags
        }
        merged = [
            tag for tag in previous_tags
            if (_clothing_key(tag), _detail_family(tag))
            not in current_families
        ]
        merged.extend(current_tags)
        order: list[str] = []
        chosen: dict[str, str] = {}
        for tag in merged:
            key = _detail_tag_key(tag)
            if not key:
                continue
            if key not in chosen:
                order.append(key)
            chosen[key] = tag
        result[profile.key] = {chosen[key] for key in order}
    return result


_MALE_PROMPT_CLOTHING = (
    "clothed male", "male clothing", "male outfit", "male uniform",
    "male suit", "casual clothes", "male casual clothes", "school uniform",
    "open fly", "unzipped pants", "zipper", "male clothes", "boxers",
    "briefs", "necktie", "belt buckle",
)
_GENERIC_CLOTHING_DAMAGE = (
    "torn clothes", "clothes pull", "half-off clothes",
    "clothing damage",
)
_MULTI_MALE_TAGS = (
    "2boys", "multiple boys", "extra boy", "duplicate boy", "cloned boy",
    "two male heads", "extra male head", "second male head",
)
_MULTI_FEMALE_TAGS = (
    "2girls", "multiple girls", "extra girl", "duplicate girl", "cloned girl",
    "two female heads", "extra female head", "duplicate female head",
    "second female head",
)
_DAMAGE_WORDS = (
    "torn", "ripped", "damaged", "tear", "crotch hole", "pantyhose hole",
    "破", "撕", "裂", "洞", "扯开", "拉破",
)


def _tag_weight_key(tag: str) -> tuple[str, bool]:
    value = str(tag or "").strip()
    match = re.fullmatch(r"\((.+?):\d+(?:\.\d+)?\)", value)
    if match:
        value = match.group(1)
    key = re.sub(r"[\s_\-]+", " ", value.lower()).strip()
    return key, bool(match)


def _dedupe_weighted_clothing(tags: list[str]) -> list[str]:
    order: list[str] = []
    chosen: dict[str, str] = {}
    for tag in tags:
        key, weighted = _tag_weight_key(tag)
        if not key:
            continue
        if key not in chosen:
            chosen[key] = tag
            order.append(key)
        elif weighted and not _tag_weight_key(chosen[key])[1]:
            chosen[key] = tag
    return [chosen[key] for key in order]


_HALF_OFF_WORDS = (
    "pulled down", "pulled aside", "half-off", "half off", "around one leg",
    "around one ankle", "around ankle", "around ankles", "around thigh",
    "around thighs", "around knee", "around knees", "around calf",
    "around calves", "around shin", "around shins", "around foot",
    "around feet", "around leg", "around legs", "one leg removed",
    "off shoulder", "bra pull", "skirt lift", "panties aside", "slid down",
    "partially removed",
)
_LEGWEAR_KEYS = {
    "fishnet", "pantyhose", "legwear", "stockings", "thighhigh",
    "leggings", "socks",
}
_HALF_OFF_SCRIPT_WORDS = (
    "半脱", "半褪", "褪在", "褪到", "褪下", "卷到", "卷在", "拉到",
    "拉下", "拉上", "拉回", "拨到", "拨开", "滑落", "滑到", "滑下",
    "松开", "解开", "脱到", "掀起", "掀开", "堆在", "堆到", "歪到",
    "挂在", "挂到", "蹬到", "蹬下", "扯到", "扯下", "拽到", "拽下",
    "卡在", "卡到", "pull down", "pulled down", "half-off", "half off",
    "around one leg", "around thigh", "around knee", "around ankle",
    "around calf", "slid down", "partially removed",
)


def _script_has_half_off(script: str) -> bool:
    text = str(script or "").lower()
    return bool(text) and any(
        word.lower() in text for word in _HALF_OFF_SCRIPT_WORDS)


_FULL_CLOTHING_SCRIPT_WORDS = (
    "仍完整穿着", "完整穿着", "穿好衣服", "穿回", "重新穿",
    "整理好衣服", "把衣服拉好", "无裸露",
)


def _script_resets_to_full(script: str) -> bool:
    text = str(script or "").lower()
    if not text:
        return False
    for word in _FULL_CLOTHING_SCRIPT_WORDS:
        start = text.find(word.lower())
        while start >= 0:
            if not _is_negated(text, start):
                return True
            start = text.find(word.lower(), start + 1)
    return False


def _half_off_tags(tags: list[str]) -> list[str]:
    result = list(tags)
    states = [
        tag for tag in list(result)
        if any(word in tag.lower().replace("_", " ")
               for word in _HALF_OFF_WORDS)]
    legwear_modes: set[str] = set()
    for state in states:
        key = _clothing_key(state)
        if not key:
            continue
        base = next((tag for tag in result
                     if _clothing_key(tag) == key
                     and tag != state
                     and not _is_clothing_state_tag(tag)
                     and not any(word in tag.lower().replace("_", " ")
                                 for word in _HALF_OFF_WORDS)), None)
        if not base:
            continue
        base_text = base.replace("_", " ").strip()
        state_text = state.replace("_", " ").strip()
        weight = ""
        match = re.fullmatch(r"\((.+?):(\d+(?:\.\d+)?)\)", base_text)
        if match:
            base_text = match.group(1).strip()
            weight = match.group(2)
        if key in _LEGWEAR_KEYS:
            low_state = state_text.lower()
            if any(word in low_state for word in (
                    "one leg", "one ankle", "one-leg", "single leg")):
                mode = "one_leg"
                combined = "%s around one leg" % base_text
            elif "knee" in low_state:
                mode = "knees"
                combined = "%s around knees" % base_text
            elif any(word in low_state for word in ("calf", "calves", "shin")):
                mode = "calves"
                combined = "%s around calves" % base_text
            elif any(word in low_state for word in ("ankle", "foot", "feet")):
                mode = "ankles"
                combined = "%s around ankles" % base_text
            else:
                mode = "thighs"
                combined = "%s around thighs" % base_text
            legwear_modes.add(mode)
        else:
            key_text = key.replace("_", " ")
            if key_text in state_text.lower():
                combined = re.sub(re.escape(key_text), base_text, state_text,
                                  count=1, flags=re.I)
            else:
                combined = "%s %s" % (base_text, state_text)
        if weight:
            combined = "(%s:%s)" % (combined, weight)
        result = [tag for tag in result if tag not in (state, base)]
        result.append(combined)
    if "thighs" in legwear_modes:
        for tag in ("pantyhose pulled down", "upper thighs bare",
                    "thighs exposed"):
            if tag not in result:
                result.append(tag)
    if "knees" in legwear_modes:
        for tag in ("pantyhose around knees", "lower legs covered"):
            if tag not in result:
                result.append(tag)
    if "calves" in legwear_modes:
        for tag in ("pantyhose around calves", "lower legs covered"):
            if tag not in result:
                result.append(tag)
    if "ankles" in legwear_modes:
        for tag in ("pantyhose around ankles", "lower legs covered"):
            if tag not in result:
                result.append(tag)
    if "one_leg" in legwear_modes:
        for tag in ("one leg out", "asymmetrical legwear"):
            if tag not in result:
                result.append(tag)
    return result


def _finalize_shot_prompt(shot: dict[str, Any],
                          female_clothing: str | None = None,
                          preserve_clothing: bool = False) -> None:
    before_prompt = str(shot.get("prompt") or "")
    tags = [tag.strip() for tag in before_prompt.split(",")
            if tag.strip()]
    text = " ".join(tags).lower()
    double = "1girl" in text and "1boy" in text
    script_text = str(shot.get("script") or "").lower()
    detail_text = " ".join(
        str(value) for value in (shot.get("clothing_details") or {}).values())
    damage_script = any(word in script_text for word in _DAMAGE_WORDS)
    carried_damage = any(word in detail_text.lower() for word in _DAMAGE_WORDS)
    damage_state = damage_script or carried_damage
    if female_clothing is None:
        female_clothing = str(shot.get("clothing") or "")
    female_clothing = female_clothing.lower()
    female_exact = {
        _tag_weight_key(item)[0] for item in female_clothing.split(",")
        if item.strip()}
    female_keys = {_clothing_key(item) for item in female_exact
                   if _clothing_key(item)}
    cast = str(shot.get("cast") or "").lower()
    allow_two_females = bool(re.search(
        r"(?:\b2\s*girls\b|\btwo\s+girls\b|\bmultiple\s+girls\b)", cast))
    cleaned: list[str] = []
    for tag in tags:
        low = tag.lower()
        if low.startswith("then ") or " then " in low:
            continue
        if double and low in (
                "solo", "solo focus", "solo female", "female solo",
                "solo male", "male solo"):
            continue
        if not preserve_clothing and script_text and not damage_state and any(
                word in low for word in _DAMAGE_WORDS):
            continue
        if any(word in low for word in _MULTI_MALE_TAGS):
            continue
        if not allow_two_females and any(
                word in low for word in _MULTI_FEMALE_TAGS):
            continue
        if double and low == "solo focus":
            continue
        if double and any(word in low for word in _MALE_PROMPT_CLOTHING):
            continue
        if not preserve_clothing and double and _clothing_key(tag):
            if (_tag_weight_key(tag)[0] not in female_exact
                    and not (_is_clothing_state_tag(tag)
                             and _clothing_key(tag) in female_keys)):
                continue
        if not preserve_clothing and female_clothing and low in (
                "completely nude", "fully nude", "full nude", "nude", "naked"):
            continue
        if not preserve_clothing and not female_clothing and (
                _clothing_key(tag) or _is_clothing_state_tag(tag)):
            continue
        cleaned.append(tag)
    if not preserve_clothing:
        if not female_clothing and "1girl" in text:
            cleaned.append("completely nude")
        elif (female_clothing and damage_state and any(
                word in text for word in (
                    "pussy", "crotch", "breasts out", "one breast out",
                    "nipples"))):
            cleaned.extend(_GENERIC_CLOTHING_DAMAGE)
        script = str(shot.get("script") or "")
        carried_half_off = any(
            word in detail_text.lower().replace("_", " ")
            for word in _HALF_OFF_WORDS)
        keep_half_off = (
            not script
            or _script_has_half_off(script)
            or (carried_half_off and not _script_resets_to_full(script)))
        if script and not keep_half_off:
            cleaned = [
                tag for tag in cleaned
                if not any(word in tag.lower().replace("_", " ")
                           for word in _HALF_OFF_WORDS)]
        else:
            cleaned = _half_off_tags(cleaned)
    cleaned = _dedupe_weighted_clothing(cleaned)
    seen: set[str] = set()
    result: list[str] = []
    for tag in cleaned:
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(tag)
    shot["prompt"] = ", ".join(result)
    trace_event("prompt.finalize", {
        "id": str(shot.get("id") or ""),
        "before": before_prompt,
        "after": shot["prompt"],
        "female_clothing": female_clothing,
        "preserve_clothing": preserve_clothing,
    })


_OUTFIT_CHANGE_WORDS = (
    "换装", "换衣", "换衣服", "换上", "换上新的", "换一套", "穿上",
    "套上", "披上", "戴上", "新衣", "新的衣服", "另一套", "change clothes",
    "changed clothes", "put on", "wearing a new",
)
_OUTFIT_REPAIR_WORDS = (
    "换新", "新的", "补好", "修好", "完好无损", "破口消失", "换成新的",
    "换了新的", "repaired", "brand new",
)
_STATE_RESET_WORDS = (
    "拉正", "穿好", "整理好", "拉回", "拨正", "调整好", "复位",
    "重新穿好", "put back on", "adjust back",
)


def _script_allows_state_reset(script: str) -> bool:
    text = str(script or "").lower()
    return bool(text) and any(word in text for word in _STATE_RESET_WORDS)


def _script_allows_outfit_change(script: str) -> bool:
    text = str(script or "").lower()
    return bool(text) and any(word in text for word in _OUTFIT_CHANGE_WORDS)


def _script_allows_repair(script: str) -> bool:
    text = str(script or "").lower()
    return bool(text) and any(word in text for word in _OUTFIT_REPAIR_WORDS)


def stabilize_clothing_sequence(shots: list[dict[str, Any]],
                                profiles: list[CharacterProfile]) -> None:
    girls = [profile for profile in profiles if profile.gender == "girl"]
    if not girls:
        return
    profile = girls[0]
    current: dict[str, str] = {
        key: tag for tag in profile.initial_clothing
        if (key := _clothing_key(tag))
    }
    current_repr = dict(current)
    damaged: set[str] = set()
    for shot in shots:
        script = str(shot.get("script") or shot.get("outline") or "")
        change = _script_allows_outfit_change(script)
        repair = _script_allows_repair(script)
        state_reset = _script_allows_state_reset(script)
        for key in list(current):
            if _removes_item(script, key) and not change:
                current.pop(key, None)
                current_repr.pop(key, None)
                damaged.discard(key)
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        nude = any(_is_full_nude_tag(tag) for tag in tags)
        if nude:
            current.clear()
            current_repr.clear()
            damaged.clear()
        kept: list[str] = []
        present_keys: set[str] = set()
        for tag in tags:
            key = _clothing_key(tag)
            if not key:
                kept.append(tag)
                continue
            is_damage = any(word in tag.lower() for word in _DAMAGE_WORDS)
            is_state = _is_clothing_state_tag(tag) and not is_damage
            if key not in current:
                if not change:
                    continue
                current[key] = tag
                current_repr[key] = tag
            elif is_state:
                current_repr[key] = tag
            elif is_damage:
                damaged.add(key)
            elif (not state_reset and _is_clothing_state_tag(
                    current_repr.get(key, ""))):
                continue
            elif state_reset or change:
                current[key] = tag
                current_repr[key] = tag
                damaged.discard(key)
            present_keys.add(key)
            if is_damage:
                damaged.add(key)
            kept.append(tag)
        if repair:
            damaged.clear()
        if damaged:
            kept = [
                tag for tag in kept
                if not (_clothing_key(tag) in damaged
                        and any(word in tag.lower() for word in (
                            "intact", "pristine", "完好", "完整")))
            ]
            for key in sorted(damaged):
                if any(_clothing_key(tag) == key
                       and any(word in tag.lower() for word in _DAMAGE_WORDS)
                       for tag in kept):
                    continue
                base = _tag_weight_key(current.get(key, key))[0]
                kept.append("torn %s" % base)
        for key, tag in current_repr.items():
            if key not in present_keys:
                kept.append(tag)
        shot["prompt"] = ", ".join(kept)


_MALE_HIDDEN_TAGS = {
    "male collar", "hand on male collar", "hand on collar", "collar",
}


def _drop_male_visibility_conflicts(tags: list[str]) -> list[str]:
    low_tags = [tag.lower().replace("_", " ").strip() for tag in tags]
    hidden = any(
        tag in ("male head out of frame", "male face out of frame",
                "faceless male")
        for tag in low_tags)
    if not hidden:
        return tags
    kept: list[str] = []
    for tag, low in zip(tags, low_tags):
        if ("out of frame" not in low
                and any(word in low for word in (
                    "male face", "male head", "male facial features",
                    "handsome male"))):
            continue
        kept.append(tag)
    return kept


def _tags_from_value(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(tag).strip() for tag in value if str(tag).strip()}
    if str(value or "").strip():
        return {tag.strip() for tag in str(value).split(",") if tag.strip()}
    return set()


def _profile_clothing_details(shot: dict[str, Any],
                              profile: CharacterProfile) -> set[str]:
    raw = (shot.get("clothing_details") or {}).get(profile.key)
    return _tags_from_value(raw)


def _profile_worn_clothing(shot: dict[str, Any],
                           profile: CharacterProfile) -> set[str]:
    raw = (shot.get("character_states") or {}).get(profile.key)
    return _tags_from_value(raw)


_STATE_ACTION_WORDS = (
    "adjusting", "pulling", "putting on", "taking off", "removing",
    "sliding", "lifting", "hiking", "tugging", "breasts out",
    "one breast out",
)


_LAYER_ACTION_RE = re.compile(
    r"\b(?:hand|fingers?|finger)\s+(?:inside|under|in)\b|"
    r"\b(?:inside|under)\s+(?:panties|pantyhose|bra|shirt|uniform|clothes|"
    r"underwear|skirt)\b", re.I)


def _is_layer_action_tag(tag: str) -> bool:
    return bool(_LAYER_ACTION_RE.search(str(tag or "").replace("_", " ")))


def _is_state_or_damage(tag: str) -> bool:
    low = tag.lower().replace("_", " ")
    return (_is_clothing_state_tag(tag) or _is_off_body_tag(tag)
            or any(word in low for word in _DAMAGE_WORDS + _STATE_ACTION_WORDS))


def _is_damage_tag(tag: str) -> bool:
    low = tag.lower().replace("_", " ")
    return any(word in low for word in _DAMAGE_WORDS)


def infer_missing_clothing_details(shots: list[dict[str, Any]],
                                   profiles: list[CharacterProfile]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        details = shot.get("clothing_details")
        if not isinstance(details, dict):
            details = None
        prompt_tags = [tag.strip() for tag in str(
            shot.get("prompt") or "").split(",") if tag.strip()]
        for profile in profiles:
            keys = {_clothing_key(tag) for tag in profile.initial_clothing
                    if _clothing_key(tag)}
            initial_text = " ".join(
                _tag_weight_key(tag)[0] for tag in profile.initial_clothing)
            state_tags = [
                tag for tag in prompt_tags
                if _is_state_or_damage(tag)
                and not (profile.gender != "boy" and _is_male_state(tag))
                and (
                    _clothing_key(tag) in keys
                    or (_is_off_body_tag(tag)
                        and bool(_item_head(_off_body_item(tag)))
                        and _item_head(_off_body_item(tag)) in initial_text))]
            if not state_tags and profile.gender == "girl":
                state_tags = [
                    tag for tag in prompt_tags
                    if _clothing_key(tag) and _is_state_or_damage(tag)
                    and not _is_male_state(tag)]
            if not state_tags:
                continue
            if details is None:
                details = {}
                shot["clothing_details"] = details
            existing = _tags_from_value(details.get(profile.key))
            merged = list(existing)
            seen = {tag.lower() for tag in existing}
            for tag in state_tags:
                if tag.lower() not in seen:
                    seen.add(tag.lower())
                    merged.append(tag)
            details[profile.key] = ", ".join(merged)


def backfill_clothing_details(shots: list[dict[str, Any]],
                              premise: str) -> None:
    profiles = parse_character_profiles(premise)
    if profiles:
        infer_missing_clothing_details(shots, profiles)


def sync_clothing_state_to_prompt(shots: list[dict[str, Any]],
                                  profiles: list[CharacterProfile]) -> None:
    removed_items: set[str] = set()
    weighted_keys = {
        _clothing_key(_tag_weight_key(tag)[0])
        for profile in profiles for tag in profile.initial_clothing
        if _has_weight(tag)}
    weighted_keys.discard("")
    active_states: dict[str, dict[str, str]] = {
        profile.key: {} for profile in profiles}
    damaged_keys: dict[str, set[str]] = {
        profile.key: set() for profile in profiles}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        before_prompt = str(shot.get("prompt") or "")
        tags = [tag.strip() for tag in before_prompt.split(",")
                if tag.strip()]
        script = str(shot.get("script") or shot.get("outline") or "")

        for tag in tags:
            if _is_off_body_tag(tag) and not _is_male_state(tag):
                item = _off_body_item(tag)
                if item:
                    removed_items.add(item)
        for profile in profiles:
            for tag in _profile_clothing_details(shot, profile):
                if _is_off_body_tag(tag) and not _is_male_state(tag):
                    item = _off_body_item(tag)
                    if item:
                        removed_items.add(item)
        for item in list(removed_items):
            key = _clothing_key(item)
            if ((key in _INTIMATE_CLOTHING or key in weighted_keys)
                    and _script_reintroduces_item(script, item)):
                removed_items.discard(item)

        nude = any(
            _is_full_nude_tag(tag) and "male" not in tag.lower()
            for tag in tags)
        for profile in profiles:
            state_tags = set(_drop_mutually_exclusive_states(
                list(_profile_clothing_details(shot, profile))))
            active = active_states[profile.key]
            for tag in state_tags:
                key = _clothing_key(tag)
                if not key:
                    continue
                if _is_damage_tag(tag):
                    damaged_keys[profile.key].add(key)
                    active[key] = tag
                elif (key not in damaged_keys[profile.key]
                      and (_is_clothing_state_tag(tag)
                           or _is_off_body_tag(tag))):
                    active[key] = tag
            restore_all = _script_resets_to_full(script)
            restored_keys = set()
            for key in list(active):
                if key not in _INTIMATE_CLOTHING and key not in weighted_keys:
                    continue
                if key in damaged_keys[profile.key]:
                    continue
                if restore_all or _restores_item(script, key):
                    active.pop(key, None)
                    restored_keys.add(key)
            state_tags = {
                tag for tag in state_tags
                if _clothing_key(tag) not in restored_keys}
            state_tags.update(active.values())
            state_tags = set(_drop_mutually_exclusive_states(
                list(state_tags)))
            details = shot.get("clothing_details")
            if isinstance(details, dict):
                details[profile.key] = ", ".join(sorted(state_tags))
            worn_tags = _profile_worn_clothing(shot, profile)
            worn_tags = {
                tag for tag in worn_tags
                if not any(_tag_matches_removed_item(tag, item)
                           for item in removed_items)}
            for key in restored_keys:
                base = next((
                    tag for tag in profile.initial_clothing
                    if _clothing_key(tag) == key), "")
                if base:
                    worn_tags.add(base)
            removed_keys = {
                _clothing_key(tag) for tag in state_tags
                if _is_displaced_state(tag) and _clothing_key(tag)}
            worn_tags = {tag for tag in worn_tags
                         if _clothing_key(tag) not in removed_keys}
            if isinstance(shot.get("character_states"), dict):
                shot["character_states"][profile.key] = ", ".join(
                    sorted(worn_tags))
            keys = {_clothing_key(tag) for tag in state_tags | worn_tags
                    if _clothing_key(tag)}
            if not keys:
                continue
            worn_keys = {_clothing_key(tag) for tag in worn_tags
                         if _clothing_key(tag)}
            if nude:
                tags = [tag for tag in tags if not _clothing_key(tag)]
                continue
            cleaned: list[str] = []
            for tag in tags:
                key = _clothing_key(tag)
                if not key:
                    if _is_state_or_damage(tag) and tag not in state_tags:
                        continue
                    cleaned.append(tag)
                    continue
                if key not in keys:
                    continue
                if _is_state_or_damage(tag):
                    if tag not in state_tags:
                        continue
                elif key not in worn_keys:
                    continue
                cleaned.append(tag)
            for tag in state_tags:
                if _is_off_body_tag(tag):
                    continue
                if tag not in cleaned:
                    cleaned.append(tag)
            for tag in worn_tags:
                key = _clothing_key(tag)
                if not key:
                    continue
                base_name = _tag_weight_key(tag)[0].lower()
                has_base = any(
                    _tag_weight_key(item)[0].lower() == base_name
                    for item in cleaned)
                if not has_base:
                    cleaned.append(tag)
            tags = cleaned
        tags = [
            tag for tag in tags
            if not _is_off_body_tag(tag)
            and not any(_tag_matches_removed_item(tag, item)
                        for item in removed_items)]
        tags = _drop_male_visibility_conflicts(tags)
        tags = [tag for tag in tags
                if tag.lower() not in _MALE_HIDDEN_TAGS]
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            key = tag.lower()
            if key and key not in seen:
                seen.add(key)
                result.append(tag)
        shot["prompt"] = ", ".join(result)
        trace_event("clothing.sync", {
            "id": str(shot.get("id") or ""),
            "before": before_prompt,
            "after": shot["prompt"],
            "clothing_details": shot.get("clothing_details") or {},
            "character_states": shot.get("character_states") or {},
        })


def _is_displaced_state(tag: str) -> bool:
    if _is_off_body_tag(tag):
        return True
    low = _spaced_tag(tag)
    return (any(word in low for word in _DAMAGE_WORDS)
            or bool(re.search(
                r"\b(?:around|at|bunched|hanging|removed|off)\b", low)))


def _drop_mutually_exclusive_states(tags: list[str]) -> list[str]:
    damaged_keys = {
        _clothing_key(tag) for tag in tags
        if _clothing_key(tag) and _is_damage_tag(tag)}
    if not damaged_keys:
        return list(tags)
    return [
        tag for tag in tags
        if not (_clothing_key(tag) in damaged_keys
                and _is_clothing_state_tag(tag)
                and not _is_damage_tag(tag))]


def sanitize_render_prompt(prompt: str) -> str:
    tags = _drop_mutually_exclusive_states(
        [tag.strip() for tag in str(prompt or "").split(",") if tag.strip()])
    removed_items: set[str] = set()
    for tag in tags:
        if _is_off_body_tag(tag) and not _is_male_state(tag):
            item = _off_body_item(tag)
            if item:
                removed_items.add(item)
    displaced_keys = {
        _clothing_key(tag) for tag in tags
        if _clothing_key(tag) and _is_displaced_state(tag)
        and not _is_male_state(tag)}
    faceless = any(
        tag.lower() in (
            "faceless male", "male face out of frame", "male head out of frame")
        for tag in tags)
    result: list[str] = []
    for tag in tags:
        if _is_male_state(tag) and _is_off_body_tag(tag):
            continue
        if _is_off_body_tag(tag):
            continue
        if any(_tag_matches_removed_item(tag, item)
               for item in removed_items):
            continue
        key = _clothing_key(tag)
        if (key and key in displaced_keys
                and not _is_displaced_state(tag)
                and not _is_state_or_damage(tag)):
            continue
        if (faceless and re.search(r"\bmale (?:face|head)\b", tag, re.I)
                and "out of frame" not in tag.lower()):
            continue
        result.append(tag)
    return ", ".join(result)


def apply_focus_weights(shots: list[dict[str, Any]],
                        weight: float = 1.2) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        focus = {
            _tag_weight_key(tag)[0]
            for tag in (shot.get("focus_tags") or [])
            if _tag_weight_key(tag)[0]}
        if not focus:
            continue
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        weighted: list[str] = []
        for tag in tags:
            clean, has_weight = _tag_weight_key(tag)
            if clean in focus and not has_weight:
                weighted.append("(%s:%g)" % (clean, weight))
            else:
                weighted.append(tag)
        shot["prompt"] = ", ".join(weighted)


_FULL_REMOVAL_RE = re.compile(
    r"\bremoved\b|\btaken off\b|\bpulled off\b|\boff body\b|"
    r"\bon (?:the )?(?:floor|sofa|cushion|chair|bed|ground)\b|"
    r"\bbarefoot\b|\bshoeless\b", re.I)


def _is_full_removal_tag(tag: str) -> bool:
    return bool(_FULL_REMOVAL_RE.search(str(tag or "")))


def enforce_weighted_core(shots: list[dict[str, Any]],
                          profiles: list[CharacterProfile]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        cast = str(shot.get("cast") or "").lower()
        if cast and "girl" not in cast:
            continue
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        changed = False
        for profile in profiles:
            weighted = [tag for tag in profile.initial_clothing
                        if _has_weight(tag)]
            if not weighted:
                continue
            keys = {_clothing_key(_tag_weight_key(tag)[0]) for tag in weighted}
            keys.discard("")
            if not keys:
                continue
            active = {
                _clothing_key(_tag_weight_key(tag)[0]) for tag in tags
                if not _is_full_removal_tag(tag)}
            nude_tags = [
                tag for tag in tags
                if _is_full_nude_tag(tag) and "male" not in tag.lower()]
            if nude_tags:
                tags = [tag for tag in tags if tag not in nude_tags]
                changed = True
            if keys & {"heels", "shoes", "footwear"}:
                filtered = [
                    tag for tag in tags
                    if _tag_weight_key(tag)[0].lower() not in (
                        "barefoot", "shoeless")]
                if filtered != tags:
                    tags = filtered
                    changed = True
            missing = keys - active
            if not missing:
                if changed:
                    shot["prompt"] = ", ".join(tags)
                    trace_event("wardrobe.weighted_core", {
                        "id": str(shot.get("id") or ""),
                        "prompt": shot["prompt"],
                    })
                continue
            removed = []
            kept = []
            for tag in tags:
                key = _clothing_key(_tag_weight_key(tag)[0])
                if key in missing and _is_full_removal_tag(tag):
                    removed.append(tag)
                    continue
                if (_is_full_nude_tag(tag) and "male" not in tag.lower()
                        and not key):
                    removed.append(tag)
                    continue
                kept.append(tag)
            if "heels" in missing or "shoes" in missing:
                kept = [tag for tag in kept
                        if _tag_weight_key(tag)[0].lower() not in (
                            "barefoot", "shoeless")]
            added: set[str] = set()
            for tag in weighted:
                key = _clothing_key(_tag_weight_key(tag)[0])
                if key in missing and key not in added:
                    kept.append(tag)
                    added.add(key)
            tags = kept
            changed = True
            for field in ("character_states", "clothing_details"):
                values = shot.get(field)
                if not isinstance(values, dict):
                    continue
                current = values.get(profile.key)
                if not isinstance(current, str):
                    continue
                values[profile.key] = ", ".join(
                    tag.strip() for tag in current.split(",")
                    if tag.strip()
                    and not (_clothing_key(_tag_weight_key(tag.strip())[0])
                             in missing
                             and _is_full_removal_tag(tag.strip())))
        if changed:
            shot["prompt"] = ", ".join(tags)
            trace_event("wardrobe.weighted_core", {
                "id": str(shot.get("id") or ""),
                "prompt": shot["prompt"],
            })


def _enforce_wardrobe_for_shot(shot: dict[str, Any],
                               profiles: list[CharacterProfile]) -> None:
    if not isinstance(shot, dict):
        return
    tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
            if tag.strip()]
    removed: set[str] = set()
    weighted_keys = {
        _clothing_key(_tag_weight_key(tag)[0])
        for profile in profiles for tag in profile.initial_clothing
        if _has_weight(tag)}
    weighted_keys.discard("")
    if weighted_keys:
        for tag in tags:
            key = _clothing_key(_tag_weight_key(tag)[0])
            if key and key not in weighted_keys:
                removed.add(tag)
        tags = [tag for tag in tags if tag not in removed]
        if removed:
            shot["prompt"] = ", ".join(tags)
    for profile in profiles:
        if not profile.initial_clothing:
            continue
        weighted = {tag for tag in profile.initial_clothing if _has_weight(tag)}
        if not weighted:
            continue
        weighted_keys = {
            _clothing_key(_tag_weight_key(tag)[0]) for tag in weighted}
        weighted_keys.discard("")
        unweighted = [
            tag for tag in profile.initial_clothing if tag not in weighted]
        remove_keys = {
            _clothing_key(_tag_weight_key(tag)[0]) for tag in unweighted}
        remove_keys.discard("")
        remove_keys -= weighted_keys
        remove_tags = {
            _tag_weight_key(tag)[0] for tag in unweighted
            if not _clothing_key(_tag_weight_key(tag)[0])}
        remove_items = {_tag_weight_key(tag)[0] for tag in unweighted}
        for tag in tags:
            clean = _tag_weight_key(tag)[0]
            if (_clothing_key(clean) in remove_keys
                    or clean in remove_tags):
                removed.add(tag)
        kept = [tag for tag in tags if tag not in removed]
        if kept != tags:
            shot["prompt"] = ", ".join(kept)
        for field in ("character_states", "clothing_details"):
            values = shot.get(field)
            if not isinstance(values, dict):
                continue
            current = values.get(profile.key)
            if not isinstance(current, str):
                continue
            values[profile.key] = ", ".join(
                tag.strip() for tag in current.split(",")
                if tag.strip()
                and _clothing_key(_tag_weight_key(tag.strip())[0])
                not in remove_keys
                and _tag_weight_key(tag.strip())[0] not in remove_tags
                and (not weighted_keys
                     or _clothing_key(_tag_weight_key(tag.strip())[0])
                     in weighted_keys
                     or not _clothing_key(_tag_weight_key(tag.strip())[0]))
                and not any(_tag_matches_removed_item(tag.strip(), item)
                            for item in remove_items))
        tags = kept
    if removed:
        trace_event("wardrobe.finalize", {
            "id": str(shot.get("id") or ""),
            "removed": sorted(removed),
            "prompt": shot.get("prompt") or "",
        })


def enforce_final_wardrobe(shots: list[dict[str, Any]],
                           profiles: list[CharacterProfile]) -> None:
    if not shots:
        return
    tail = max(1, int(round(len(shots) * 0.2)))
    for shot in shots[-tail:]:
        _enforce_wardrobe_for_shot(shot, profiles)


_LAYERED_TOUCH_RE = re.compile(
    r"(?:伸进|探入|伸入|插进|进入|inside)[^。；;]{0,18}"
    r"(?:裤袜|丝袜|pantyhose)", re.I)
_LAYERED_PANTIES_RE = re.compile(
    r"(?:伸进|探入|伸入|插进|进入|inside)[^。；;]{0,18}"
    r"(?:内裤|underwear|panties)", re.I)
_DIRECT_TOUCH_WORDS = ("阴唇", "阴蒂", "私处", "阴道口", "外阴")


def ensure_layered_masturbation(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        text = _shot_narrative_text(shot)
        if not any(word in text for word in _DIRECT_TOUCH_WORDS):
            continue
        if not any(word in text for word in (
                "自慰", "揉", "摸", "指", "手", "masturbat", "fingering")):
            continue
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        low = ", ".join(tag.lower() for tag in tags)
        additions: list[str] = []
        if _LAYERED_TOUCH_RE.search(text) and "hand inside pantyhose" not in low:
            additions.append("hand inside pantyhose")
        if _LAYERED_PANTIES_RE.search(text) and "hand inside panties" not in low:
            additions.append("hand inside panties")
        if not any(term in low for term in (
                "fingers on labia", "fingers on clitoris", "touching labia")):
            additions.append("fingers on labia")
        if additions:
            shot["prompt"] = ", ".join(tags + additions)
            script = str(shot.get("script") or "")
            if "直接接触阴唇" not in script:
                if "hand inside panties" in additions:
                    script = (script.rstrip("。；; ")
                              + "；手指伸入内裤，指腹直接接触阴唇。").strip()
                elif "hand inside pantyhose" in additions:
                    script = (script.rstrip("。；; ")
                              + "；手指伸入裤袜内。").strip()
                if script:
                    shot["script"] = script
            trace_event("prompt.layered_masturbation", {
                "id": str(shot.get("id") or ""),
                "added": additions,
            })


_BREAST_LAYER_RE = re.compile(
    r"(?:手|指)[^。；;]{0,12}(?:伸进|伸入|探入|进入|under)[^。；;]{0,16}"
    r"(?:外衣|上衣|制服|衣服|shirt|uniform|bra|胸罩|内衣)"
    r"[^。；;]{0,20}(?:胸|乳房|breast)", re.I)


def ensure_layered_breast_contact(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        text = _shot_narrative_text(shot)
        if not any(word in text for word in ("胸", "乳房", "breast")):
            continue
        if not any(word in text for word in ("手", "指")):
            continue
        if not any(word in text for word in (
                "外衣", "上衣", "制服", "衣服", "shirt", "uniform", "bra",
                "胸罩", "内衣")):
            continue
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        low = ", ".join(tag.lower() for tag in tags)
        additions = []
        if "hand under clothes" not in low:
            additions.append("hand under clothes")
        if "hand inside bra" not in low:
            additions.append("hand inside bra")
        if "breast grab" not in low and "hand on breast" not in low:
            additions.append("breast grab")
        if additions:
            shot["prompt"] = ", ".join(tags + additions)
            script = str(shot.get("script") or "")
            if "从外衣下伸入胸罩" not in script:
                shot["script"] = (script.rstrip("。；; ")
                                  + "；手从外衣下伸入胸罩内抚摸乳房。").strip()
            trace_event("prompt.layered_breast", {
                "id": str(shot.get("id") or ""),
                "added": additions,
            })


def enforce_premise_masturbation_layers(
        shots: list[dict[str, Any]], premise: str) -> None:
    text = str(premise or "")
    inside = re.search(
        r"(?:手|指)[^。；;]{0,8}(?:伸进|探入|伸入|插进)[^。；;]{0,12}"
        r"(?:内裤|裤袜)", text)
    if not inside:
        return
    wants_pantyhose = bool(re.search(r"裤袜", text))
    candidates = []
    for shot in shots:
        cast = str(shot.get("cast") or "").lower()
        if "1boy" in cast or "male" in cast:
            break
        narrative = _shot_narrative_text(shot)
        if not any(word in narrative for word in ("自慰", "masturbat", "fingering")):
            continue
        if not any(word in narrative for word in ("内裤", "panties")):
            continue
        stages = _intimacy_stages(shot)
        if 3 in stages:
            break
        if 4 in stages:
            continue
        candidates.append(shot)
    if not candidates:
        return
    target = candidates[-1]
    tags = [tag.strip() for tag in str(target.get("prompt") or "").split(",")
            if tag.strip()]
    low = ", ".join(tag.lower() for tag in tags)
    additions: list[str] = []
    if "hand inside pantyhose" not in low and wants_pantyhose:
        additions.append("hand inside pantyhose")
    if "hand inside panties" not in low:
        additions.append("hand inside panties")
    if not any(term in low for term in (
            "fingers on labia", "fingers on clitoris", "touching labia")):
        additions.append("fingers on labia")
    if not additions:
        return
    tags = [
        tag for tag in tags
        if tag.lower() not in (
            "through panties", "rubbing through panties",
            "rubbing over panties", "through clothes")]
    target["prompt"] = ", ".join(tags + additions)
    script = str(target.get("script") or "")
    if "手指直接接触阴唇" not in script:
        target["script"] = (script.rstrip("。；; ") + "；手指伸入内裤内直接接触阴唇。").strip()
    trace_event("prompt.premise_masturbation_layers", {
        "id": str(target.get("id") or ""),
        "added": additions,
    })


_LAYER_TAG_ORDER = (
    "hand inside pantyhose", "hand inside panties", "fingers on labia",
    "fingers on clitoris", "touching labia",
)


def canonicalize_layer_tags(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]
        present = {}
        for tag in tags:
            clean = _tag_weight_key(tag)[0]
            if clean in _LAYER_TAG_ORDER:
                present[clean] = tag
        if not present:
            continue
        layer_clean = set(present)
        tags = [tag for tag in tags
                if _tag_weight_key(tag)[0] not in layer_clean]
        tags.extend(present[clean] for clean in _LAYER_TAG_ORDER
                    if clean in present)
        shot["prompt"] = ", ".join(tags)


def ensure_final_afterglow(shots: list[dict[str, Any]]) -> None:
    if not shots or not isinstance(shots[-1], dict):
        return
    shot = shots[-1]
    text = _shot_narrative_text(shot)
    if any(term in text for term in (
            "afterglow", "after sex", "afterplay", "余韵", "事后")):
        return
    if not any(term in text for term in (
            "orgasm", "climax", "ejaculat", "creampie", "cum", "semen",
            "射精", "高潮", "潮吹", "白浊")):
        return
    tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
            if tag.strip()]
    low = ", ".join(tag.lower() for tag in tags)
    additions = []
    if "afterglow" not in low:
        additions.append("afterglow")
    if "after sex" not in low:
        additions.append("after sex")
    shot["prompt"] = ", ".join(tags + additions)
    phase = str(shot.get("phase") or "").strip()
    if phase and not any(term in phase for term in ("余韵", "事后")):
        shot["phase"] = phase + "·事后余韵"
    script = str(shot.get("script") or "")
    if "事后余韵" not in script:
        shot["script"] = (script.rstrip("。；; ")
                          + "；事后余韵：动作放慢，呼吸仍未平复。").strip()
    trace_event("prompt.final_afterglow", {"id": str(shot.get("id") or "")})


def finalize_generated_story(shots: list[dict[str, Any]], premise: str,
                             profiles: list[CharacterProfile] | None = None
                             ) -> None:
    renumber_shots(shots)
    normalize_shot_casts(shots)
    for shot in shots:
        if not isinstance(shot, dict) or str(shot.get("phase") or "").strip():
            continue
        fallback = str(
            shot.get("beat") or shot.get("outline")
            or shot.get("script") or "")[:80]
        if fallback:
            shot["phase"] = fallback
    profiles = profiles or parse_character_profiles(premise)
    infer_missing_clothing_details(shots, profiles)
    sync_clothing_state_to_prompt(shots, profiles)
    enforce_weighted_core(shots, profiles)
    enforce_final_wardrobe(shots, profiles)
    ensure_layered_masturbation(shots)
    ensure_layered_breast_contact(shots)
    enforce_premise_masturbation_layers(shots, premise)
    ensure_final_afterglow(shots)
    apply_focus_weights(shots)
    canonicalize_layer_tags(shots)


_CLOTHING_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}


def _clothing_repair_messages(shot: dict[str, Any],
                              feedback: list[str],
                              previous_prompt: str = "") -> list[dict[str, str]]:
    user = [
        "剧本：%s" % str(shot.get("script") or shot.get("outline") or ""),
        "当前镜头原 prompt：%s" % str(shot.get("prompt") or ""),
        "上一镜 prompt（仅用于连续性参考）：%s" % previous_prompt,
        "连续性校验发现的问题：\n" + "\n".join("- " + item for item in feedback),
        "请只重写当前镜头的英文 Booru prompt，保留原剧本的场景、角色、动作、"
        "镜头和 NSFW 内容，只修正服装连续性。不要修改分镜，不要增加新剧情。"
        "只输出 JSON：{\"prompt\":\"...\"}。",
    ]
    return [
        {"role": "system", "content": (
            "你是 Booru 提示词修复器。根据校验反馈重写当前镜头 prompt，"
            "只修正服装连续性问题；保留原有剧情、动作、场景、构图和画风。")},
        {"role": "user", "content": "\n".join(user)},
    ]


_OFF_BODY_WORDS = (
    "removed", "discarded", "on towel", "on sand", "on floor", "on the floor",
    "on seat", "on the seat", "on car seat", "on chair", "on bed", "on ground",
    "on table", "on couch", "on sofa", "under seat", "under the seat", "on waist",
    "holding", "folded", "in hand", "thrown",
    "dropped", "taken off", "pulled off", "slipped off", "panties off",
    "bra off", "pantyhose off", " off",
)


_MALE_STATE_RE = re.compile(r"\b(?:male|man|men|boy|boys|his)\b", re.I)


def _is_male_state(tag: str) -> bool:
    return bool(_MALE_STATE_RE.search(str(tag or "")))


def _item_head(item: str) -> str:
    words = re.findall(r"[a-z0-9]+", str(item or "").lower())
    return words[-1] if words else ""


def _off_body_item(tag: str) -> str:
    value = _tag_weight_key(tag)[0]
    if not value or "off shoulder" in value or "off-shoulder" in value:
        return ""
    markers = sorted(
        {word.strip() for word in _OFF_BODY_WORDS if word.strip()},
        key=len, reverse=True)
    for marker in markers:
        match = re.search(
            r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(marker), value)
        if match:
            item = value[:match.start()].strip(" ,_-")
            if item:
                return item
    return ""


def _is_off_body_tag(tag: str) -> bool:
    return bool(_off_body_item(tag))


def _tag_matches_removed_item(tag: str, item: str) -> bool:
    head = _item_head(item)
    if not head:
        return False
    value = _tag_weight_key(tag)[0]
    return bool(re.search(
        r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(head), value))


def _script_reintroduces_item(script: str, item: str) -> bool:
    text = str(script or "").lower()
    key = _clothing_key(item)
    if key and _restores_item(script, key):
        return True
    head = _item_head(item)
    if not text or not head or not re.search(
            r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(head), text):
        return False
    markers = tuple(_OUTFIT_CHANGE_WORDS) + ("wearing",)
    return (any(str(marker).lower() in text for marker in markers)
            or bool(re.search(_CLOTHING_RESTORE_RE, text, re.I)))


def repair_clothing_sequence(client: Any, model: str,
                             shots: list[dict[str, Any]],
                             profiles: list[CharacterProfile],
                             timeout: float = 300.0,
                             log: Callable[[str], None] | None = None) -> None:
    girls = [profile for profile in profiles if profile.gender == "girl"]
    if not girls:
        return
    current: dict[str, str] = {}
    current_repr: dict[str, str] = {}
    damaged: set[str] = set()
    previous_prompt = ""
    for shot in shots:
        script = str(shot.get("script") or shot.get("outline") or "")
        change = _script_allows_outfit_change(script)
        repair = _script_allows_repair(script)
        state_reset = _script_allows_state_reset(script)
        removed = {
            key for key in current
            if _removes_item(script, key) and not change
        }
        for key in removed:
            current.pop(key, None)
            current_repr.pop(key, None)
            damaged.discard(key)
        tags = [tag.strip() for tag in str(shot.get("prompt") or "").split(",")
                if tag.strip()]

        def issues_for(values: list[str]) -> list[str]:
            worn_values = [tag for tag in values if not _is_off_body_tag(tag)]
            keys = {_clothing_key(tag) for tag in worn_values
                    if _clothing_key(tag)}
            low = " ".join(values).lower()
            off_keys = {_clothing_key(tag) for tag in values
                        if _is_off_body_tag(tag) and _clothing_key(tag)}
            if "topless" in low:
                off_keys.update(_TOPLESS_REMOVE)
            if "bottomless" in low:
                off_keys.update(_BOTTOMLESS_REMOVE)
            issues: list[str] = []
            nude_now = any(_is_full_nude_tag(tag) for tag in values)
            for key, tag in current_repr.items():
                if key in removed or key in off_keys:
                    continue
                if key not in keys:
                    issues.append("上一镜仍穿着、这一镜漏掉了：%s" % tag)
                elif (_is_clothing_state_tag(tag)
                      and not state_reset
                      and not any(
                          _clothing_key(item) == key
                          and _is_clothing_state_tag(item)
                          for item in worn_values)):
                    issues.append("服装状态被改回去了：上一镜是 %s，不能变回完整穿着"
                                  % tag)
            for key in damaged:
                if key in removed or key in off_keys or key not in keys:
                    continue
                if not any(_clothing_key(tag) == key
                           and any(word in tag.lower() for word in _DAMAGE_WORDS)
                           for tag in worn_values):
                    issues.append("上一镜已有破损，这一镜必须保留：%s"
                                  % current.get(key, key))
            if previous_prompt and not change and not state_reset:
                for tag in worn_values:
                    key = _clothing_key(tag)
                    if key and key not in current:
                        issues.append("上一镜没有这件服装，除非剧本明确换装：%s"
                                      % tag)
            if nude_now and keys:
                issues.append("当前写成全裸，却同时出现服装标签：%s"
                              % ", ".join(sorted(keys)))
            if "bottomless" in low and any(
                    key in keys for key in _BOTTOMLESS_REMOVE):
                issues.append("当前写 bottomless，却同时出现下身服装")
            if "topless" in low and any(
                    key in keys for key in _TOPLESS_REMOVE):
                issues.append("当前写 topless，却同时出现上身服装")
            for key in keys:
                has_removed = any(
                    _clothing_key(tag) == key and _is_off_body_tag(tag)
                    for tag in values)
                has_worn = any(
                    _clothing_key(tag) == key and not _is_off_body_tag(tag)
                    for tag in values)
                if has_removed and has_worn:
                    issues.append("同一服装同时写了脱下和在穿：%s" % key)
            return issues

        feedback = issues_for(tags)
        if feedback:
            try:
                raw = client.chat_json(
                    model,
                    _clothing_repair_messages(shot, feedback, previous_prompt),
                    schema=_CLOTHING_REPAIR_SCHEMA,
                    temperature=0.5,
                    num_predict=4096,
                    num_ctx=32768,
                    keep_alive="5m",
                    timeout=timeout,
                    retries=1,
                )
                fixed = raw_prompt(raw.get("prompt") or "")
                if fixed:
                    shot["prompt"] = fixed
                    tags = [tag.strip() for tag in fixed.split(",")
                            if tag.strip()]
                    if log:
                        log("服装连续性已重新生成 shot %s" % shot.get("id", ""))
                elif log:
                    log("服装连续性重生成返回空 shot %s" % shot.get("id", ""))
            except Exception as exc:
                if log:
                    log("服装连续性重生成失败 shot %s: %s" % (
                        shot.get("id", ""), exc))

        # 状态缓存只来自 AI prompt，不再来自用户初始服装。
        nude = any(_is_full_nude_tag(tag) for tag in tags)
        if nude:
            current.clear()
            current_repr.clear()
            damaged.clear()
        else:
            low = " ".join(tags).lower()
            if "bottomless" in low:
                for key in _BOTTOMLESS_REMOVE:
                    current.pop(key, None)
                    current_repr.pop(key, None)
                    damaged.discard(key)
            if "topless" in low:
                for key in _TOPLESS_REMOVE:
                    current.pop(key, None)
                    current_repr.pop(key, None)
                    damaged.discard(key)
            for tag in tags:
                key = _clothing_key(tag)
                if not key:
                    continue
                if (key not in current and previous_prompt
                        and not change and not state_reset):
                    continue
                is_damage = any(word in tag.lower() for word in _DAMAGE_WORDS)
                is_state = _is_clothing_state_tag(tag) and not is_damage
                if _is_off_body_tag(tag):
                    current.pop(key, None)
                    current_repr.pop(key, None)
                    damaged.discard(key)
                elif is_damage:
                    damaged.add(key)
                elif is_state:
                    current[key] = tag
                    current_repr[key] = tag
                elif state_reset:
                    current[key] = tag
                    current_repr[key] = tag
                elif key not in current_repr:
                    current[key] = tag
                    current_repr[key] = tag
            if repair:
                damaged.clear()
        previous_prompt = str(shot.get("prompt") or "")
        if log:
            remaining = issues_for(tags)
            if remaining:
                log("服装连续性仍有问题 shot %s: %s" % (
                    shot.get("id", ""), "；".join(remaining)))


_CLOTHING_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "valid": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "prompt": {"type": "string"},
                    "clothing_state": {"type": "string"},
                },
                "required": ["id", "valid"],
            },
        },
    },
    "required": ["shots"],
}


def _clothing_validation_messages(previous_prompt: str,
                                  previous_state: str,
                                  batch: list[dict[str, Any]]
                                  ) -> list[dict[str, str]]:
    payload = {
        "previous_prompt": previous_prompt,
        "previous_clothing_state": previous_state,
        "shots": [{
            "id": str(shot.get("id") or ""),
            "script": str(shot.get("script") or shot.get("outline") or ""),
            "prompt": str(shot.get("prompt") or ""),
        } for shot in batch],
    }
    return [
        {"role": "system", "content": (
            "你是 NSFW 连续剧情分镜的服装连续性审稿员。"
            "根据剧本、上一镜 prompt、当前镜头 prompt 和本批镜头顺序，"
            "检查所有服装与裸露状态，不受固定服装词表限制。"
            "男主始终无服装、无脸、裸体：删除所有男装标签，补 nude male、faceless male；"
            "script 里的男主服装描述视为错误，不能沿用；"
            "男主优先近景或上半身，除非动作确实需要，否则删除 full body/wide shot。"
            "重点检查：上一镜仍在穿的衣服这一镜漏掉、"
            "半脱/拨开/破损状态无理由恢复完整、"
            "已脱下的服装无理由重新出现、"
            "没有剧本依据的新服装、"
            "破损单品同时保留完整基础标签、"
            "全裸/半裸标签与服装标签互相矛盾。"
            "同一服装类别只能有一个有效状态，不要同时写穿着和脱下；"
            "破损与半脱互斥：torn/ripped/hole 与 pulled aside/around/half-off "
            "不能出现在同一服装 key 上，破损优先，直接写破洞。"
            "只有情趣服装可在明确非否定恢复动作后穿回；常规服装脱了不能穿回；"
            "damage 永久保留。带权重的初始服装是保留核心；"
            "不带权重的初始服装必须按剧情节奏逐镜脱完，最后一镜前全部消失。"
            "半脱/拨开/破损必须有当前 script 依据，或由上一镜 clothing_state 继承，"
            "否则删除该状态；script 明确写拉回/穿好/扣好/整理时，"
            "必须移除对应衣物的半脱状态并恢复基础服装。"
            "上一镜 clothing_state 明确写 removed/脱下/放在一旁时，"
            "当前没有明确重新穿上的依据就不能重新出现。"
            "pantyhose 是连裤袜，不是第二件 panties；不要把裤袜状态写成额外内裤。"
            "如果某镜 prompt 没有服装连续性问题，valid=true，"
            "不要返回 prompt，以减少输出长度。"
            "如果有问题，valid=false，并在 issues 写清原因，"
            "同时重写该镜 prompt：保留原剧本的场景、角色、动作、表情、构图、"
            "镜头、光线和 NSFW 内容，只修正服装状态。"
            "每一镜都必须返回简短的 clothing_state，使用英文 Booru 标签、"
            "逗号分隔，只写当前仍成立的状态/破损标签，例如 torn pantyhose、"
            "panties aside、bra pull、panties removed；"
            "如果当前没有任何半脱/破损/脱下状态，clothing_state 必须返回 none；"
            "不要把完整基础服装、角色外貌和场景写进 clothing_state。"
            "只输出 JSON：{shots:[{id,valid,issues,prompt,clothing_state}]}，不要解释。")},
        {"role": "user", "content": json.dumps(
            payload, ensure_ascii=False) + (
            "\n第一镜参考 previous_prompt 和 previous_clothing_state；"
            "之后每一镜参考前一镜。有效镜头只返回 clothing_state，不返回 prompt。")},
    ]


def _apply_ai_clothing_state(shot: dict[str, Any],
                             profiles: list[CharacterProfile],
                             state: str) -> None:
    girl = next((profile for profile in profiles
                 if profile.gender == "girl"), None)
    if girl is None:
        return
    details = shot.setdefault("clothing_details", {})
    if not isinstance(details, dict):
        return
    if str(state or "").strip().lower() in ("", "none", "无", "没有"):
        details[girl.key] = ""
        return
    state_tags = {
        tag for tag in _tags_from_value(state)
        if _is_state_or_damage(tag) and not _is_male_state(tag)}
    if state_tags:
        details[girl.key] = ", ".join(sorted(state_tags))


def repair_clothing_sequence_ai(client: Any, model: str,
                                shots: list[dict[str, Any]],
                                profiles: list[CharacterProfile],
                                timeout: float = 300.0,
                                log: Callable[[str], None] | None = None,
                                chunk: int = 8,
                                start: int = 0) -> None:
    if not shots:
        return
    start = max(0, min(int(start), len(shots)))
    previous_prompt = ""
    previous_state = ""
    if start > 0:
        previous_prompt = str(shots[start - 1].get("prompt") or "")
        previous_state = str(shots[start - 1].get("clothing_state") or "")
    for offset in range(start, len(shots), max(1, int(chunk))):
        batch = shots[offset:offset + max(1, int(chunk))]
        try:
            raw = client.chat_json(
                model,
                _clothing_validation_messages(
                    previous_prompt, previous_state, batch),
                schema=_CLOTHING_VALIDATION_SCHEMA,
                temperature=0.2,
                num_predict=8192,
                num_ctx=32768,
                keep_alive="5m",
                timeout=timeout,
                retries=1,
            )
            items = raw.get("shots") if isinstance(raw, dict) else []
            by_id = {
                str(item.get("id") or ""): item
                for item in items
                if isinstance(item, dict)
            }
            for index, shot in enumerate(batch):
                item = by_id.get(str(shot.get("id") or ""))
                if item is None and index < len(items):
                    item = items[index] if isinstance(items[index], dict) else None
                if not isinstance(item, dict):
                    continue
                before = dict(shot)
                fixed = raw_prompt(item.get("prompt") or "")
                if item.get("valid") is False and fixed:
                    shot["prompt"] = fixed
                    if log:
                        issues = item.get("issues") or []
                        log(_format_issue_log(
                            "服装修正 shot %s" % shot.get("id", ""),
                            issues))
                if "clothing_state" in item:
                    state = str(item.get("clothing_state") or "").strip()
                    shot["clothing_state"] = state
                    _apply_ai_clothing_state(shot, profiles, state)
                trace_event("repair.clothing", {
                    "id": str(shot.get("id") or ""),
                    "before": before,
                    "after": dict(shot),
                    "ai_item": item,
                })
        except Exception as exc:
            if log:
                log("AI 服装连续性校验失败，保留原 prompt: %s" % exc)
        previous_prompt = str(batch[-1].get("prompt") or "")
        previous_state = str(
            batch[-1].get("clothing_state") or previous_state)


_STORY_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "valid": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cast": {"type": "string"},
                    "script": {"type": "string"},
                    "prompt": {"type": "string"},
                    "phase": {"type": "string"},
                    "beat": {"type": "string"},
                    "clothing": {"type": "string"},
                    "scene": {"type": "string"},
                    "camera": {"type": "string"},
                    "nsfw": {"type": "string"},
                },
                "required": ["id", "valid"],
            },
        },
    },
    "required": ["shots"],
}


def _story_validation_messages(history: list[dict[str, Any]],
                               batch: list[dict[str, Any]],
                               premise: str = ""
                               ) -> list[dict[str, str]]:
    payload = {
        "user_story_request": str(premise or ""),
        "clothing_weight_policy": wardrobe_weight_policy(premise),
        "history": history,
        "shots": [{
            "id": str(shot.get("id") or ""),
            "script": str(shot.get("script") or shot.get("outline") or ""),
            "prompt": str(shot.get("prompt") or ""),
        } for shot in batch],
    }
    return [
        {"role": "system", "content": (
            "你是 NSFW 连续剧情分镜的剧情连续性审稿员。"
            "只检查剧情、动作、场景和构图是否重复、回退或原地打转，不限制题材。"
            "男主始终无服装、无脸、裸体，script 的男装描述视为错误；"
            "男主优先近景/上半身，除非动作确实需要，否则不写全身。"
            "带权重的初始服装是保留核心；不带权重的初始服装必须按剧情节奏逐镜脱去，"
            "最后一镜前全部脱完，不能跳步或复穿。"
            "根据完整历史镜头摘要和当前批次，检查："
            "是否重复已经发生过的同一事件、同一前戏节拍、同一对话、同一动作；"
            "是否在已经推进后无理由回到更早阶段；"
            "是否连续多镜只有轻微换词但剧情没有前进；"
            "动作姿势是否与上一镜物理不连贯（躺着突然站起、背对突然正对等）；"
            "场景、时间、光线是否无过渡跳变；"
            "连续镜头是否机位/构图只是重复换词；"
            "性行为段是否缺少不同体位；"
            "cast 与 prompt 人数是否一致：cast 有 1boy 时 prompt 必须有男性在场，"
            "或明确写 male body out of frame；若男性完全不在场，cast 改成 1girl solo；"
            "同一阶段连续超过 15-20 镜仍未推进时，要求压缩或推进到下一阶段。"
            "用户明确要求的动作类型必须分别覆盖，例如女主自慰、男主对女主口交、"
            "女主对男主口交、吞精；缺少任何一项都要重写补上。"
            "穿衣或整理后无时间跳跃、场景变化或新事件就再次脱衣，必须重写。"
            "多轮性爱如果没有明确轮次过渡，只是前戏→性交→事后→再脱循环，必须合并或删重。"
            "用户没有明确要求第二轮时，第一次射精后再完整重复"
            "口交→前戏→性交→射精必须删除；连续事后、整理、走路无新信息时"
            "必须合并，不能靠堆镜头拖长度。"
            "镜头数多于可用剧情节点时，不得循环剧情或重复同一事件；"
            "必须把当前动作扩展成更细的微节拍和状态变化："
            "开始/加深/失控/临界/余韵、程度、身体细节、表情、体液、机位。"
            "同一服装类别不要同时出现穿着和脱下两个状态；"
            "pantyhose 不是第二件 panties。"
            "如果某镜有效，valid=true，不要返回 script 和 prompt，以减少输出长度。"
            "如果某镜重复、回退或衔接失败，valid=false，在 issues 写清问题，"
            "并重写该镜 script 和 prompt：保留角色、场景、服装、动作风格和 NSFW 强度，"
            "但必须让剧情进入新的节拍或写出必要过渡。"
            "无效镜头请同时返回 beat、clothing、scene、camera、nsfw 字段。"
            "不要修改有效镜头。只输出 JSON："
            "{shots:[{id,valid,issues,script,prompt,beat,clothing,scene,camera,nsfw}]}，不要解释。")},
        {"role": "user", "content": json.dumps(
            payload, ensure_ascii=False) + (
            "\n请逐镜检查当前批次；历史镜头只用于判断重复，不要重写历史。")},
    ]


_ACTION_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "shot_id": {"type": "string"},
                    "cast": {"type": "string"},
                    "script": {"type": "string"},
                    "prompt": {"type": "string"},
                    "phase": {"type": "string"},
                    "beat": {"type": "string"},
                    "clothing": {"type": "string"},
                    "scene": {"type": "string"},
                    "camera": {"type": "string"},
                    "nsfw": {"type": "string"},
                },
                "required": ["id", "label", "shot_id", "script", "prompt"],
            },
        },
    },
    "required": ["actions"],
}


def _action_audit_messages(premise: str,
                           shots: list[dict[str, Any]]
                           ) -> list[dict[str, str]]:
    payload = {
        "user_story_request": str(premise or ""),
        "shots": [{
            "id": str(shot.get("id") or ""),
            "cast": str(shot.get("cast") or ""),
            "phase": str(shot.get("phase") or ""),
            "beat": str(shot.get("beat") or ""),
            "script": str(shot.get("script") or shot.get("outline") or ""),
            "prompt": str(shot.get("prompt") or ""),
        } for shot in shots],
    }
    return [
        {"role": "system", "content": (
            "你是 NSFW 剧本动作覆盖审稿员。读取用户完整要求和全部镜头，"
            "找出用户明确要求但当前镜头没有覆盖的动作。"
            "只返回缺失动作；每个动作选择最合适的一镜重写。"
            "动作可能包括自慰、口交、乳交、足交、肛交、69、潮吹、射精、"
            "吞精、颜射、内射或任何用户明确写出的行为，不限于固定词表。"
            "用户明确要求的服装破坏/撕裂/扯破/剪开/破坏/脱下/半脱，"
            "也属于必须覆盖的动作；如果当前只是 pulled aside 而没有真正破坏或脱下，"
            "必须报告缺失并选择合适镜头重写。"
            "用户要求的自慰衣物层次（隔着裤袜/内裤 → 手伸进裤袜/内裤 → "
            "直接摸阴唇/阴蒂）也必须逐层覆盖，不能只写 hand between legs 或 "
            "rubbing through clothes。"
            "必须保持角色、人数、服装、场景、光线和前后剧情连续；"
            "禁止新增用户没有要求的角色，禁止把主动方写反，"
            "禁止把已经覆盖的动作重复返回。"
            "新动作必须同步给出新的 phase/beat，不能让 phase 继续停留在自慰阶段。"
            "如果所有明确要求都已覆盖，actions 返回空数组。"
            "只输出 JSON：{actions:[{id,label,shot_id,cast,script,prompt,"
            "phase,beat,clothing,scene,camera,nsfw}]}，不要解释。")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def repair_missing_actions_ai(client: Any, model: str,
                              shots: list[dict[str, Any]],
                              premise: str,
                              timeout: float = 300.0,
                              log: Callable[[str], None] | None = None) -> None:
    if not shots:
        return
    try:
        raw = client.chat_json(
            model,
            _action_audit_messages(premise, shots),
            schema=_ACTION_AUDIT_SCHEMA,
            temperature=0.2,
            num_predict=8192,
            num_ctx=32768,
            keep_alive="5m",
            timeout=timeout,
            retries=1,
        )
        actions = raw.get("actions") if isinstance(raw, dict) else []
        by_id = {str(shot.get("id") or ""): shot for shot in shots}
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict):
                continue
            shot = by_id.get(str(action.get("shot_id") or ""))
            if shot is None:
                continue
            before = dict(shot)
            script = str(action.get("script") or "").strip()
            prompt = raw_prompt(action.get("prompt") or "")
            if not script and not prompt:
                continue
            if script:
                shot["script"] = script
                shot["outline"] = script
            if prompt:
                shot["prompt"] = prompt
            cast = str(action.get("cast") or "").strip()
            if cast:
                shot["cast"] = normalize_cast(
                    cast, script or str(shot.get("script") or ""))
            phase = str(action.get("phase") or "").strip()
            if not phase:
                phase = str(action.get("label") or "").strip()
            if phase:
                shot["phase"] = phase
            for key in ("beat", "clothing", "scene", "camera", "nsfw"):
                value = str(action.get(key) or "").strip()
                if value:
                    shot[key] = value
            trace_event("repair.missing_action", {
                "id": str(shot.get("id") or ""),
                "before": before,
                "after": dict(shot),
                "ai_action": action,
            })
            if log:
                log("补动作 shot %s：%s" % (
                    shot.get("id", ""), action.get("label", "")))
    except Exception as exc:
        if log:
            log("补动作校验失败，不影响生成: %s" % exc)


def repair_missing_actions_safe(client: Any, model: str,
                                shots: list[dict[str, Any]],
                                premise: str,
                                timeout: float = 300.0,
                                log: Callable[[str], None] | None = None) -> None:
    try:
        repair_missing_actions_ai(
            client, model, shots, premise, timeout=timeout, log=log)
    except Exception as exc:
        if log:
            log("补动作校验已跳过，不影响生成: %s" % exc)


def repair_story_continuity_ai(client: Any, model: str,
                               shots: list[dict[str, Any]],
                               timeout: float = 300.0,
                               log: Callable[[str], None] | None = None,
                               chunk: int = 8,
                               start: int = 0,
                               premise: str = "") -> None:
    if not shots:
        return
    start = max(0, min(int(start), len(shots)))
    for offset in range(start, len(shots), max(1, int(chunk))):
        batch = shots[offset:offset + max(1, int(chunk))]
        history = [{
            "id": str(shot.get("id") or ""),
            "script": str(shot.get("script") or shot.get("outline") or "")[:180],
        } for shot in shots[:offset]]
        try:
            raw = client.chat_json(
                model,
                _story_validation_messages(history, batch, premise),
                schema=_STORY_VALIDATION_SCHEMA,
                temperature=0.25,
                num_predict=8192,
                num_ctx=32768,
                keep_alive="5m",
                timeout=timeout,
                retries=1,
            )
            items = raw.get("shots") if isinstance(raw, dict) else []
            by_id = {
                str(item.get("id") or ""): item
                for item in items
                if isinstance(item, dict)
            }
            for index, shot in enumerate(batch):
                item = by_id.get(str(shot.get("id") or ""))
                if item is None and index < len(items):
                    item = items[index] if isinstance(items[index], dict) else None
                if not isinstance(item, dict) or item.get("valid") is not False:
                    continue
                before = dict(shot)
                script = str(item.get("script") or "").strip()
                prompt = raw_prompt(item.get("prompt") or "")
                cast = str(item.get("cast") or "").strip()
                if cast:
                    shot["cast"] = normalize_cast(cast, script or shot.get("script", ""))
                if script:
                    shot["script"] = script
                    shot["outline"] = script
                if prompt:
                    shot["prompt"] = prompt
                for key in ("phase", "beat", "clothing", "scene", "camera", "nsfw"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        shot[key] = value
                trace_event("repair.story_continuity", {
                    "id": str(shot.get("id") or ""),
                    "before": before,
                    "after": dict(shot),
                    "ai_item": item,
                })
                if log:
                    issues = item.get("issues") or []
                    log(_format_issue_log(
                        "剧情修正 shot %s" % shot.get("id", ""),
                        issues))
        except Exception as exc:
            if log:
                log("AI 剧情连续性校验失败，保留原内容: %s" % exc)


def repair_story_continuity_safe(client: Any, model: str,
                                 shots: list[dict[str, Any]],
                                 timeout: float = 300.0,
                                 log: Callable[[str], None] | None = None,
                                 start: int = 0,
                                 premise: str = "") -> None:
    try:
        repair_story_continuity_ai(
            client, model, shots, timeout=timeout, log=log, start=start,
            premise=premise)
    except Exception as exc:
        if log:
            log("剧情连续性校验已跳过，不影响生成: %s" % exc)


def repair_clothing_sequence_safe(client: Any, model: str,
                                  shots: list[dict[str, Any]],
                                  profiles: list[CharacterProfile],
                                  timeout: float = 300.0,
                                  log: Callable[[str], None] | None = None,
                                  start: int = 0) -> None:
    try:
        repair_clothing_sequence_ai(
            client, model, shots, profiles, timeout=timeout, log=log,
            start=start)
    except Exception as exc:
        if log:
            log("服装连续性校验已跳过，不影响提示词生成: %s" % exc)


def repetitive_shot_groups(shots: list[dict[str, Any]],
                           threshold: float = 0.82) -> list[list[str]]:
    texts = [
        str(shot.get("script") or shot.get("outline") or shot.get("prompt") or "")
        for shot in shots]
    ids = [str(shot.get("id") or "") for shot in shots]
    visited: set[int] = set()
    groups: list[list[str]] = []
    for index in range(len(texts)):
        if index in visited:
            continue
        group = [index]
        for other in range(index + 1, len(texts)):
            if not texts[index] or not texts[other]:
                continue
            ratio = difflib.SequenceMatcher(
                None, texts[index], texts[other]).ratio()
            if ratio >= threshold:
                group.append(other)
                visited.add(other)
        if len(group) > 1:
            groups.append([ids[item] for item in group])
            visited.add(index)
    return groups


def _long_phase_runs(shots: list[dict[str, Any]],
                     minimum: int = 15) -> list[str]:
    runs: list[str] = []
    current = ""
    count = 0
    start = ""
    for shot in shots:
        label = str(shot.get("phase") or shot.get("beat") or "").strip()
        if label and label == current:
            count += 1
        else:
            if current and count >= minimum:
                runs.append("%s-%s: %s" % (
                    start, shot.get("id", ""), current))
            current = label
            count = 1 if label else 0
            start = str(shot.get("id") or "")
    if current and count >= minimum:
        runs.append("%s-END: %s" % (start, current))
    return runs


def _phase_backtracks(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first: dict[str, int] = {}
    current = ""
    backtracks: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        label = str(shot.get("phase") or shot.get("beat") or "").strip()
        if not label:
            continue
        if label != current and label in first:
            backtracks.append({
                "phase": label,
                "first": str(shots[first[label]].get("id") or ""),
                "again": str(shot.get("id") or ""),
            })
        if label not in first:
            first[label] = index
        current = label
    return backtracks


_INTIMACY_STAGE_TERMS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (4, (
        "afterglow", "after sex", "orgasm", "climax", "ejaculat", "creampie",
        "squirt", "cum", "余韵", "高潮", "射精", "事后")),
    (3, (
        "vaginal sex", "penis in pussy", "penetration", "intercourse",
        "anal sex", "sex from behind", "missionary", "cowgirl", "doggystyle",
        "mating press", "riding", "性交", "做爱", "交合")),
    (2, (
        "fellatio", "cunnilingus", "blowjob", "oral sex", "deepthroat",
        "handjob", "paizuri", "口交", "深喉", "舔阴", "舔弄")),
    (1, (
        "masturbation", "fingering", "rubbing pussy", "self pleasure",
        "自慰", "手淫", "揉阴")),
)


_NEGATION_PREFIX_RE = re.compile(
    r"(?:\bnot\b|\bno\b|\bwithout\b|\bnever\b|尚未|没有|没|未|不要|不能|"
    r"并未|无)\s{0,6}$", re.I)


def _term_is_negated(text: str, term: str) -> bool:
    if re.search(r"[a-z]", term):
        pattern = r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term)
    else:
        pattern = re.escape(term)
    for match in re.finditer(pattern, text):
        before = text[max(0, match.start() - 12):match.start()]
        if _NEGATION_PREFIX_RE.search(before):
            continue
        return False
    return bool(re.search(pattern, text))


def _shot_narrative_text(shot: dict[str, Any]) -> str:
    return " ".join((
        str(shot.get("prompt") or ""),
        str(shot.get("script") or shot.get("outline") or ""),
        str(shot.get("beat") or ""),
        str(shot.get("phase") or ""),
    )).lower()


def _intimacy_stages(shot: dict[str, Any]) -> set[int]:
    text = _shot_narrative_text(shot)
    found: set[int] = set()
    for stage, terms in _INTIMACY_STAGE_TERMS:
        for term in terms:
            if term in text and not _term_is_negated(text, term):
                found.add(stage)
                break
    return found


def _intimacy_stage(shot: dict[str, Any]) -> int:
    return max(_intimacy_stages(shot), default=0)


def _intimacy_regressions(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first_sex = ""
    max_stage = 0
    regressions: list[dict[str, Any]] = []
    for shot in shots:
        stages = _intimacy_stages(shot)
        text = _shot_narrative_text(shot)
        afterglow = any(term in text for term in (
            "afterglow", "after sex", "afterplay", "余韵", "事后"))
        if 3 in stages:
            if not first_sex:
                first_sex = str(shot.get("id") or "")
            max_stage = max(max_stage, max(stages))
        elif first_sex and 4 in stages and afterglow:
            max_stage = max(max_stage, 4)
        elif first_sex and (
                (stages & {1, 2}) or not stages):
            regressions.append({
                "id": str(shot.get("id") or ""),
                "first": first_sex,
                "stage": max(stages, default=0),
                "max_stage": max_stage,
            })
        elif first_sex and 4 in stages:
            max_stage = max(max_stage, 4)
    return regressions


def _pacing_audit_messages(shots: list[dict[str, Any]], premise: str,
                           duplicate_groups: list[list[str]],
                           long_runs: list[str]) -> list[dict[str, str]]:
    phase_counts: dict[str, int] = {}
    for shot in shots:
        label = str(shot.get("phase") or shot.get("beat") or "未标注").strip()
        phase_counts[label] = phase_counts.get(label, 0) + 1
    payload = {
        "user_story_request": str(premise or ""),
        "clothing_weight_policy": wardrobe_weight_policy(premise),
        "shot_count": len(shots),
        "phase_counts": phase_counts,
        "duplicate_groups": duplicate_groups,
        "long_phase_runs": long_runs,
        "phase_backtracks": _phase_backtracks(shots),
        "intimacy_regressions": _intimacy_regressions(shots),
        "shots": [{
            "id": str(shot.get("id") or ""),
            "phase": str(shot.get("phase") or ""),
            "beat": str(shot.get("beat") or ""),
            "cast": str(shot.get("cast") or ""),
            "script": str(shot.get("script") or shot.get("outline") or "")[:500],
            "prompt": str(shot.get("prompt") or "")[:350],
        } for shot in shots],
    }
    return [
        {"role": "system", "content": (
            "你是 NSFW 剧情节奏与镜头扩展审稿员。用户镜头数很多时，"
            "绝对不能靠循环剧情、重复同一事件或重复同一段描写来凑镜头。"
            "检查重复镜头组、连续过长阶段、无新信息的事后/走路/整理，"
            "以及带权重服装被无故脱掉、不带权重的初始服装没有逐镜脱完；"
            "以及 phase/beat 已经推进后又回到更早阶段（phase_backtracks）；"
            "以及已经发生插入/性交后又回到站立、自慰、口交等更早动作"
            "（intimacy_regressions）；"
            "回退段必须改成当前阶段内的新微节拍或删除，不能直接复用旧阶段。"
            "性交已经发生后，后续镜头只能继续性交、换姿势、高潮或事后余韵，"
            "不能回到自慰、口交、重新站立准备或重复前戏。"
            "需要补足镜头时，在同一场景、同一剧情节点内扩展微节拍和细节："
            "动作开始/加深/失控/临界/余韵、程度变化、身体细节、姿态变化、"
            "表情、呼吸、体液、衣物状态、机位和构图变化。"
            "每个重写镜头必须有新的可画变化，不能只是换同义词；"
            "检查镜头分配是否头重脚轻：某个动作/阶段占用大量镜头，"
            "而用户明确要求的其他动作只有一两镜时，必须压缩过度部分并补足其他动作。"
            "如果重写后 script 仍与重复镜头高度相似，必须继续改写，"
            "不能只改 prompt 或替换同义词。"
            "不得新增场景、人物、轮次或用户没有要求的动作。"
            "只重写重复、循环或没有推进的镜头；有效镜头 valid=true，不返回内容。"
            "只输出 JSON：{shots:[{id,valid,issues,cast,script,prompt,"
            "phase,beat,clothing,scene,camera,nsfw}]}，不要解释。")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def repair_story_pacing_ai(client: Any, model: str,
                           shots: list[dict[str, Any]], premise: str,
                           timeout: float = 300.0,
                           log: Callable[[str], None] | None = None) -> None:
    if not shots:
        return
    try:
        total_changed = 0
        for attempt in range(2):
            duplicate_groups = repetitive_shot_groups(shots)
            long_runs = _long_phase_runs(shots)
            backtracks = _phase_backtracks(shots)
            regressions = _intimacy_regressions(shots)
            if (attempt > 0 or len(shots) < 10) and not (
                    duplicate_groups or long_runs or backtracks or regressions):
                break
            messages = _pacing_audit_messages(
                shots, premise, duplicate_groups, long_runs)
            if attempt:
                messages.append({
                    "role": "user",
                    "content": (
                        "上一轮重写后仍存在重复、循环或阶段回退镜头。"
                        "这次必须让 script 与重复镜头的动作、阶段、表情、"
                        "身体细节或体液状态明显不同，不能只改 prompt 或换同义词。"
                        "重复组：%s；"
                        "性交后回退：%s" % (
                            json.dumps(duplicate_groups, ensure_ascii=False),
                            json.dumps(regressions, ensure_ascii=False))),
                })
            raw = client.chat_json(
                model,
                messages,
                schema=_STORY_VALIDATION_SCHEMA,
                temperature=0.35 if attempt == 0 else 0.5,
                num_predict=16384,
                num_ctx=32768,
                keep_alive="5m",
                timeout=timeout,
                retries=1,
            )
            items = raw.get("shots") if isinstance(raw, dict) else []
            by_id = {
                str(item.get("id") or ""): item
                for item in items if isinstance(item, dict)
            }
            duplicate_ids = {
                str(value) for group in duplicate_groups for value in group}
            changed = 0
            for shot in shots:
                sid = str(shot.get("id") or "")
                item = by_id.get(sid)
                forced = sid in duplicate_ids
                if not isinstance(item, dict):
                    continue
                if item.get("valid") is not False and not forced:
                    continue
                if forced and item.get("valid") is not False and not (
                        item.get("script") or item.get("prompt")):
                    continue
                before = dict(shot)
                script = str(item.get("script") or "").strip()
                prompt = raw_prompt(item.get("prompt") or "")
                if script:
                    shot["script"] = script
                    shot["outline"] = script
                if prompt:
                    shot["prompt"] = prompt
                cast = str(item.get("cast") or "").strip()
                if cast:
                    shot["cast"] = normalize_cast(
                        cast, script or str(shot.get("script") or ""))
                for key in ("phase", "beat", "clothing", "scene",
                            "camera", "nsfw"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        shot[key] = value
                trace_event("repair.story_pacing", {
                    "id": str(shot.get("id") or ""),
                    "attempt": attempt + 1,
                    "before": before,
                    "after": dict(shot),
                    "ai_item": item,
                })
                changed += 1
            total_changed += changed
            if not changed:
                break
        if log and total_changed:
            log("剧情节奏修正 %d 镜（重复/循环/拖沓）" % total_changed)
    except Exception as exc:
        if log:
            log("剧情节奏校验失败，不影响生成: %s" % exc)


def repair_story_pacing_safe(client: Any, model: str,
                             shots: list[dict[str, Any]], premise: str,
                             timeout: float = 300.0,
                             log: Callable[[str], None] | None = None) -> None:
    try:
        repair_story_pacing_ai(
            client, model, shots, premise, timeout=timeout, log=log)
    except Exception as exc:
        if log:
            log("剧情节奏校验已跳过，不影响生成: %s" % exc)


def apply_character_state(prompt: str, profiles: list[CharacterProfile],
                          states: dict[str, set[str]],
                          present: list[CharacterProfile] | None = None,
                          details: dict[str, set[str]] | None = None,
                          preserve_ai_clothing: bool = False) -> str:
    present = present or profiles
    worn: set[str] = set()
    for profile in present:
        worn.update(states.get(profile.key) or set())
    wardrobe = {tag for profile in profiles for tag in profile.initial_clothing}
    original = [tag.strip() for tag in str(prompt or "").split(",")
                if tag.strip()]
    has_ai_clothing = any(
        _clothing_key(tag) or _is_clothing_state_tag(tag)
        or _is_full_nude_tag(tag) for tag in original)
    if preserve_ai_clothing and has_ai_clothing:
        tags = original
    else:
        tags = [tag.strip() for tag in apply_story_state(
            prompt, worn, wardrobe).split(",") if tag.strip()]
    tags = [tag for tag in tags if not _appearance_conflicts(tag, present)]
    if not (preserve_ai_clothing and has_ai_clothing):
        for profile in present:
            for tag in (details or {}).get(profile.key) or set():
                key = _clothing_key(tag)
                if not key or any(_clothing_key(worn_tag) == key
                                  for worn_tag in worn):
                    if tag.lower() not in {item.lower() for item in tags}:
                        tags.append(tag)
        nude_flags = [_is_fully_nude(profile, states) for profile in present]
        if nude_flags and any(nude_flags) and not all(nude_flags):
            tags = [tag for tag in tags if not _is_full_nude_tag(tag)]
        elif nude_flags and all(nude_flags):
            if not any(_is_full_nude_tag(tag) for tag in tags):
                tags.append("completely nude")
    seen = {tag.lower() for tag in tags}
    for profile in present:
        for tag in profile.appearance:
            key = tag.lower()
            if key and key not in seen:
                seen.add(key)
                tags.append(tag)
    result = ", ".join(tags)
    trace_event("prompt.apply_state", {
        "before": str(prompt or ""),
        "after": result,
        "worn": sorted(worn),
        "details": details or {},
        "present": [profile.key for profile in present],
    })
    return result


_CAST_TAG_RE = re.compile(
    r"^(?:\d+\s*(?:girl|boy|other)s?|1girl|1boy|solo|multiple girls|multiple boys)$",
    re.I)

_GROUP_GIRL_RE = re.compile(
    r"\b(?:girl|female|woman|breasts?|nipples?|pussy|vagina|labia|clitoris|"
    r"uterus|womb|pantyhose|stockings?|thighhighs?|skirt|dress|bra|panties|"
    r"lingerie|high heels?|makeup|mature female|long hair|"
    r"(?:red|pink|blonde|white|silver|blue|purple|orange|green|"
    r"multicolored) hair)\b"
)
_GROUP_BOY_RE = re.compile(
    r"\b(?:boy|male|man|penis|cock|testicles|phallus|beard|muscular|abs|"
    r"pectorals|short(?:\s+\w+){0,2}\s+hair|adam's apple|jeans|trousers)\b"
)


def _group_key(tag: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(tag or "").lower()).strip()


def _group_tags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        raw = str(value or "").split(",")
    return [tag.strip() for tag in raw if tag.strip()]


def _dedupe_group_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = _group_key(tag)
        if key and key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def character_prompt_groups(profiles: list[CharacterProfile],
                            states: dict[str, set[str]],
                            details: dict[str, set[str]],
                            prompt: str,
                            present: list[CharacterProfile] | None = None
                            ) -> list[dict[str, str]]:
    """Build separate prompt groups so male and female tags cannot bleed."""
    present = present or profiles
    if len(present) < 2:
        return []
    genders = {profile.gender for profile in present}
    if "girl" not in genders or "boy" not in genders:
        return []
    prompt_tags = [tag.strip() for tag in str(prompt or "").split(",")
                   if tag.strip()]
    owned: dict[str, set[str]] = {}
    for profile in present:
        values = list(profile.appearance)
        values.extend(sorted(states.get(profile.key) or set()))
        values.extend(sorted(details.get(profile.key) or set()))
        owned[profile.key] = {
            _group_key(tag) for tag in values if _group_key(tag)}
    all_owned = set().union(*owned.values()) if owned else set()
    shared = [tag for tag in prompt_tags
              if _group_key(tag) not in all_owned and not _CAST_TAG_RE.match(tag)]
    groups: list[dict[str, str]] = []
    for profile in present:
        if profile.gender not in ("girl", "boy"):
            continue
        own = list(profile.appearance)
        own.extend(sorted(states.get(profile.key) or set()))
        own.extend(sorted(details.get(profile.key) or set()))
        own_keys = owned.get(profile.key) or set()
        other_keys = set().union(
            *(value for key, value in owned.items() if key != profile.key))
        tags = ["1boy" if profile.gender == "boy" else "1girl"]
        for tag in own + shared:
            key = _group_key(tag)
            if not key or (key in other_keys and key not in own_keys):
                continue
            text = " " + key.replace("-", " ") + " "
            if profile.gender == "boy" and key not in own_keys:
                if _GROUP_GIRL_RE.search(text):
                    continue
            if profile.gender == "girl" and key not in own_keys:
                if _GROUP_BOY_RE.search(text):
                    continue
            tags.append(tag)
        tags = _dedupe_group_tags(tags)
        if len(tags) > 1:
            groups.append({
                "gender": profile.gender,
                "name": profile.name or profile.key,
                "prompt": ", ".join(tags),
            })
    if not any(group["gender"] == "girl" for group in groups):
        return []
    if not any(group["gender"] == "boy" for group in groups):
        return []
    return groups


def attach_character_prompt_groups(shot: dict[str, Any],
                                   profiles: list[CharacterProfile],
                                   states: dict[str, set[str]],
                                   details: dict[str, set[str]],
                                   present: list[CharacterProfile] | None = None
                                   ) -> None:
    groups = character_prompt_groups(
        profiles, states, details, str(shot.get("prompt") or ""), present)
    if groups:
        shot["prompt_groups"] = groups
    else:
        shot.pop("prompt_groups", None)


def _scene_for_beat(beat: str) -> list[str] | None:
    for key, pattern in _SCENE_PATTERNS:
        if re.search(pattern, beat, re.I):
            return list(_SCENE_TAGS[key])
    return None


def scene_states_for_beats(beats: list[str],
                           initial_scene: list[str] | None = None,
                           scenes: list[str] | None = None) -> list[list[str]]:
    current = list(initial_scene) if initial_scene else list(_SCENE_TAGS["room"])
    states: list[list[str]] = []
    for index, beat in enumerate(beats):
        found: list[str] | None = None
        if scenes and index < len(scenes) and str(scenes[index] or "").strip():
            found = [tag.strip() for tag in re.split(
                r"[,，;；]", str(scenes[index])) if tag.strip()]
        if not found:
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
    "partially removed", "shirt pull", "clothes pull", "bra pull",
    "skirt pull", "top pull", "shirt lift", "skirt lift",
)
_STATE_AROUND_RE = re.compile(
    r"\baround (?:one |the )?(?:ankle|thigh|knee|leg|foot|calf|shin)s?\b")


def _is_clothing_state_tag(tag: str) -> bool:
    low = _spaced_tag(tag)
    return (any(word in low for word in _CLOTHING_DAMAGE_WORDS)
            or any(word in low for word in _HALF_OFF_WORDS)
            or bool(_STATE_AROUND_RE.search(low)))


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
        if _is_layer_action_tag(tag):
            if (not clothing_key or clothing_key in worn_keys
                    or tag.lower() in worn_lowers):
                kept.append(tag)
            continue
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
        hinted = str(item.get("cast") or "").strip()
        cast = normalize_cast(forced_cast or hinted, text)
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
            "cast": normalize_cast(str(item.get("cast") or ""), summary),
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
        options.model,
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
        options.model,
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
        scene_states = scene_states_for_beats(
            beats, scenes=[item.get("scene", "") for item in outline])
        details = _shot_clothing_details(result[-1], profiles) if result else {}
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
                options.model,
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
            for index, shot in enumerate(part):
                state_index = _shot_state_index(shot, outline, offset + index)
                female_clothing: str | None = None
                if state_index < len(character_states):
                    states = character_states[state_index]
                    beat = beats[state_index] if state_index < len(beats) else ""
                    present = present_character_profiles(profiles, shot, beat)
                    details = update_clothing_details(
                        profiles, states, present, shot["prompt"], details,
                        script=str(shot.get("script") or ""))
                    shot["prompt"] = apply_character_state(
                        shot["prompt"], profiles, states, present, details,
                        preserve_ai_clothing=options.preserve_ai_clothing)
                    worn = set()
                    for profile in present:
                        worn.update(states.get(profile.key) or set())
                        if profile.gender == "girl":
                            female_clothing = ", ".join(
                                sorted(states.get(profile.key) or set()))
                    shot["clothing"] = ", ".join(sorted(worn))
                    shot["characters"] = ", ".join(
                        profile.name for profile in present)
                    shot["character_states"] = {
                        profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                        for profile in profiles}
                    shot["clothing_details"] = {
                        profile.key: ", ".join(sorted(details.get(profile.key) or set()))
                        for profile in profiles}
                    attach_character_prompt_groups(
                        shot, profiles, states, details, present)
                if state_index < len(scene_states):
                    shot["scene"] = ", ".join(scene_states[state_index])
                _finalize_shot_prompt(
                    shot, female_clothing,
                    preserve_clothing=options.preserve_ai_clothing)
                shot["preserve_ai_clothing"] = options.preserve_ai_clothing
            chunk_start = len(result)
            result.extend(part)
            repair_story_continuity_safe(
                client, options.model, result,
                timeout=max(options.timeout, 300.0), log=options.log,
                start=chunk_start, premise=premise)
            repair_clothing_sequence_safe(
                client, options.model, result, profiles,
                timeout=max(options.timeout, 300.0), log=options.log,
                start=chunk_start)
            _notify_partial(options, result)
            log("Stage 4/4: Act %d +%d shots (%d/%d)" % (
                act_index, len(part), len(result), shots))
            if not part:
                break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    result = result[:shots]
    repair_missing_actions_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
    repair_story_pacing_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
    finalize_generated_story(result, premise)
    return result


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
            "cast": normalize_cast(str(item.get("cast") or ""), script),
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
            "focus_tags": [
                str(tag).strip() for tag in focus
                if str(tag).strip()] if isinstance(focus, list) else [],
            "script": script["script"],
            "cast": normalize_cast(
                script.get("cast", ""), script.get("script", "")),
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
    profiles = strip_male_profile_details(parse_character_profiles(premise))
    bible = character_bible_text(profiles)
    spine: list[dict[str, Any]] = []
    max_act_shots = max(1, int(options.max_act_shots))
    if not extract_premise_beats(premise):
        spine = plan_story_spine(
            client, options.model, premise, shots, options.setting,
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
            story_beats, initial_scene=_shot_scene(last_shot) or None,
            scenes=[item.get("scene", "") for item in outline])
        details = _shot_clothing_details(last_shot, profiles) if last_shot else {}
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
            chunk_state = _global_story_state(premise, result, profiles)
            script_raw = client.chat_json(
                options.model,
                build_script_messages(
                    premise, len(outline_chunk), options.setting,
                    result, shots, beat_slice,
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
                options.model,
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
            for index, shot in enumerate(part):
                state_index = _shot_state_index(shot, outline, offset + index)
                beat = (story_beats[state_index]
                        if state_index < len(story_beats) else "")
                female_clothing: str | None = None
                if (beat and state_index < len(character_states)
                        and state_index < len(scene_states)):
                    states = character_states[state_index]
                    present = present_character_profiles(profiles, shot, beat)
                    details = update_clothing_details(
                        profiles, states, present, shot["prompt"], details,
                        script=str(shot.get("script") or ""))
                    shot["prompt"] = apply_character_state(
                        shot["prompt"], profiles, states, present, details,
                        preserve_ai_clothing=options.preserve_ai_clothing)
                    worn = set()
                    for profile in present:
                        worn.update(states.get(profile.key) or set())
                        if profile.gender == "girl":
                            female_clothing = ", ".join(
                                sorted(states.get(profile.key) or set()))
                    shot["clothing"] = ", ".join(sorted(worn))
                    shot["characters"] = ", ".join(
                        profile.name for profile in present)
                    shot["character_states"] = {
                        profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                        for profile in profiles}
                    shot["clothing_details"] = {
                        profile.key: ", ".join(sorted(details.get(profile.key) or set()))
                        for profile in profiles}
                    attach_character_prompt_groups(
                        shot, profiles, states, details, present)
                    shot["scene"] = ", ".join(scene_states[state_index])
                _finalize_shot_prompt(
                    shot, female_clothing,
                    preserve_clothing=options.preserve_ai_clothing)
                shot["preserve_ai_clothing"] = options.preserve_ai_clothing
            chunk_start = len(result)
            result.extend(part)
            repair_story_continuity_safe(
                client, options.model, result,
                timeout=max(options.timeout, 300.0), log=options.log,
                start=chunk_start, premise=premise)
            repair_clothing_sequence_safe(
                client, options.model, result, profiles,
                timeout=max(options.timeout, 300.0), log=options.log,
                start=chunk_start)
            _notify_partial(options, result)
            log("Act %d: +%d shots (%d/%d)" % (act_index, len(part), len(result), shots))
            if not part:
                break
        if len(result) >= shots:
            break
    result = result[:shots]
    repair_missing_actions_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
    repair_story_pacing_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
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
            client, options.model, premise, remaining, options.setting,
            chunk=6, timeout=max(options.timeout, 600.0),
            strip_appearance=options.strip_appearance, spine=None,
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
    scene_states = scene_states_for_beats(
        story_beats, scenes=[item.get("scene", "") for item in outline])
    details = _shot_clothing_details(result[-1], profiles) if result else {}

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
            options.model,
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
            options.model,
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
        state_offset = len(result)
        for index, shot in enumerate(part):
            state_index = _shot_state_index(shot, outline, state_offset + index)
            beat = (story_beats[state_index]
                    if state_index < len(story_beats) else "")
            female_clothing: str | None = None
            if (beat and state_index < len(character_states)
                    and state_index < len(scene_states)):
                states = character_states[state_index]
                present = present_character_profiles(profiles, shot, beat)
                details = update_clothing_details(
                    profiles, states, present, shot["prompt"], details,
                    script=str(shot.get("script") or ""))
                shot["prompt"] = apply_character_state(
                    shot["prompt"], profiles, states, present, details,
                    preserve_ai_clothing=options.preserve_ai_clothing)
                worn = set()
                for profile in present:
                    worn.update(states.get(profile.key) or set())
                    if profile.gender == "girl":
                        female_clothing = ", ".join(
                            sorted(states.get(profile.key) or set()))
                shot["clothing"] = ", ".join(sorted(worn))
                shot["characters"] = ", ".join(
                    profile.name for profile in present)
                shot["character_states"] = {
                    profile.key: ", ".join(sorted(states.get(profile.key) or set()))
                    for profile in profiles}
                shot["clothing_details"] = {
                    profile.key: ", ".join(sorted(details.get(profile.key) or set()))
                    for profile in profiles}
                attach_character_prompt_groups(
                    shot, profiles, states, details, present)
                shot["scene"] = ", ".join(scene_states[state_index])
            _finalize_shot_prompt(
                shot, female_clothing,
                preserve_clothing=options.preserve_ai_clothing)
            shot["preserve_ai_clothing"] = options.preserve_ai_clothing
        chunk_start = len(result)
        result.extend(part)
        repair_story_continuity_safe(
            client, options.model, result,
            timeout=max(options.timeout, 300.0), log=options.log,
            start=chunk_start, premise=premise)
        repair_clothing_sequence_safe(
            client, options.model, result, profiles,
            timeout=max(options.timeout, 300.0), log=options.log,
            start=chunk_start)
        _notify_partial(options, result)
        log("Stage B: +%d shots (%d/%d)" % (len(part), len(result), shots))
        if not part:
            break
    if len(result) < shots:
        log("Note: model produced %d/%d shots" % (len(result), shots))
    result = result[:shots]
    repair_missing_actions_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
    repair_story_pacing_safe(
        client, options.model, result, premise,
        timeout=max(options.timeout, 300.0), log=options.log)
    finalize_generated_story(result, premise)
    return result
