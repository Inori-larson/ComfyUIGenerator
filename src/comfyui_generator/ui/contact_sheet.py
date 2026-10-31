"""Contact sheets for visual continuity review.

Uses Qt's image primitives so no extra Pillow/numpy dependency is needed.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QImageReader, QPainter


def _load_image(path: Path) -> QImage:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return reader.read()


def _cell(
    painter: QPainter, image: QImage, x: int, y: int, size: int,
    label: str, label_height: int,
) -> None:
    scaled = image.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    painter.drawImage(
        QPoint(x + (size - scaled.width()) // 2,
               y + (size - scaled.height()) // 2), scaled)
    font = QFont()
    font.setPointSize(9)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    text = metrics.elidedText(label, Qt.TextElideMode.ElideMiddle, size)
    painter.setPen(QColor("#333333"))
    painter.drawText(
        QRect(x, y + size, size, label_height),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)


def _build(
    paths: Iterable[str | Path], output: str | Path, *, columns: int,
    thumb_size: int, label_height: int, title: str, face_crop: bool,
    crop_ratio: float,
) -> Path:
    images: list[tuple[QImage, str]] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        image = _load_image(path)
        if image.isNull():
            continue
        if face_crop:
            height = max(1, int(image.height() * max(0.1, min(1.0, crop_ratio))))
            image = image.copy(0, 0, image.width(), height)
        images.append((image, path.stem))
    if not images:
        raise ValueError("没有可用的图片")

    columns = max(1, int(columns))
    thumb_size = max(64, int(thumb_size))
    rows = math.ceil(len(images) / columns)
    margin = 16
    gap = 12
    title_height = 32 if title else 0
    cell_height = thumb_size + label_height
    width = margin * 2 + columns * thumb_size + (columns - 1) * gap
    height = margin * 2 + title_height + rows * cell_height + (rows - 1) * gap
    canvas = QImage(width, height, QImage.Format.Format_RGB32)
    canvas.fill(QColor("#f4f1ea"))
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if title:
            font = QFont()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#222222"))
            painter.drawText(
                QRect(margin, margin, width - margin * 2, title_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        top = margin + title_height
        for index, (image, label) in enumerate(images):
            row, column = divmod(index, columns)
            x = margin + column * (thumb_size + gap)
            y = top + row * (cell_height + gap)
            _cell(painter, image, x, y, thumb_size, label, label_height)
    finally:
        painter.end()
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(target), "PNG"):
        raise OSError("联系表保存失败：%s" % target)
    return target


def build_contact_sheet(paths: Iterable[str | Path], output: str | Path,
                        *, columns: int = 4, thumb_size: int = 320,
                        title: str = "Storyboard") -> Path:
    return _build(
        paths, output, columns=columns, thumb_size=thumb_size,
        label_height=24, title=title, face_crop=False, crop_ratio=1.0)


def build_face_sheet(paths: Iterable[str | Path], output: str | Path,
                     *, columns: int = 6, thumb_size: int = 220,
                     title: str = "Face / Character Check",
                     crop_ratio: float = 0.5) -> Path:
    return _build(
        paths, output, columns=columns, thumb_size=thumb_size,
        label_height=22, title=title, face_crop=True, crop_ratio=crop_ratio)
