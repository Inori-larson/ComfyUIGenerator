"""Post-render verification coordinator.

Runs the WD tagger on a finished image, compares it to the shot prompt, and
asks the configured LLM to rewrite the prompt when an objective cast/layer
finding is found. This coordinator never writes prompt semantics itself; the
LLM produces the new prompt and the renderer re-runs it with the same seed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from comfyui_generator.core.rewrite import rewrite_shot_prompt
from comfyui_generator.core.tagdb import load_tag_database
from comfyui_generator.core.tagger import run_tagger, tagger_ready
from comfyui_generator.core.verification import VerifyThresholds, verify_render


@dataclass
class VerifyDecision:
    accepted: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    new_prompt: str = ""
    device: str = ""


MINIMAL_FIX_SYSTEM = (
    "You repair a single booru image prompt that failed an objective render check. "
    "Output only JSON {\"prompt\": \"...\"} with English comma-separated Danbooru tags. "
    "Make the MINIMAL change required to fix exactly the listed findings: adjust only the "
    "cast/count tags or clothing-layer/nudity tags that are wrong. "
    "Keep every other tag unchanged: do NOT add new actions, poses, camera angles, body "
    "features, characters, settings, fluids, or extra detail, and do NOT remove correct tags. "
    "Preserve the original scene, action, characters, and composition. Stay close to the "
    "original tag count. If a required person/state is missing, add the standard tag for it "
    "(e.g. 1boy / nude male / faceless male, or nipples / bare breasts); if a tag must not be "
    "visible under closed outer clothing, remove that inner-wear tag. No prose, no refusal.")


class RenderVerifier:
    def __init__(self, *, python: str, root: Path, base_dir: str,
                 tagger_config: Any, tagdb_config: Any,
                 llm_client: Any, llm_model: str,
                 character_tags: str = "", style_positive: str = "",
                 strip_appearance: bool = False,
                 log: Callable[[str], None] | None = None):
        self.python = python
        self.root = Path(root)
        self.base_dir = base_dir
        self.tagger_config = tagger_config
        self.tagdb_config = tagdb_config
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.character_tags = character_tags
        self.style_positive = style_positive
        self.strip_appearance = strip_appearance
        self.log = log or (lambda message: None)
        self._db = None

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.tagger_config, "enabled", False))

    @property
    def max_rerender(self) -> int:
        return max(0, int(getattr(self.tagger_config, "max_rerender", 2)))

    def database(self):
        if self._db is None:
            self._db = load_tag_database(
                getattr(self.tagdb_config, "csv_path", "") or None,
                getattr(self.tagdb_config, "alias_path", "") or None)
        return self._db

    def _thresholds(self) -> VerifyThresholds:
        t = self.tagger_config
        return VerifyThresholds(
            cast=float(getattr(t, "cast_threshold", 0.6)),
            layer=float(getattr(t, "layer_threshold", 0.5)),
            general=float(getattr(t, "general_threshold", 0.55)))

    def interrogate(self, image_path: str) -> dict[str, Any]:
        t = self.tagger_config
        ready, reason = tagger_ready(
            self.root, self.python, self.base_dir,
            getattr(t, "model_path", "") or None)
        if not ready:
            self.log("渲染后复核跳过：%s" % reason)
            return {}
        results = run_tagger(
            self.python, self.root, self.base_dir, [image_path],
            model_path=getattr(t, "model_path", "") or None,
            device=getattr(t, "device", "gpu"),
            general_threshold=0.30,
            log=None, timeout=1800.0)
        if not results:
            return {}
        return results[0]

    def verify(self, shot_prompt: str, tagger_result: dict[str, Any]
               ) -> list[dict[str, Any]]:
        return verify_render(shot_prompt, tagger_result,
                             self.database(), self._thresholds())

    @staticmethod
    def rewrite_instruction(findings: list[dict[str, Any]]) -> str:
        lines = [
            "成品图反推标签发现以下客观问题，请只修改相关英文 booru 标签修正，"
            "保持剧情、动作、场景和镜头不变，不要新增无关内容："]
        for finding in findings:
            lines.append("- %s（期望：%s；实际：%s）" % (
                finding.get("message", ""), finding.get("expected", ""),
                finding.get("actual", "")))
        lines.append("仍然必须只输出英文 Danbooru 标签，逗号分隔。")
        return "\n".join(lines)

    def rewrite(self, current_prompt: str,
                findings: list[dict[str, Any]]) -> str:
        raw = rewrite_shot_prompt(
            self.llm_client, self.llm_model, current_prompt,
            self.rewrite_instruction(findings),
            character_tags=self.character_tags,
            style_positive=self.style_positive,
            strip_appearance=self.strip_appearance,
            system_override=MINIMAL_FIX_SYSTEM,
            temperature=0.4)
        return self._constrain(raw, current_prompt, findings)

    def _constrain(self, rewritten: str, original: str,
                   findings: list[dict[str, Any]]) -> str:
        """Keep only tag changes justified by the finding text.

        No vocabulary whitelist: a newly added tag survives only if the
        finding itself mentioned that tag as missing/expected evidence.
        """
        from comfyui_generator.core.mechanical import dedupe_tags, split_tags

        orig = {t.strip().lower() for t in split_tags(original)}
        justification = " ".join(
            " ".join(str(f.get(key) or "") for key in ("expected", "actual", "evidence", "message"))
            for f in findings).lower()
        kept: list[str] = []
        for tag in dedupe_tags(split_tags(rewritten)):
            key = tag.strip().lower()
            if key in orig:
                kept.append(tag)
                continue
            if key and re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])",
                                 justification):
                kept.append(tag)
        return ", ".join(kept) or original

    def evaluate(self, image_path: str, shot_prompt: str) -> VerifyDecision:
        try:
            tagger_result = self.interrogate(image_path)
        except Exception as exc:
            self.log("渲染后复核跳过（%s）" % str(exc)[:200])
            return VerifyDecision(accepted=True)
        if not tagger_result or tagger_result.get("error"):
            return VerifyDecision(accepted=True)
        findings = self.verify(shot_prompt, tagger_result)
        device = str(tagger_result.get("device") or "")
        blocking = [f for f in findings if f.get("severity") == "P1"]
        if not blocking:
            return VerifyDecision(accepted=True, findings=findings,
                                  device=device)
        try:
            new_prompt = self.rewrite(shot_prompt, blocking)
        except Exception as exc:
            self.log("复核发现问题但重写失败，保留本图：%s" % str(exc)[:200])
            return VerifyDecision(accepted=True, findings=findings,
                                  device=device)
        return VerifyDecision(accepted=False, findings=findings,
                              new_prompt=new_prompt, device=device)
