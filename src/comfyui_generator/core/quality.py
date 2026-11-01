"""Prompt-level continuity checks before rendering.

Image-level checks (face embedding, pose consistency) are intentionally kept
out of this module so the preflight stays fast and has no extra model
dependencies.  It catches the cheap mistakes that otherwise waste a batch.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comfyui_generator.core.continuity import apply_auto_grammar


@dataclass
class QualityReport:
    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.critical and not self.warnings

    def lines(self) -> list[str]:
        rows = ["严重：" + item for item in self.critical]
        rows += ["警告：" + item for item in self.warnings]
        rows += ["提示：" + item for item in self.info]
        return rows or ["未发现连续性问题。"]


_CHINESE = re.compile(r"[\u4e00-\u9fff]")


def _check_file(report: QualityReport, label: str, value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    path = Path(text)
    if path.is_absolute() and not path.is_file():
        report.critical.append("%s不存在：%s" % (label, text))


def check_project(project: dict[str, Any]) -> QualityReport:
    report = QualityReport()
    character = project.get("character") or {}
    continuity = project.get("continuity") or {}

    for key, label in (("character", "角色锚点"), ("scene", "场景锚点"),
                       ("state", "连续性台账"), ("negative", "额外负面词")):
        value = str(continuity.get(key) or "")
        if _CHINESE.search(value):
            report.warnings.append(
                "%s含中文，CLIP 可能忽略；建议改英文 Booru 标签" % label)
    if _CHINESE.search(str(character.get("tags") or "")):
        report.warnings.append("角色标签含中文，出图前需要英文标签")

    ip = character.get("ipadapter") or {}
    if character.get("use_ipadapter") and not ip.get("reference"):
        report.critical.append("已启用角色参考图，但没有填写参考图路径")
    _check_file(report, "角色参考图", ip.get("reference"))
    style_ref = project.get("style_ref") or {}
    if style_ref.get("enabled"):
        if not style_ref.get("image"):
            report.critical.append("已启用画风参考图，但没有填写图片路径")
        _check_file(report, "画风参考图", style_ref.get("image"))

    grammar = continuity.get("grammar") or {}
    grammar_auto = bool(grammar.get("auto", True))
    shots = project.get("shots") or []
    if not shots:
        report.warnings.append("项目没有可生成的分镜")
    for shot in shots:
        shot_id = str(shot.get("id") or "?")
        prompt = str(shot.get("prompt") or "")
        if not prompt.strip():
            report.warnings.append("镜头 %s 提示词为空" % shot_id)
        elif _CHINESE.search(prompt):
            report.warnings.append("镜头 %s 提示词含中文" % shot_id)
        if grammar_auto and not (
                str(shot.get("shot_size") or "").strip()
                and str(shot.get("camera_angle") or "").strip()):
            report.info.append("镜头 %s 没有景别/机位，将使用默认构图" % shot_id)
        for key, label in (("continuity_state", "连续性台账"),
                           ("continuity_scene", "场景锚点")):
            if _CHINESE.search(str(shot.get(key) or "")):
                report.warnings.append(
                    "镜头 %s 的%s含中文，建议改英文标签" % (shot_id, label))
    if not str(continuity.get("character") or "").strip():
        report.info.append("未填写角色锚点；跨镜人物一致性只能依赖角色 LoRA/参考图")
    if not str(continuity.get("scene") or "").strip():
        report.info.append("未填写场景锚点；换场景时背景可能漂移")
    return report


def format_report(report: QualityReport) -> str:
    return "\n".join(report.lines())


def repair_project(project: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply only conservative, reversible repairs.

    Chinese anchors, empty prompts and missing files cannot be guessed safely,
    so they are left for the user to fix.
    """
    data = copy.deepcopy(project)
    changes: list[str] = []
    character = data.setdefault("character", {})
    ip = character.get("ipadapter") or {}
    ref = str(ip.get("reference") or "").strip()
    ref_missing = bool(ref) and Path(ref).is_absolute() and not Path(ref).is_file()
    if character.get("use_ipadapter") and (not ref or ref_missing):
        character["use_ipadapter"] = False
        changes.append("关闭缺少参考图的 IPAdapter")
    style_ref = data.get("style_ref") or {}
    style_image = str(style_ref.get("image") or "").strip()
    style_missing = (bool(style_image) and Path(style_image).is_absolute()
                     and not Path(style_image).is_file())
    if style_ref.get("enabled") and (not style_image or style_missing):
        style_ref["enabled"] = False
        data["style_ref"] = style_ref
        changes.append("关闭缺少图片的画风参考")

    shots = data.get("shots") or []

    before = [(shot.get("shot_size"), shot.get("camera_angle"))
              for shot in shots if isinstance(shot, dict)]
    apply_auto_grammar(shots, data.get("continuity") or {})
    after = [(shot.get("shot_size"), shot.get("camera_angle"))
             for shot in shots if isinstance(shot, dict)]
    if before != after:
        changes.append("补齐缺失的景别/机位")
    return data, changes
