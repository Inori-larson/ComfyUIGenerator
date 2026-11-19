from __future__ import annotations

from comfyui_generator.core.pose import resolve_pose_preset


def test_explicit_pose_id_is_used():
    assert resolve_pose_preset({"pose_id": "cowgirl"}) == "cowgirl"
    assert resolve_pose_preset({"pose_id": "classic_69"}) == "classic_69"


def test_user_override_wins():
    assert resolve_pose_preset({"pose_id": "cowgirl"}, "spooning") == "spooning"


def test_no_keyword_inference():
    # Poses are never inferred from prompt/description text anymore.
    assert resolve_pose_preset({"prompt": "cowgirl, riding"}) == ""
    assert resolve_pose_preset({"description": "男主从后面抱起她"}) == ""
    assert resolve_pose_preset({"prompt": "missionary, legs up"}) == ""


def test_auto_without_declaration_means_no_pose():
    assert resolve_pose_preset({"prompt": "doggy"}, "auto") == ""
