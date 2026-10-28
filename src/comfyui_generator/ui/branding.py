"""Application icon and in-app branding assets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PNG = ASSETS_DIR / "app_icon.png"
ICON_ICO = ASSETS_DIR / "app_icon.ico"


def app_icon() -> QIcon:
    icon = QIcon()
    for path in (ICON_ICO, ICON_PNG):
        if path.is_file():
            icon.addFile(str(path))
    return icon


def logo_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(str(ICON_PNG))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
