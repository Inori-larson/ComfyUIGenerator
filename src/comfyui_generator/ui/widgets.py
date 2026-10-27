"""Reusable searchable dropdown."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QCompleter


class SearchComboBox(QComboBox):
    """Editable combo with contains-search and strict selection.

    The user can type to filter, but only values from the list can be committed
    unless ``allow_free_text`` is enabled.
    """

    def __init__(self, parent=None, placeholder: str = "输入以搜索…", allow_free_text: bool = False):
        super().__init__(parent)
        self.allow_free_text = allow_free_text
        self._last_valid = 0
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(25)
        line = self.lineEdit()
        line.setPlaceholderText(placeholder)
        line.setClearButtonEnabled(False)
        line.installEventFilter(self)
        line.editingFinished.connect(self._normalize)
        self.currentIndexChanged.connect(self._remember)
        self._rebuild_completer()

    def _remember(self, index: int) -> None:
        if index >= 0:
            self._last_valid = index

    def _rebuild_completer(self) -> None:
        completer = QCompleter(self.model(), self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setMaxVisibleItems(25)
        completer.activated.connect(self._on_activated)
        self.setCompleter(completer)
        if self.lineEdit() and self.lineEdit().completer() is not completer:
            self.lineEdit().setCompleter(completer)

    def _on_activated(self, text: str) -> None:
        index = self.findText(text, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
        if index < 0:
            index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)
            self.lineEdit().setText(self.itemText(index))

    def _normalize(self) -> None:
        if self.allow_free_text or self.count() == 0:
            return
        text = self.currentText().strip()
        index = self.findText(text)
        if index < 0:
            matches = [i for i in range(self.count()) if text.lower() in self.itemText(i).lower()]
            if len(matches) == 1:
                index = matches[0]
        if index < 0:
            index = max(0, min(self._last_valid, self.count() - 1))
        self.setCurrentIndex(index)
        self.lineEdit().setText(self.itemText(index))

    def setItems(self, items: list[tuple[str, Any]]) -> None:
        current_data = self.currentData()
        current_text = self.currentText()
        self.blockSignals(True)
        self.clear()
        for text, data in items:
            self.addItem(text, data)
        self.blockSignals(False)
        self._rebuild_completer()

        index = -1
        if current_data is not None:
            index = self.findData(current_data)
        if index < 0 and current_text:
            index = self.findText(current_text)
        if index < 0 and self.count():
            index = 0
        if index >= 0:
            self.setCurrentIndex(index)
            self.lineEdit().setText(self.itemText(index))
            self._last_valid = index
        elif self.count() == 0:
            self.setCurrentIndex(-1)
            self.lineEdit().clear()

    def setValues(self, values: list[str], current: str = "") -> None:
        self.setItems([(value, value) for value in values])
        if current:
            self.selectValue(current)

    def selectValue(self, value: Any) -> None:
        index = self.findData(value)
        if index < 0:
            index = self.findText(str(value))
        if index >= 0:
            self.setCurrentIndex(index)
            self.lineEdit().setText(self.itemText(index))

    def currentValue(self) -> Any:
        data = self.currentData()
        return data if data is not None else self.currentText().strip()

    def selectFirst(self) -> None:
        if self.count():
            self.setCurrentIndex(0)
            self.lineEdit().setText(self.itemText(0))

    # ------------------------------------------------------------- search UX

    def show_popup_search(self) -> None:
        """Show the full list immediately and select current text for typing."""
        completer = self.completer()
        if completer is None or self.count() == 0:
            return
        line = self.lineEdit()
        line.setFocus(Qt.FocusReason.MouseFocusReason)
        line.selectAll()
        completer.setCompletionPrefix("")
        popup = completer.popup()
        popup.setMinimumWidth(max(self.width(), 320))
        completer.complete()

    def showPopup(self) -> None:  # noqa: N802
        self.show_popup_search()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            QTimer.singleShot(0, self.show_popup_search)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.lineEdit():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                QTimer.singleShot(0, self.show_popup_search)
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                QTimer.singleShot(0, self.lineEdit().selectAll)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        completer = self.completer()
        if (event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up)
                and completer is not None and not completer.popup().isVisible()):
            self.show_popup_search()
            return
        super().keyPressEvent(event)
