"""Settings dialog (paths, ports, runtime options)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from comfyui_generator.ui.widgets import SearchComboBox

from comfyui_generator.core.config import AppConfig, save_config


class PathRow(QLineEdit):
    def __init__(self, value: str, directory: bool = False):
        super().__init__(value)
        self.directory = directory

    def pick(self) -> None:
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, "选择目录", self.text() or str(Path.home()))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", self.text() or str(Path.home()))
        if path:
            self.setText(path.replace("/", "\\"))


def _path_row(layout: QFormLayout, label: str, value: str, directory: bool = False) -> PathRow:
    row = QHBoxLayout()
    edit = PathRow(value, directory)
    button = QPushButton("浏览")
    button.clicked.connect(edit.pick)
    row.addWidget(edit)
    row.addWidget(button)
    layout.addRow(label, row)
    return edit


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None, models: list[str] | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.models = list(models or [])
        self.setWindowTitle("设置")
        self.resize(760, 720)

        root = QVBoxLayout(self)
        comfy_box = QGroupBox("ComfyUI")
        comfy_form = QFormLayout(comfy_box)
        self.mode = SearchComboBox(placeholder="搜索模式")
        self.mode.setItems([
            ("auto（探测→没有则启动）", "auto"),
            ("attach（只连接已有）", "attach"),
            ("managed（总是托管）", "managed"),
        ])
        self.mode.selectValue(cfg.comfy.mode)
        comfy_form.addRow("连接模式", self.mode)

        self.host = QLineEdit(cfg.comfy.host)
        comfy_form.addRow("地址", self.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(cfg.comfy.port)
        comfy_form.addRow("端口", self.port)
        self.python = _path_row(comfy_form, "Python 解释器", cfg.comfy.python)
        self.main_py = _path_row(comfy_form, "ComfyUI main.py", cfg.comfy.main_py)
        self.base_dir = _path_row(comfy_form, "base 目录", cfg.comfy.base_dir, directory=True)
        self.preview_method = SearchComboBox(placeholder="搜索预览方式")
        self.preview_method.setItems([(x, x) for x in ("latent2rgb", "auto", "taesd", "none")])
        self.preview_method.selectValue(cfg.comfy.preview_method)
        comfy_form.addRow("预览方式", self.preview_method)
        self.preview_size = QSpinBox()
        self.preview_size.setRange(128, 1024)
        self.preview_size.setValue(cfg.comfy.preview_size)
        comfy_form.addRow("预览尺寸", self.preview_size)
        self.keep_running = QCheckBox("退出应用时保留下次启动的 ComfyUI")
        self.keep_running.setChecked(cfg.comfy.keep_running_on_exit)
        comfy_form.addRow("", self.keep_running)
        root.addWidget(comfy_box)

        ollama_box = QGroupBox("Ollama")
        ollama_form = QFormLayout(ollama_box)
        self.ollama_host = QLineEdit(cfg.ollama.host)
        ollama_form.addRow("地址", self.ollama_host)
        self.ollama_port = QSpinBox()
        self.ollama_port.setRange(1, 65535)
        self.ollama_port.setValue(cfg.ollama.port)
        ollama_form.addRow("端口", self.ollama_port)
        self.ollama_exe = _path_row(ollama_form, "ollama.exe", cfg.ollama.exe)
        self.ollama_model = SearchComboBox(placeholder="扫描到的 Ollama 模型，可搜索")
        self.ollama_model.setItems([("自动（第一个可用）", "")] +
                                   [(name, name) for name in self.models])
        self.ollama_model.selectValue(cfg.ollama.default_model or "")
        ollama_form.addRow("默认模型", self.ollama_model)
        root.addWidget(ollama_box)

        app_box = QGroupBox("应用")
        app_form = QFormLayout(app_box)
        self.template = _path_row(app_form, "默认模板 JSON", cfg.generation.template)
        self.language = SearchComboBox(placeholder="搜索语言")
        self.language.setItems([("中文", "zh-CN"), ("English", "en-US")])
        self.language.selectValue(cfg.ui.language)
        app_form.addRow("界面语言（重启生效）", self.language)
        self.storage = QLineEdit(str(cfg.root))
        self.storage.setReadOnly(True)
        app_form.addRow("数据目录", self.storage)
        root.addWidget(app_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        c = self.cfg
        c.comfy.mode = self.mode.currentValue()
        c.comfy.host = self.host.text().strip() or "127.0.0.1"
        c.comfy.port = self.port.value()
        c.comfy.python = self.python.text().strip()
        c.comfy.main_py = self.main_py.text().strip()
        c.comfy.base_dir = self.base_dir.text().strip()
        if c.comfy.base_dir:
            c.comfy.input_dir = str(Path(c.comfy.base_dir) / "input")
            c.comfy.output_dir = str(Path(c.comfy.base_dir) / "output")
            c.comfy.user_dir = str(Path(c.comfy.base_dir) / "user")
        c.comfy.preview_method = self.preview_method.currentValue()
        c.comfy.preview_size = self.preview_size.value()
        c.comfy.keep_running_on_exit = self.keep_running.isChecked()
        c.ollama.host = self.ollama_host.text().strip() or "127.0.0.1"
        c.ollama.port = self.ollama_port.value()
        c.ollama.exe = self.ollama_exe.text().strip()
        c.ollama.default_model = self.ollama_model.currentValue() or ""
        c.generation.template = self.template.text().strip()
        c.ui.language = self.language.currentValue()
        save_config(c)
        self.accept()
