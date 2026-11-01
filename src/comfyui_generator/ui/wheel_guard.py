"""Prevent accidental value changes from hover-scrolling config widgets."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox


class WheelGuard(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._armed: set[QAbstractSpinBox] = set()

    @staticmethod
    def _spinbox(obj) -> QAbstractSpinBox | None:
        widget = obj
        while widget is not None:
            if isinstance(widget, QAbstractSpinBox):
                return widget
            widget = widget.parent()
        return None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            self._armed.clear()
            spin = self._spinbox(obj)
            if spin is not None and event.button() == Qt.MouseButton.LeftButton:
                self._armed.add(spin)
            return False
        if kind == QEvent.Type.FocusOut:
            spin = self._spinbox(obj)
            if spin is not None:
                self._armed.discard(spin)
            return False
        if kind != QEvent.Type.Wheel:
            return False
        if isinstance(obj, QComboBox):
            event.ignore()
            return True
        spin = self._spinbox(obj)
        if spin is not None and spin not in self._armed:
            event.ignore()
            return True
        return False


def install_wheel_guard(app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is None or getattr(app, "_config_wheel_guard", None) is not None:
        return
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    app._config_wheel_guard = guard
