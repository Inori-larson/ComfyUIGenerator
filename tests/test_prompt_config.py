from comfyui_generator.core.jobs import build_tasks
from comfyui_generator.core.workflow import compose_prompts


def _cfg():
    return {
        "style": {
            "positive": "STYLE_POS, masterpiece",
            "negative": "STYLE_NEG, bad quality",
        },
        "character": {"tags": "silver hair"},
        "settings": {"split": {"enabled": True}},
    }


def test_every_task_kind_uses_configured_positive_and_negative():
    shots = [
        {
            "id": "01", "name": "a", "prompt": "1girl, bedroom",
            "ai_expansions": ["1girl, bedroom, smile", "1girl, bedroom, nude"],
        },
        {
            "id": "02", "name": "b", "prompt": "1girl, 1boy, bedroom",
            "cast": "1girl 1boy",
        },
    ]
    tasks = build_tasks(_cfg(), shots, 1, "fixed", 1, expansions=2)
    assert any(task.kind == "expand" for task in tasks)
    for task in tasks:
        positive, negative = compose_prompts(_cfg(), task.shot)
        assert "STYLE_POS" in positive
        assert "STYLE_NEG" in negative
