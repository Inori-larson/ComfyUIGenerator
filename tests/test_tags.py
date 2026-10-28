from comfyui_generator.core.tags import dedupe_tag_list, dedupe_tags


def test_dedupe_tags_preserves_order_and_case_insensitive_duplicates():
    assert dedupe_tags("solo, Solo, park,  solo") == "solo, park"
    assert dedupe_tag_list(["hero", "HERO", "red hair"]) == ["hero", "red hair"]
    assert dedupe_tags("") == ""
