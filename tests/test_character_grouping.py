from __future__ import annotations

from comfyui_generator.core.mechanical import (
    dedupe_tags, normalize_prompt_text, split_tags, strip_cjk_segments,
)
from comfyui_generator.core.rewrite import REWRITE_SYSTEM
from comfyui_generator.core.single import SINGLE_SYSTEM_PROMPT
from comfyui_generator.core.storyboard import (
    CHARACTER_GROUPING, STORYBOARD_SYSTEM,
)


def test_split_tags_keeps_parenthesized_group_intact():
    prompt = (
        "1girl (long hair, black hair, white pleated skirt), "
        "1boy (nude male, faceless male), classroom, smile"
    )
    assert split_tags(prompt) == [
        "1girl (long hair, black hair, white pleated skirt)",
        "1boy (nude male, faceless male)",
        "classroom",
        "smile",
    ]


def test_normalize_prompt_text_preserves_group():
    text = "1girl (long hair, black hair), 1girl (long hair, black hair), smile"
    assert normalize_prompt_text(text) == "1girl (long hair, black hair), smile"


def test_grouping_not_confused_with_weight_syntax():
    group = "1girl (long hair, black hair)"
    assert dedupe_tags([group, group]) == [group]


def test_strip_cjk_segments_keeps_group_with_commas():
    text = "1girl (long hair, black hair), 中文描述, smile"
    assert strip_cjk_segments(text) == "1girl (long hair, black hair), smile"


def test_grouping_rule_in_all_generation_prompts():
    marker = "圆括号"
    assert marker in CHARACTER_GROUPING
    assert CHARACTER_GROUPING in STORYBOARD_SYSTEM
    assert CHARACTER_GROUPING in SINGLE_SYSTEM_PROMPT
    assert CHARACTER_GROUPING in REWRITE_SYSTEM
