from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from comfyui_generator.core.pose import (
    COLORS, KEYPOINTS, LIMBS, POSE_PRESET_LABELS, pose_keypoints,
)


class PoseCanvas(QWidget):
    changed = Signal(str, float, float)
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.poses: dict[str, dict[str, tuple[float, float]]] = {}
        self.active_person = "girl"
        self.selected_name = ""
        self._drag = ""
        self.setMinimumSize(360, 480)
        self.setMouseTracking(True)

    def set_poses(self, poses: dict[str, dict[str, tuple[float, float]]]) -> None:
        self.poses = copy.deepcopy(poses)
        self.update()

    def set_active(self, person: str) -> None:
        self.active_person = person
        self.update()

    def _pixel(self, point: tuple[float, float]) -> QPointF:
        return QPointF(point[0] * self.width(), point[1] * self.height())

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 8, 12))
        radius = max(3, min(self.width(), self.height()) // 160)
        joint = max(4, min(self.width(), self.height()) // 110)
        for person, points in self.poses.items():
            if not points:
                continue
            base = 255 if person == self.active_person else 110
            for index, (start, end) in enumerate(LIMBS):
                color = COLORS[index % len(COLORS)]
                pen = QPen(QColor(color[0], color[1], color[2], base))
                pen.setWidth(max(2, radius - 1))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(self._pixel(points[KEYPOINTS[start]]),
                                 self._pixel(points[KEYPOINTS[end]]))
            for index, name in enumerate(KEYPOINTS):
                color = COLORS[index % len(COLORS)]
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color[0], color[1], color[2], base))
                center = self._pixel(points[name])
                painter.drawEllipse(center, joint, joint)
                if person == self.active_person and name == self.selected_name:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(255, 255, 255), 2))
                    painter.drawEllipse(center, joint + 5, joint + 5)
        painter.end()

    def _nearest(self, position: QPointF) -> str:
        points = self.poses.get(self.active_person) or {}
        best = ""
        distance = 16.0
        for name in KEYPOINTS:
            if name not in points:
                continue
            center = self._pixel(points[name])
            value = (center.x() - position.x()) ** 2 + (center.y() - position.y()) ** 2
            if value <= distance ** 2:
                best = name
                distance = value ** 0.5
        return best

    def mousePressEvent(self, event) -> None:  # noqa: N802
        name = self._nearest(event.position())
        if name:
            self._drag = name
            self.selected_name = name
            self.selected.emit(name)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._drag:
            return
        x = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
        y = max(0.0, min(1.0, event.position().y() / max(1, self.height())))
        self.poses[self.active_person][self._drag] = (x, y)
        self.changed.emit(self._drag, x, y)
        self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._drag = ""


class PoseEditorDialog(QDialog):
    def __init__(self, custom: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预览 / 编辑骨架库")
        self.resize(1080, 760)
        self._custom = copy.deepcopy(custom or {})
        self._poses: dict[str, dict[str, tuple[float, float]]] = {}
        self._loading = False
        self._preset = next(iter(POSE_PRESET_LABELS))

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.preset_list = QListWidget()
        for key, label in POSE_PRESET_LABELS.items():
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.preset_list.addItem(item)
        self.preset_list.setMinimumWidth(170)
        splitter.addWidget(self.preset_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        row = QHBoxLayout()
        row.addWidget(QLabel("编辑人物"))
        self.person = QComboBox()
        self.person.addItem("女主", "girl")
        self.person.addItem("男主", "boy")
        row.addWidget(self.person)
        row.addStretch(1)
        self.hint = QLabel("亮色为当前人物；拖动关键点或修改右侧坐标，保存后用于所有项目")
        row.addWidget(self.hint)
        right_layout.addLayout(row)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PoseCanvas()
        body.addWidget(self.canvas)
        self.table = QTableWidget(len(KEYPOINTS), 3)
        self.table.setHorizontalHeaderLabels(["关键点", "X", "Y"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        for row_index, name in enumerate(KEYPOINTS):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 0, item)
        body.addWidget(self.table)
        body.setSizes([650, 280])
        right_layout.addWidget(body, 1)
        splitter.addWidget(right)
        splitter.setSizes([180, 880])
        root.addWidget(splitter, 1)

        row = QHBoxLayout()
        self.btn_reset_person = QPushButton("重置当前人物")
        self.btn_reset_person.clicked.connect(self._reset_person)
        self.btn_reset_all = QPushButton("重置全部")
        self.btn_reset_all.clicked.connect(self._reset_all)
        row.addWidget(self.btn_reset_person)
        row.addWidget(self.btn_reset_all)
        row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        root.addLayout(row)

        self.preset_list.currentRowChanged.connect(self._load_preset)
        self.person.currentIndexChanged.connect(self._load_person)
        self.canvas.changed.connect(self._on_canvas_changed)
        self.canvas.selected.connect(self._select_row)
        self.table.itemChanged.connect(self._on_table_changed)
        self.preset_list.setCurrentRow(0)

    def _load_preset(self, row: int) -> None:
        item = self.preset_list.item(row)
        if item is None:
            return
        self._preset = str(item.data(Qt.ItemDataRole.UserRole))
        self._poses = pose_keypoints(self._preset, self._custom)
        self.canvas.set_poses(self._poses)
        self._load_table()

    def _load_person(self, _index: int) -> None:
        self.canvas.set_active(self.person.currentData())
        self._load_table()

    def _load_table(self) -> None:
        person = self.person.currentData()
        points = self._poses.get(person) or {}
        self._loading = True
        try:
            for row, name in enumerate(KEYPOINTS):
                point = points.get(name, (0.0, 0.0))
                self.table.setItem(row, 1, QTableWidgetItem("%.4f" % point[0]))
                self.table.setItem(row, 2, QTableWidgetItem("%.4f" % point[1]))
        finally:
            self._loading = False

    def _store_person(self) -> None:
        person = self.person.currentData()
        self._custom.setdefault(self._preset, {})[person] = {
            name: [round(value[0], 5), round(value[1], 5)]
            for name, value in self._poses[person].items()
        }

    def _on_canvas_changed(self, name: str, x: float, y: float) -> None:
        person = self.person.currentData()
        self._poses[person][name] = (x, y)
        self._store_person()
        self._loading = True
        try:
            row = KEYPOINTS.index(name)
            self.table.item(row, 1).setText("%.4f" % x)
            self.table.item(row, 2).setText("%.4f" % y)
        finally:
            self._loading = False

    def _on_table_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() == 0:
            return
        person = self.person.currentData()
        row = item.row()
        name = KEYPOINTS[row]
        try:
            x = max(0.0, min(1.0, float(self.table.item(row, 1).text())))
            y = max(0.0, min(1.0, float(self.table.item(row, 2).text())))
        except (AttributeError, TypeError, ValueError):
            return
        self._poses[person][name] = (x, y)
        self._store_person()
        self.canvas.set_poses(self._poses)
        self._loading = True
        try:
            self.table.item(row, 1).setText("%.4f" % x)
            self.table.item(row, 2).setText("%.4f" % y)
        finally:
            self._loading = False

    def _select_row(self, name: str) -> None:
        if name in KEYPOINTS:
            self.table.selectRow(KEYPOINTS.index(name))

    def _reset_person(self) -> None:
        person = self.person.currentData()
        presets = self._custom.get(self._preset)
        if isinstance(presets, dict):
            presets.pop(person, None)
            if not presets:
                self._custom.pop(self._preset, None)
        self._load_preset(self.preset_list.currentRow())

    def _reset_all(self) -> None:
        self._custom.clear()
        self._load_preset(self.preset_list.currentRow())

    def _save(self) -> None:
        self.accept()

    def custom_presets(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for preset, people in self._custom.items():
            if not isinstance(people, dict):
                continue
            base = pose_keypoints(preset, None)
            for person, values in people.items():
                if person not in base or not isinstance(values, dict):
                    continue
                diff = {}
                for name, point in values.items():
                    if name not in base[person] or not isinstance(point, (list, tuple)):
                        continue
                    x, y = float(point[0]), float(point[1])
                    bx, by = base[person][name]
                    if abs(x - bx) > 0.0001 or abs(y - by) > 0.0001:
                        diff[name] = [round(x, 5), round(y, 5)]
                if diff:
                    result.setdefault(preset, {})[person] = diff
        return result
