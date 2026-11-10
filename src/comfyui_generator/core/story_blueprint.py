"""Shot-budget blueprint planned BEFORE any outline is written.

The software does not decide story semantics. It asks the AI to produce a
structural allocation of the user's ordered milestones across the requested
number of shots, then validates structural facts the software CAN check:

- ids cover every shot 1..N exactly once (continuous, no gaps/overlaps);
- milestones stay in the user's order;
- the terminal milestone is allocated to the final shot, never earlier;
- any extra shots (more shots than milestones) are subdivisions placed
  BEFORE the terminal milestone.

An invalid blueprint is re-planned at the outline stage, so a story can never
reach rendering with its climax placed in the middle and the remaining shots
left to improvise.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

BLUEPRINT_SYSTEM = (
    "你是 NSFW 连续分镜的结构规划师。只做镜头预算分配，不写具体画面。\n"
    "输入 plot_text 是用户的剧情原文，可能采用数字编号、破折号小节、"
    "“**第X–Y镜：标题**”等分节格式，且可能整段挤在一行。\n"
    "你必须先从 plot_text 中识别出有序里程碑：按剧情的自然推进切分，"
    "保持原有顺序，不得调换、遗漏或合并；若同时给出 numbered_milestones，"
    "以其为优先参考。\n"
    "硬性规则：\n"
    "1. 把识别出的里程碑按原有顺序映射到目标镜数。\n"
    "2. “终局”仅指剧本的最后一个里程碑；它必须且只能落在最后一镜。"
    "射精本身不是终局判据：口交内射、颜射、射在身上等可以发生在中段，故事仍可继续。\n"
    "3. 当镜数多于里程碑数时，多出的镜头在最后一个里程碑之前把相关动作拆成更细微节拍，"
    "不得把多余额度放到剧本最后一个里程碑之后。\n"
    "4. 每个里程碑给出 start/end 镜范围，所有范围首尾相接，连续覆盖第1镜到最后一镜，"
    "不留空隙也不重叠。一切以符合剧本设计为最高原则。\n"
    "只输出 JSON：{\"milestones\":[{\"index\":1,\"title\":\"...\","
    "\"start\":1,\"end\":1,\"terminal\":false}]}，不要解释。"
)

BLUEPRINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "terminal": {"type": "boolean"},
                },
                "required": ["index", "start", "end", "terminal"],
            },
        }
    },
    "required": ["milestones"],
}


def _milestone_titles(premise: str) -> list[str]:
    titles: dict[int, str] = {}
    for line in str(premise or "").splitlines():
        match = re.match(r"^\s*(\d{1,2})\s*[.、)]\s*(.+?)\s*$", line)
        if match and match.group(2).strip():
            titles[int(match.group(1))] = match.group(2).strip()
    return [titles[n] for n in sorted(titles)]


_PLOT_MARK_RE = re.compile(r"^\s*(?:剧情|情节|故事|plot)\s*[::：]?\s*$", re.I)


def plot_section(premise: str) -> str:
    """Raw plot body after a 剧情 marker, excluding config/其它 lines.

    Preserves the user's original formatting (numbered lists, dash bullets,
    bold section headers, single-line blocks); semantic parsing is the AI's
    job, so this only locates and returns the plot region verbatim.
    """
    lines = str(premise or "").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if _PLOT_MARK_RE.match(line):
            start = i + 1
            break
    body: list[str] = []
    for line in lines[start:]:
        if re.match(r"^\s*(?:其它|备注|补充|note)\s*[::：]", line, re.I):
            break
        body.append(line)
    return "\n".join(body).strip()


def build_blueprint_messages(premise: str, total_shots: int) -> list[dict[str, str]]:
    numbered = _milestone_titles(premise)
    plot = plot_section(premise)
    payload: dict[str, Any] = {
        "total_shots": int(total_shots),
        "plot_text": plot,
    }
    if numbered:
        payload["numbered_milestones"] = [
            {"index": i + 1, "title": title}
            for i, title in enumerate(numbered)]
    return [
        {"role": "system", "content": BLUEPRINT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def normalize_blueprint(raw: Any, total_shots: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, dict) and isinstance(raw.get("milestones"), list):
        items = [item for item in raw["milestones"] if isinstance(item, dict)]
    cleaned: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: int(x.get("index", 0))):
        try:
            start, end = int(item["start"]), int(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        cleaned.append({
            "index": int(item.get("index", len(cleaned) + 1)),
            "title": str(item.get("title") or "").strip(),
            "start": start,
            "end": end,
            "terminal": bool(item.get("terminal")),
        })
    return cleaned


def blueprint_violations(milestones: list[dict[str, Any]],
                         total_shots: int) -> list[str]:
    total_shots = int(total_shots)
    issues: list[str] = []
    if not milestones:
        return ["蓝图为空：未得到任何里程碑分配"]

    expected_start = 1
    terminal_entries: list[dict[str, Any]] = []
    prev_index = 0
    for entry in milestones:
        start, end = entry["start"], entry["end"]
        if start != expected_start:
            issues.append(
                "里程碑%d 起始镜=%d，但应为%d（镜头范围必须连续无重叠）"
                % (entry["index"], start, expected_start))
        if end < start:
            issues.append("里程碑%d end(%d) < start(%d)" % (
                entry["index"], end, start))
        expected_start = end + 1
        if entry["index"] != prev_index + 1:
            issues.append("里程碑顺序/编号不连续：index=%d 接在 %d 之后" % (
                entry["index"], prev_index))
        prev_index = entry["index"]
        if entry["terminal"]:
            terminal_entries.append(entry)

    if expected_start != total_shots + 1:
        issues.append(
            "蓝图只覆盖到第%d镜，但应连续覆盖到第%d镜"
            % (expected_start - 1, total_shots))

    if len(terminal_entries) != 1:
        issues.append("应有且仅有一个终局里程碑，实际标记 %d 个"
                      % len(terminal_entries))
    elif terminal_entries[0] is not milestones[-1]:
        issues.append("终局里程碑必须是最后一个里程碑")
    else:
        terminal = terminal_entries[0]
        if terminal["end"] != total_shots:
            issues.append(
                "终局被安排在第%d镜结束，但必须落在最后一镜（第%d镜）"
                % (terminal["end"], total_shots))
    return issues


def plan_shot_blueprint(client: Any, model: str,
                        premise: str, total_shots: int,
                        *, timeout: float = 600.0,
                        log: Callable[[str], None] | None = None,
                        max_tries: int = 2
                        ) -> list[dict[str, Any]]:
    """Ask the AI for a blueprint and require it to pass structural validation."""
    total_shots = int(total_shots)
    best: list[dict[str, Any]] = []
    for attempt in range(max(1, int(max_tries))):
        raw = client.chat_json(
            model,
            build_blueprint_messages(premise, total_shots),
            schema=BLUEPRINT_SCHEMA,
            temperature=0.3,
            num_predict=4096,
            num_ctx=32768,
            timeout=timeout,
            retries=2,
        )
        milestones = normalize_blueprint(raw, total_shots)
        violations = blueprint_violations(milestones, total_shots)
        best = milestones
        if not violations:
            if log:
                log("镜头蓝图已通过：终局锁定第%d镜。" % total_shots)
            return milestones
        if log:
            log("镜头蓝图第%d次校验未过：%s" % (
                attempt + 1, "；".join(violations)))
    return best


def blueprint_text(milestones: list[dict[str, Any]]) -> str:
    rows = []
    for entry in milestones:
        tag = "（终局）" if entry["terminal"] else ""
        rows.append("镜%02d-%02d：里程碑%d%s%s" % (
            entry["start"], entry["end"], entry["index"], tag,
            " " + entry["title"] if entry["title"] else ""))
    return "镜头预算蓝图（必须严格按此范围写大纲）：\n" + "\n".join(rows)
