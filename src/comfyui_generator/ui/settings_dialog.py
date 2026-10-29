"""Settings dialog (paths, ports, runtime options)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel,
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
        self.ollama_model = SearchComboBox(
            placeholder="扫描到的 Ollama 模型，可搜索或直接输入", allow_free_text=True)
        model_names = list(dict.fromkeys(self.models + ([cfg.ollama.default_model]
                                                       if cfg.ollama.default_model else [])))
        self.ollama_model.setItems([("自动（第一个可用）", "")] +
                                   [(name, name) for name in model_names])
        self.ollama_model.selectValue(cfg.ollama.default_model or "")
        ollama_form.addRow("默认模型", self.ollama_model)
        root.addWidget(ollama_box)

        external_box = QGroupBox("外部 OpenAI 兼容 API（提示词生成）")
        external_form = QFormLayout(external_box)
        self.external_base = QLineEdit(cfg.external_llm.base_url)
        self.external_base.setPlaceholderText("https://api.openai.com/v1")
        external_form.addRow("Base URL", self.external_base)
        self.external_key = QLineEdit(cfg.external_llm.api_key)
        self.external_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.external_key.setPlaceholderText("sk-...（也可用 OPENAI_API_KEY）")
        external_form.addRow("API Key", self.external_key)
        self.external_model = QLineEdit(cfg.external_llm.model)
        self.external_model.setPlaceholderText("模型名，例如 gpt-4o")
        external_form.addRow("模型", self.external_model)
        external_hint = QLabel("只用于外部提示词生成，不调用 Ollama；Key 仅保存在本机 config.json。")
        external_hint.setWordWrap(True)
        external_form.addRow("", external_hint)
        root.addWidget(external_box)

        lora_box = QGroupBox("LoRA 数据源")
        lora_form = QFormLayout(lora_box)
        self.character_lora_dir = _path_row(
            lora_form, "角色 LoRA 目录", cfg.lora.character_dir, directory=True)
        self.style_lora_dir = _path_row(
            lora_form, "风格 LoRA 目录", cfg.lora.style_dir, directory=True)
        self.body_lora_dir = _path_row(
            lora_form, "身体 LoRA 目录", cfg.lora.body_dir, directory=True)
        lora_hint = QLabel("留空 = 扫描 ComfyUI 的 LoRA 列表并按文件名自动分类。"
                           "自定义目录需已加入 ComfyUI 的 LoRA 搜索路径（extra_model_paths）。")
        lora_hint.setWordWrap(True)
        lora_form.addRow("", lora_hint)
        self.online_lookup = QCheckBox("无内置元数据时联网查询 Civitai 作者触发词")
        self.online_lookup.setChecked(cfg.lora.online_lookup)
        lora_form.addRow("", self.online_lookup)
        self.civitai_base = QLineEdit(cfg.lora.civitai_base)
        self.civitai_base.setPlaceholderText("https://civitai.red")
        lora_form.addRow("Civitai 地址", self.civitai_base)
        root.addWidget(lora_box)

        models_box = QGroupBox("模型目录（浏览选择）")
        models_form = QFormLayout(models_box)
        self.checkpoint_dir = _path_row(
            models_form, "Checkpoint 目录", cfg.models.checkpoint_dir, directory=True)
        self.upscaler_dir = _path_row(
            models_form, "放大模型目录", cfg.models.upscaler_dir, directory=True)
        models_hint = QLabel(
            "选择模型文件所在目录，保存后会扫描并加入下拉列表。"
            "Ollama、采样器、调度器由服务自动读取，也可在下拉框直接输入。")
        models_hint.setWordWrap(True)
        models_form.addRow("", models_hint)
        root.addWidget(models_box)

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
        c.external_llm.base_url = self.external_base.text().strip()
        c.external_llm.api_key = self.external_key.text().strip()
        c.external_llm.model = self.external_model.text().strip()
        c.lora.character_dir = self.character_lora_dir.text().strip()
        c.lora.style_dir = self.style_lora_dir.text().strip()
        c.lora.body_dir = self.body_lora_dir.text().strip()
        c.lora.online_lookup = self.online_lookup.isChecked()
        c.lora.civitai_base = self.civitai_base.text().strip() or "https://civitai.red"
        c.models.checkpoint_dir = self.checkpoint_dir.text().strip()
        c.models.upscaler_dir = self.upscaler_dir.text().strip()
        c.generation.template = self.template.text().strip()
        c.ui.language = self.language.currentValue()
        save_config(c)
        self.accept()
