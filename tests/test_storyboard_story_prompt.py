from __future__ import annotations

from comfyui_generator.core.storyboard import (
    BOORU_WORKFLOW, PROMPT_COVERAGE, STORYBOARD_SYSTEM,
)


def test_storyboard_system_injects_story_prompt_rules():
    assert PROMPT_COVERAGE in STORYBOARD_SYSTEM
    assert BOORU_WORKFLOW in STORYBOARD_SYSTEM
    assert "剧情必须写进 prompt" in STORYBOARD_SYSTEM
    assert "不能只写进 description" in STORYBOARD_SYSTEM
