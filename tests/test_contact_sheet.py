import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from comfyui_generator.ui.contact_sheet import build_contact_sheet, build_face_sheet


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _image(path: Path, color: str) -> Path:
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def test_build_contact_sheet(tmp_path):
    paths = [_image(tmp_path / "01.png", "#aa0000"),
             _image(tmp_path / "02.png", "#00aa00")]
    target = build_contact_sheet(paths, tmp_path / "sheet.png", columns=2,
                                 thumb_size=120)
    assert target.is_file()
    result = QImage(str(target))
    assert not result.isNull()
    assert result.width() > 120


def test_build_face_sheet_crops_top(tmp_path):
    paths = [_image(tmp_path / "01.png", "#0000aa")]
    target = build_face_sheet(paths, tmp_path / "faces.png", columns=1,
                              thumb_size=100, crop_ratio=0.5)
    assert target.is_file()
    result = QImage(str(target))
    assert not result.isNull()


def test_contact_sheet_rejects_empty(tmp_path):
    try:
        build_contact_sheet([], tmp_path / "empty.png")
    except ValueError:
        return
    raise AssertionError("empty contact sheet should fail")
