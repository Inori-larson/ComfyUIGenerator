from pathlib import Path

from comfyui_generator.core.detailers import (
    build_detailer_choices, local_detectors, resolve_detailers,
)


def test_empty_detector_list_has_no_choices():
    assert build_detailer_choices([]) == []


def test_choices_follow_scanned_models():
    detectors = ["bbox/face_yolov8n.pt", "bbox/hand_yolov8n.pt",
                 "bbox/eyes_v1.pt", "segm/person_yolov8m-seg.pt"]
    choices = build_detailer_choices(detectors)
    assert [choice["detector"] for choice in choices] == detectors
    by_detector = {choice["detector"]: choice for choice in choices}
    assert "脸部重绘" in by_detector["bbox/face_yolov8n.pt"]["label"]
    assert "face_yolov8n" in by_detector["bbox/face_yolov8n.pt"]["label"]
    assert "眼睛重绘" in by_detector["bbox/eyes_v1.pt"]["label"]
    assert "人物重绘" in by_detector["segm/person_yolov8m-seg.pt"]["label"]
    assert by_detector["bbox/face_yolov8n.pt"]["prompt"].startswith("detailed face")


def test_unknown_model_gets_generic_label():
    choices = build_detailer_choices(["bbox/custom_detector.pt"])
    assert len(choices) == 1
    assert choices[0]["label"].startswith("重绘")
    assert "custom detector" in choices[0]["prompt"]


def test_duplicate_detectors_are_ignored():
    detectors = ["bbox/face_yolov8n.pt", "bbox\\face_yolov8n.pt"]
    choices = build_detailer_choices(detectors)
    assert len(choices) == 1


def test_resolve_order_keywords_and_raw_paths():
    detectors = ["bbox/face_yolov8n.pt", "bbox/hand_yolov8n.pt",
                 "bbox/eyes_v1.pt", "bbox/face_yolov8s.pt"]
    resolved = resolve_detailers("hand,face", detectors)
    assert [item["kind"] for item in resolved] == ["hand", "face"]
    assert resolved[0]["detector"] == "bbox/hand_yolov8n.pt"

    by_kind = resolve_detailers("eyes", detectors)
    assert by_kind[0]["detector"] == "bbox/eyes_v1.pt"

    raw = resolve_detailers("bbox/face_yolov8s.pt", detectors)
    assert raw[0]["detector"] == "bbox/face_yolov8s.pt"

    assert resolve_detailers("none", detectors) == []
    assert resolve_detailers("", detectors) == []


def test_local_detectors_scan(tmp_path):
    (tmp_path / "models" / "ultralytics" / "bbox").mkdir(parents=True)
    (tmp_path / "models" / "ultralytics" / "segm").mkdir(parents=True)
    (tmp_path / "models" / "ultralytics" / "bbox" / "face.pt").write_bytes(b"")
    (tmp_path / "models" / "ultralytics" / "segm" / "person.pt").write_bytes(b"")
    found = local_detectors(tmp_path)
    assert found == ["bbox/face.pt", "segm/person.pt"]
    assert local_detectors(None) == []
