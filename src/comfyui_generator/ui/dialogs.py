"""Secondary dialogs: project browser, trash, variant compare."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from comfyui_generator.core.project import (
    clear_trash, delete_from_trash, delete_project, list_trash, load_project,
    restore_from_trash, trash_original,
)
from comfyui_generator.core.tags import estimate_tokens
from comfyui_generator.ui.workers import TagTranslateWorker


class ProjectDialog(QDialog):
    def __init__(self, projects: list[dict[str, Any]], root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.projects = projects
        self.selected_path: str | None = None
        self.setWindowTitle("打开项目")
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["名称", "分镜", "更新时间"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for project in projects:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(project.get("name", project.get("id", "")))
            name.setData(Qt.ItemDataRole.UserRole, project.get("path"))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(str(project.get("shots", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(project.get("updated", "")))
        self.table.doubleClicked.connect(lambda _index: self._open())
        layout.addWidget(self.table)

        row = QHBoxLayout()
        btn_open = QPushButton("打开")
        btn_delete = QPushButton("删除项目")
        btn_cancel = QPushButton("取消")
        btn_open.clicked.connect(self._open)
        btn_delete.clicked.connect(self._delete)
        btn_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(btn_delete)
        row.addWidget(btn_open)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

    def _current(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        path = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return next((p for p in self.projects if p.get("path") == path), None)

    def _open(self) -> None:
        project = self._current()
        if not project:
            return
        self.selected_path = project["path"]
        self.accept()

    def _delete(self) -> None:
        project = self._current()
        if not project:
            return
        answer = QMessageBox.question(self, "删除项目", "确定删除项目「%s」及其回收站？" % project.get("name"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_project(load_project(project["path"]), self.root)
        self.projects = [p for p in self.projects if p.get("path") != project["path"]]
        self.table.removeRow(self.table.currentRow())


class TrashDialog(QDialog):
    def __init__(self, root: Path, project_id: str, parent=None):
        super().__init__(parent)
        self.root = root
        self.project_id = project_id
        self.setWindowTitle("回收站")
        self.resize(680, 460)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        btn_restore = QPushButton("还原")
        btn_delete = QPushButton("永久删除")
        btn_clear = QPushButton("清空回收站")
        btn_close = QPushButton("关闭")
        btn_restore.clicked.connect(self._restore)
        btn_delete.clicked.connect(self._delete)
        btn_clear.clicked.connect(self._clear)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_restore)
        row.addWidget(btn_delete)
        row.addStretch(1)
        row.addWidget(btn_clear)
        row.addWidget(btn_close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for path in list_trash(self.root, self.project_id):
            original = trash_original(path, self.project_id, self.root)
            item = QListWidgetItem(path.name + ("  ←  " + original if original else ""))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)

    def _selected(self) -> list[Path]:
        return [Path(item.data(Qt.ItemDataRole.UserRole)) for item in self.list.selectedItems()]

    def _restore(self) -> None:
        for path in self._selected():
            try:
                restore_from_trash(path, root=self.root, project_id=self.project_id)
            except Exception as exc:
                QMessageBox.warning(self, "还原失败", str(exc))
        self.refresh()

    def _delete(self) -> None:
        paths = self._selected()
        if not paths:
            return
        if QMessageBox.question(self, "永久删除", "确定永久删除 %d 个文件？" % len(paths)) \
                != QMessageBox.StandardButton.Yes:
            return
        for path in paths:
            delete_from_trash(path, self.root, self.project_id)
        self.refresh()

    def _clear(self) -> None:
        if QMessageBox.question(self, "清空回收站", "确定永久删除全部文件？") \
                != QMessageBox.StandardButton.Yes:
            return
        clear_trash(self.root, self.project_id)
        self.refresh()


class CompareDialog(QDialog):
    def __init__(self, title: str, entries: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.entries = entries
        self.setWindowTitle("变体对比 · %s" % title)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        hint = QLabel("取消勾选要丢弃的变体；应用后会移入项目回收站。")
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(12)
        self.checks: dict[str, QCheckBox] = {}
        for index, entry in enumerate(entries):
            card = QWidget()
            card_layout = QVBoxLayout(card)
            image = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(entry["data"])
            image.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(image)
            check = QCheckBox(entry["label"])
            check.setChecked(True)
            card_layout.addWidget(check)
            self.checks[entry["id"]] = check
            grid.addWidget(card, index // 3, index % 3)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("应用")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def discarded(self) -> list[dict[str, Any]]:
        return [entry for entry in self.entries if not self.checks[entry["id"]].isChecked()]


class TagReferenceDialog(QDialog):
    def __init__(self, tags: list[str], parent=None, cfg=None, model: str = "",
                 cache_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("参考标签")
        self.resize(760, 640)
        self.worker: TagTranslateWorker | None = None
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标签（中文或英文）")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.translate_status = QLabel("")
        self.translate_status.setWordWrap(True)
        layout.addWidget(self.translate_status)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for tag in tags:
            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _item: self._update_count())
        layout.addWidget(self.list, 1)
        self.count_label = QLabel("")
        layout.addWidget(self.count_label)

        row = QHBoxLayout()
        btn_visible = QPushButton("全选可见")
        btn_clear = QPushButton("清空选择")
        btn_add = QPushButton("加入激活标签")
        btn_cancel = QPushButton("取消")
        btn_visible.clicked.connect(self._select_visible)
        btn_clear.clicked.connect(self._clear_checks)
        btn_add.clicked.connect(self._accept_selected)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_visible)
        row.addWidget(btn_clear)
        row.addStretch(1)
        row.addWidget(btn_add)
        row.addWidget(btn_cancel)
        layout.addLayout(row)
        self._update_count()

        if cfg is not None and model and tags:
            self.translate_status.setText("正在用模型翻译参考标签，可先按英文搜索...")
            worker = TagTranslateWorker(cfg, model, tags, cache_path)
            worker.batch.connect(self._apply_translations)
            worker.failed.connect(self._translation_failed)
            worker.finished.connect(self._translation_finished)
            worker.finished.connect(worker.deleteLater)
            self.finished.connect(lambda _result: worker.requestInterruption())
            self.worker = worker
            worker.start()
        else:
            self.translate_status.setText("未连接 Ollama，参考标签暂不翻译。")

    def _apply_translations(self, mapping: dict[str, str]) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            tag = item.data(Qt.ItemDataRole.UserRole) or item.text()
            translation = mapping.get(tag)
            if translation and translation != tag:
                item.setText("%s  |  %s" % (translation, tag))

    def _translation_failed(self, message: str) -> None:
        self.translate_status.setText("参考标签翻译失败：%s" % message)

    def _translation_finished(self) -> None:
        self.translate_status.setText("参考标签中文翻译已更新。")
        self.worker = None

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
        super().closeEvent(event)

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _select_visible(self) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_checks(self) -> None:
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(Qt.CheckState.Unchecked)

    def _update_count(self) -> None:
        selected = self.selected_tags()
        self.count_label.setText("已选 %d 个标签 · 约 %d tokens" % (
            len(selected), estimate_tokens(selected)))

    def selected_tags(self) -> list[str]:
        return [self.list.item(index).data(Qt.ItemDataRole.UserRole) or self.list.item(index).text()
                for index in range(self.list.count())
                if self.list.item(index).checkState() == Qt.CheckState.Checked]

    def _accept_selected(self) -> None:
        if not self.selected_tags():
            QMessageBox.information(self, "提示", "先勾选要加入的标签。")
            return
        self.accept()


class ShotDetailsDialog(QDialog):
    """Show every storyboard shot with Chinese text, plot outline and raw JSON."""

    def __init__(self, shots: list[dict[str, Any]], outlines: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("分镜详情")
        self.resize(1120, 760)
        self._shots = [dict(shot) for shot in shots]
        self._outlines = list(outlines)
        self._raw: list[str] = []
        self._loading = False
        self._current_row = -1
        for shot in self._shots:
            self._raw.append(json.dumps({
                "id": str(shot.get("id", "")),
                "name": str(shot.get("name", "")),
                "prompt": str(shot.get("prompt", "")),
            }, ensure_ascii=False, indent=2))

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        self.list.setMaximumWidth(320)
        for index, shot in enumerate(self._shots):
            self.list.addItem("%s  %s" % (shot.get("id", ""), shot.get("name", "")))
        splitter.addWidget(self.list)

        right = QWidget()
        form = QVBoxLayout(right)
        self.heading = QLabel("")
        form.addWidget(self.heading)

        form.addWidget(QLabel("中文提示词（只读）"))
        self.zh_edit = QPlainTextEdit()
        self.zh_edit.setReadOnly(True)
        self.zh_edit.setMinimumHeight(90)
        form.addWidget(self.zh_edit)

        form.addWidget(QLabel("对应分镜的中文大纲（只读）"))
        self.outline_edit = QPlainTextEdit()
        self.outline_edit.setReadOnly(True)
        self.outline_edit.setMinimumHeight(80)
        form.addWidget(self.outline_edit)

        form.addWidget(QLabel("实际生效的英文原始 JSON（可编辑；保存后用于出图）"))
        self.json_edit = QPlainTextEdit()
        self.json_edit.setMinimumHeight(220)
        self.json_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        form.addWidget(self.json_edit, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        row = QHBoxLayout()
        hint = QLabel("修改英文 prompt 后保存，会更新分镜并自动重新译中文。")
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        btn_cancel = QPushButton("取消")
        btn_save = QPushButton("保存修改")
        btn_save.setObjectName("Primary")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        layout.addLayout(row)

        self.list.currentRowChanged.connect(self._switch_shot)
        self._loading = True
        if self._shots:
            self.list.setCurrentRow(0)
        self._loading = False
        self._load_shot(0 if self._shots else -1)

    def _store_current(self) -> None:
        row = self._current_row
        if 0 <= row < len(self._raw):
            self._raw[row] = self.json_edit.toPlainText()

    def _switch_shot(self, row: int) -> None:
        if self._loading:
            return
        self._store_current()
        self._load_shot(row)

    def _load_shot(self, row: int) -> None:
        self._current_row = row
        if not (0 <= row < len(self._shots)):
            self.heading.setText("没有分镜")
            self.zh_edit.clear()
            self.outline_edit.clear()
            self.json_edit.clear()
            return
        shot = self._shots[row]
        self.heading.setText("分镜 %s · %s" % (shot.get("id", ""), shot.get("name", "")))
        self.zh_edit.setPlainText(str(shot.get("prompt_zh") or shot.get("prompt") or ""))
        outline = self._outlines[row] if row < len(self._outlines) else ""
        self.outline_edit.setPlainText(outline or "（剧情没有按编号提供对应大纲）")
        self.json_edit.setPlainText(self._raw[row])

    def _save(self) -> None:
        self._store_current()
        updated: list[dict[str, Any]] = []
        for index, raw in enumerate(self._raw):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.list.setCurrentRow(index)
                QMessageBox.warning(
                    self, "JSON 格式错误",
                    "第 %s 镜 JSON 无法解析：\n第 %d 行：%s" % (
                        self._shots[index].get("id", index + 1), exc.lineno, exc.msg))
                return
            if not isinstance(data, dict):
                self.list.setCurrentRow(index)
                QMessageBox.warning(self, "JSON 格式错误", "每一镜的 JSON 必须是对象。")
                return
            prompt = str(data.get("prompt") or "").strip()
            if not prompt:
                self.list.setCurrentRow(index)
                QMessageBox.warning(self, "提示词为空", "prompt 不能为空。")
                return
            shot = dict(self._shots[index])
            old_prompt = str(shot.get("prompt", ""))
            shot["id"] = str(data.get("id", shot.get("id", ""))).strip()
            shot["name"] = str(data.get("name", shot.get("name", ""))).strip()
            shot["prompt"] = prompt
            shot["_prompt_changed"] = prompt != old_prompt
            updated.append(shot)
        self._shots = updated
        self.accept()

    def updated_shots(self) -> list[dict[str, Any]]:
        return [dict(shot) for shot in self._shots]
