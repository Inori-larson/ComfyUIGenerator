from comfyui_generator.core.detailers import build_detailer_choices, resolve_detailers


def test_fallback_choices_without_detectors():
    choices = {choice["key"]: choice for choice in build_detailer_choices([])}
    assert set(choices) == {"face", "eyes", "mouth", "expression", "hand"}
    assert choices["face"]["detector"] == "bbox/face_yolov8n.pt"
    assert choices["hand"]["detector"] == "bbox/hand_yolov8n.pt"
    assert choices["eyes"]["detector"] == "bbox/face_yolov8n.pt"
    assert choices["eyes"]["dedicated"] is False
    assert choices["face"]["dedicated"] is True


def test_dedicated_eye_detector():
    detectors = ["bbox/face_yolov8n.pt", "bbox/hand_yolov8n.pt", "bbox/eyes_v1.pt"]
    choices = {choice["key"]: choice for choice in build_detailer_choices(detectors)}
    assert choices["eyes"]["detector"] == "bbox/eyes_v1.pt"
    assert choices["eyes"]["dedicated"] is True


def test_resolve_order_and_none():
    detectors = ["bbox/face_yolov8n.pt", "bbox/hand_yolov8n.pt"]
    resolved = resolve_detailers("hand,face", detectors)
    assert [item["key"] for item in resolved] == ["hand", "face"]
    assert resolve_detailers("none", detectors) == []
    assert resolve_detailers("", detectors) == []


def test_resolve_raw_detector_path():
    detectors = ["bbox/face_yolov8n.pt"]
    resolved = resolve_detailers("bbox/face_yolov8n.pt", detectors)
    assert len(resolved) == 1
    assert resolved[0]["detector"] == "bbox/face_yolov8n.pt"
