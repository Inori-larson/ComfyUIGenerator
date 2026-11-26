"""Settings dialog (paths, ports, runtime options)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QLabel, QPlainTextEdit,
    QGroupBox, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from comfyui_generator.ui.widgets import SearchComboBox

from comfyui_generator.core.external_llm import EXTERNAL_LLM_MODEL
from comfyui_generator.core.opencode_config import endpoint_for_model, model_choices

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
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
        form.addWidget(comfy_box)

        llama_box = QGroupBox("本地模型 · llama.cpp llama-server")
        llama_form = QFormLayout(llama_box)
        self.ollama_host = QLineEdit(cfg.ollama.host)
        llama_form.addRow("地址", self.ollama_host)
        self.ollama_port = QSpinBox()
        self.ollama_port.setRange(1, 65535)
        self.ollama_port.setValue(cfg.ollama.port)
        llama_form.addRow("端口", self.ollama_port)
        self.ollama_exe = _path_row(llama_form, "llama-server.exe", cfg.ollama.exe)
        self.ollama_model = SearchComboBox(
            placeholder="模型标识（可搜索或直接输入）", allow_free_text=True)
        model_names = list(dict.fromkeys(self.models + ([cfg.ollama.default_model]
                                                       if cfg.ollama.default_model else [])))
        self.ollama_model.setItems([("自动（第一个可用）", "")] +
                                   [(name, name) for name in model_names])
        self.ollama_model.selectValue(cfg.ollama.default_model or "")
        llama_form.addRow("默认模型标识", self.ollama_model)
        self.llama_profile = QComboBox()
        profile_names = []
        for item in getattr(cfg.ollama, "profiles", []) or []:
            if isinstance(item, dict) and item.get("name"):
                profile_names.append(str(item["name"]))
        if not profile_names:
            profile_names = ["default"]
        self.llama_profile.addItems(profile_names)
        self.llama_profile.setCurrentText(
            getattr(cfg.ollama, "profile", "") or profile_names[0])
        self.llama_profile.currentTextChanged.connect(self._on_llama_profile_changed)
        llama_form.addRow("模型配置（选择即加载该模型）", self.llama_profile)
        self.llama_model_path = _path_row(llama_form, "GGUF 模型", "")
        self.llama_mmproj_path = _path_row(llama_form, "mmproj（可选）", "")
        self._load_llama_profile_fields(cfg)
        self.llama_reasoning = QComboBox()
        self.llama_reasoning.addItems(["minimal", "low", "medium", "high", "xhigh", "max"])
        self.llama_reasoning.setCurrentText(
            getattr(cfg.ollama, "reasoning_effort", "low") or "low")
        llama_form.addRow("思考强度", self.llama_reasoning)
        self.llama_gpu_layers = QSpinBox()
        self.llama_gpu_layers.setRange(0, 999)
        self.llama_gpu_layers.setValue(int(getattr(cfg.ollama, "gpu_layers", 32)))
        llama_form.addRow("GPU 层数（显存放不下时调小）", self.llama_gpu_layers)
        self.llama_auto_start = QCheckBox("未运行时自动启动本地服务")
        self.llama_auto_start.setChecked(bool(getattr(cfg.ollama, "auto_start", False)))
        llama_form.addRow("", self.llama_auto_start)
        form.addWidget(llama_box)

        external_box = QGroupBox("外部 OpenAI 兼容 API（提示词生成）")
        external_form = QFormLayout(external_box)
        current_model = cfg.external_llm.model or EXTERNAL_LLM_MODEL
        choices = model_choices()
        has_catalog = bool(choices)
        if not choices:
            choices = [(current_model, current_model)]
        if all(value != current_model for _label, value in choices):
            choices.insert(0, (current_model, current_model))
        self.external_base = QLineEdit(cfg.external_llm.base_url)
        self.external_base.setPlaceholderText("https://api.openai.com/v1")
        self.external_base.setReadOnly(True)
        external_form.addRow("Base URL", self.external_base)
        self.external_key = QLineEdit(cfg.external_llm.api_key)
        self.external_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.external_key.setReadOnly(True)
        external_form.addRow("API Key", self.external_key)
        self.external_model = SearchComboBox(
            placeholder="选择 opencode 中配置的模型",
            allow_free_text=not has_catalog)
        self.external_model.setItems(choices)
        self.external_model.selectValue(current_model)
        self.external_model.currentIndexChanged.connect(
            self._sync_external_endpoint)
        external_form.addRow("模型", self.external_model)
        self._sync_external_endpoint()
        self.external_no_thinking = QCheckBox("关闭模型推理输出（DeepSeek/豆包结构化 JSON）")
        self.external_no_thinking.setChecked(bool(
            getattr(cfg.external_llm, "disable_thinking", True)))
        external_form.addRow("", self.external_no_thinking)
        if has_catalog:
            external_hint = QLabel(
                "模型列表读取自 opencode 配置（%s 个模型），选择后自动套用对应网关地址和 Key；"
                "Key 仅保存在本机 config.json。" % len(choices))
        else:
            external_hint = QLabel(
                "未找到 opencode 配置（~/.config/opencode/opencode.json），"
                "当前只能使用已保存的模型；请先配置 opencode。")
        external_hint.setWordWrap(True)
        external_form.addRow("", external_hint)
        form.addWidget(external_box)

        lora_box = QGroupBox("LoRA 数据源")
        lora_form = QFormLayout(lora_box)
        self.character_lora_dir = _path_row(
            lora_form, "角色 LoRA 目录", cfg.lora.character_dir, directory=True)
        self.style_lora_dir = _path_row(
            lora_form, "风格 LoRA 目录", cfg.lora.style_dir, directory=True)
        self.body_lora_dir = _path_row(
            lora_form, "身体 LoRA 目录", cfg.lora.body_dir, directory=True)
        self.action_lora_dir = _path_row(
            lora_form, "动作 LoRA 目录", cfg.lora.action_dir, directory=True)
        self.clothing_lora_dir = _path_row(
            lora_form, "服装 LoRA 目录", cfg.lora.clothing_dir, directory=True)
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
        form.addWidget(lora_box)

        models_box = QGroupBox("模型目录（浏览选择）")
        models_form = QFormLayout(models_box)
        self.checkpoint_dir = _path_row(
            models_form, "Checkpoint 目录", cfg.models.checkpoint_dir, directory=True)
        self.upscaler_dir = _path_row(
            models_form, "放大模型目录", cfg.models.upscaler_dir, directory=True)
        models_hint = QLabel(
            "选择模型文件所在目录，保存后会扫描并加入下拉列表。"
            "采样器、调度器由服务自动读取，也可在下拉框直接输入。")
        models_hint.setWordWrap(True)
        models_form.addRow("", models_hint)
        form.addWidget(models_box)

        tagdb_box = QGroupBox("标签库 / 提示词校验")
        tagdb_form = QFormLayout(tagdb_box)
        self.tagdb_enabled = QCheckBox("生成后校验 cast 与服装层级")
        self.tagdb_enabled.setChecked(cfg.tagdb.enabled)
        tagdb_form.addRow(self.tagdb_enabled)
        self.tagdb_auto_repair = QCheckBox(
            "发现 P1 自动用当前模型最小修复，修好才标记就绪")
        self.tagdb_auto_repair.setChecked(cfg.tagdb.auto_repair_story)
        tagdb_form.addRow(self.tagdb_auto_repair)
        self.tagdb_auto_repair_advisory = QCheckBox(
            "结构类 P2 提示也批量交给 AI 修复（一次调用，不阻断）")
        self.tagdb_auto_repair_advisory.setChecked(cfg.tagdb.auto_repair_advisory)
        tagdb_form.addRow(self.tagdb_auto_repair_advisory)
        self.tagdb_csv = _path_row(tagdb_form, "danbooru.csv（可选）", cfg.tagdb.csv_path)
        self.tagdb_alias = _path_row(tagdb_form, "tag_aliases.csv（可选）", cfg.tagdb.alias_path)
        self.tagdb_report_unknown = QCheckBox("报告词表之外的自造/触发词标签")
        self.tagdb_report_unknown.setChecked(cfg.tagdb.report_unknown)
        tagdb_form.addRow(self.tagdb_report_unknown)
        self.tagdb_report_aliases = QCheckBox("报告别名标签并建议规范写法")
        self.tagdb_report_aliases.setChecked(cfg.tagdb.report_aliases)
        tagdb_form.addRow(self.tagdb_report_aliases)
        self.tagdb_auto_canonical = QCheckBox("自动把别名替换为规范标签（默认关闭，建议保持关闭）")
        self.tagdb_auto_canonical.setChecked(cfg.tagdb.auto_canonical_alias)
        tagdb_form.addRow(self.tagdb_auto_canonical)
        tagdb_hint = QLabel(
            "不配置 danbooru.csv 时，服装层级与 cast 校验仍可用（随包内置词表）。"
            "配置后额外做未知标签与别名检测。校验只产生 finding，不会替你改写剧情。")
        tagdb_hint.setWordWrap(True)
        tagdb_form.addRow("", tagdb_hint)
        form.addWidget(tagdb_box)

        tagger_box = QGroupBox("WD tagger 渲染后复核")
        tagger_form = QFormLayout(tagger_box)
        self.tagger_enabled = QCheckBox("启用 WD tagger（关闭则渲染后不做任何反推）")
        self.tagger_enabled.setChecked(cfg.tagger.enabled)
        tagger_form.addRow(self.tagger_enabled)
        self.tagger_auto_verify = QCheckBox("渲染完成后自动复核 cast 与服装层级（仅报告）")
        self.tagger_auto_verify.setChecked(cfg.tagger.auto_verify_after_render)
        tagger_form.addRow(self.tagger_auto_verify)
        self.tagger_auto_rewrite = QCheckBox(
            "渲染中发现 P1 硬伤自动重写并同 seed 重渲（每镜最多 N 次）")
        self.tagger_auto_rewrite.setChecked(cfg.tagger.auto_rewrite)
        tagger_form.addRow(self.tagger_auto_rewrite)
        self.tagger_max_rerender = QSpinBox()
        self.tagger_max_rerender.setRange(0, 5)
        self.tagger_max_rerender.setValue(int(cfg.tagger.max_rerender))
        tagger_form.addRow("每镜最多自动重渲次数", self.tagger_max_rerender)
        self.tagger_model = _path_row(
            tagger_form, "tagger ONNX 模型（可选，默认 models/tagger 自动发现）",
            cfg.tagger.model_path)
        self.tagger_device = QComboBox()
        self.tagger_device.addItems(["gpu", "cpu"])
        self.tagger_device.setCurrentText(cfg.tagger.device if cfg.tagger.device in ("gpu", "cpu") else "gpu")
        tagger_form.addRow("推理设备（GPU 不可用时自动降级）", self.tagger_device)
        self.tagger_cast = QDoubleSpinBox()
        self.tagger_cast.setRange(0.05, 0.99)
        self.tagger_cast.setSingleStep(0.05)
        self.tagger_cast.setValue(float(cfg.tagger.cast_threshold))
        tagger_form.addRow("人数判定阈值", self.tagger_cast)
        self.tagger_layer = QDoubleSpinBox()
        self.tagger_layer.setRange(0.05, 0.99)
        self.tagger_layer.setSingleStep(0.05)
        self.tagger_layer.setValue(float(cfg.tagger.layer_threshold))
        tagger_form.addRow("服装层级阈值", self.tagger_layer)
        tagger_hint = QLabel(
            "首次使用会把 onnxruntime/numpy/pillow 安装到应用数据目录 tagger_packages，"
            "不改动 ComfyUI。模型 wd-eva02-large-tagger-v3（model.onnx + selected_tags.csv）"
            "需放到 ComfyUI models/tagger 目录。")
        tagger_hint.setWordWrap(True)
        tagger_form.addRow("", tagger_hint)
        form.addWidget(tagger_box)

        rag_box = QGroupBox("图站范例 RAG（few-shot）")
        rag_form = QFormLayout(rag_box)
        self.rag_enabled = QCheckBox("生成分镜时检索高分真实标签作范例（仅学搭配，不注入剧情）")
        self.rag_enabled.setChecked(cfg.rag.enabled)
        rag_form.addRow(self.rag_enabled)
        self.rag_queries = QPlainTextEdit(cfg.rag.queries)
        self.rag_queries.setMaximumHeight(110)
        self.rag_queries.setPlaceholderText("每行一个检索词；留空则不检索。不再从剧情关键词自动猜测。")
        rag_form.addRow("检索词", self.rag_queries)
        self.rag_source = QComboBox()
        self.rag_source.addItem("yande.re（推荐，可匿名直连）", "yande")
        self.rag_source.addItem("Danbooru（词表大，国内常需代理）", "danbooru")
        self.rag_source.setCurrentIndex(0 if cfg.rag.source != "danbooru" else 1)
        rag_form.addRow("范例源", self.rag_source)
        self.rag_proxy = QLineEdit(cfg.rag.proxy)
        self.rag_proxy.setPlaceholderText("http://127.0.0.1:10809（仅 Danbooru 需要，留空直连）")
        rag_form.addRow("HTTP 代理", self.rag_proxy)
        self.rag_login = QLineEdit(cfg.rag.login)
        rag_form.addRow("Danbooru 用户名（可空）", self.rag_login)
        self.rag_api_key = QLineEdit(cfg.rag.api_key)
        self.rag_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        rag_form.addRow("Danbooru API Key（可空，仅存本机）", self.rag_api_key)
        self.rag_max = QSpinBox()
        self.rag_max.setRange(1, 12)
        self.rag_max.setValue(int(cfg.rag.max_examples))
        rag_form.addRow("每批最多范例数", self.rag_max)
        self.rag_min_score = QSpinBox()
        self.rag_min_score.setRange(0, 1000)
        self.rag_min_score.setValue(int(cfg.rag.min_score))
        rag_form.addRow("最低 score", self.rag_min_score)
        rag_hint = QLabel(
            "凭据只写入本机 %APPDATA%\\ComfyUIGenerator\\config.json，不进代码/不提交。"
            "网络或鉴权失败会静默跳过，不影响生成。")
        rag_hint.setWordWrap(True)
        rag_form.addRow("", rag_hint)
        form.addWidget(rag_box)

        policy_box = QGroupBox("用户创作规则（原样交给 AI 理解，可自由编辑）")
        policy_form = QFormLayout(policy_box)
        self.story_policy = QPlainTextEdit(cfg.story_policy)
        self.story_policy.setMinimumHeight(180)
        self.story_policy.setPlaceholderText(
            "每行一条你想要遵守的规则；代码不会解释这些内容，只原样传给 AI。")
        policy_form.addRow(self.story_policy)
        form.addWidget(policy_box)

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
        form.addWidget(app_box)
        form.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _profile_values(self, name: str) -> dict[str, Any]:
        for item in getattr(self.cfg.ollama, "profiles", []) or []:
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return {}

    def _on_llama_profile_changed(self, name: str) -> None:
        values = self._profile_values(name)
        if not values:
            values = {
                "model": self.cfg.ollama.model,
                "mmproj": self.cfg.ollama.mmproj,
                "gpu_layers": self.cfg.ollama.gpu_layers,
                "context": self.cfg.ollama.context,
                "reasoning_effort": self.cfg.ollama.reasoning_effort,
                "reasoning_budget": self.cfg.ollama.reasoning_budget,
                "temperature": self.cfg.ollama.temperature,
                "top_p": self.cfg.ollama.top_p,
                "top_k": self.cfg.ollama.top_k,
            }
        self._apply_profile_values(values)

    def _apply_profile_values(self, values: dict[str, Any]) -> None:
        self.llama_model_path.setText(str(values.get("model") or ""))
        self.llama_mmproj_path.setText(str(values.get("mmproj") or ""))
        if hasattr(self, "llama_gpu_layers"):
            self.llama_gpu_layers.setValue(int(values.get("gpu_layers") or 0))
        if hasattr(self, "llama_context"):
            self.llama_context.setValue(int(values.get("context") or 16384))
        if hasattr(self, "llama_reasoning"):
            effort = str(values.get("reasoning_effort") or "low")
            if self.llama_reasoning.findText(effort) >= 0:
                self.llama_reasoning.setCurrentText(effort)
        if hasattr(self, "llama_budget"):
            self.llama_budget.setValue(int(values.get("reasoning_budget") or 1024))

    def _load_llama_profile_fields(self, cfg: AppConfig) -> None:
        values = self._profile_values(self.llama_profile.currentText())
        if not values:
            values = {
                "model": cfg.ollama.model, "mmproj": cfg.ollama.mmproj,
                "gpu_layers": cfg.ollama.gpu_layers, "context": cfg.ollama.context,
                "reasoning_effort": cfg.ollama.reasoning_effort,
                "reasoning_budget": cfg.ollama.reasoning_budget,
            }
        self._apply_profile_values(values)

    def _sync_external_endpoint(self) -> None:
        model = str(self.external_model.currentValue() or "").strip()
        endpoint = endpoint_for_model(model) if model else {}
        if endpoint.get("base_url"):
            self.external_base.setText(endpoint["base_url"])
        if endpoint.get("api_key"):
            self.external_key.setText(endpoint["api_key"])

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
        c.ollama.auto_start = self.llama_auto_start.isChecked()
        profile_name = self.llama_profile.currentText() or "default"
        c.ollama.profile = profile_name
        values = dict(self._profile_values(profile_name))
        values.update({
            "name": profile_name,
            "model": self.llama_model_path.text().strip(),
            "mmproj": self.llama_mmproj_path.text().strip(),
            "gpu_layers": self.llama_gpu_layers.value(),
            "reasoning_effort": self.llama_reasoning.currentText(),
        })
        profiles = [
            item for item in (getattr(c.ollama, "profiles", []) or [])
            if isinstance(item, dict) and item.get("name") != profile_name
        ]
        profiles.append(values)
        c.ollama.profiles = profiles
        c.ollama.model = values["model"]
        c.ollama.mmproj = values["mmproj"]
        c.ollama.gpu_layers = values["gpu_layers"]
        c.ollama.reasoning_effort = values["reasoning_effort"]
        c.external_llm.model = str(
            self.external_model.currentValue() or "").strip() or EXTERNAL_LLM_MODEL
        endpoint = endpoint_for_model(c.external_llm.model)
        c.external_llm.base_url = (
            endpoint.get("base_url") or self.external_base.text().strip())
        c.external_llm.api_key = (
            endpoint.get("api_key") or self.external_key.text().strip())
        c.external_llm.disable_thinking = self.external_no_thinking.isChecked()
        c.lora.character_dir = self.character_lora_dir.text().strip()
        c.lora.style_dir = self.style_lora_dir.text().strip()
        c.lora.body_dir = self.body_lora_dir.text().strip()
        c.lora.action_dir = self.action_lora_dir.text().strip()
        c.lora.clothing_dir = self.clothing_lora_dir.text().strip()
        c.lora.online_lookup = self.online_lookup.isChecked()
        c.lora.civitai_base = self.civitai_base.text().strip() or "https://civitai.red"
        c.models.checkpoint_dir = self.checkpoint_dir.text().strip()
        c.models.upscaler_dir = self.upscaler_dir.text().strip()
        c.story_policy = self.story_policy.toPlainText()
        c.tagdb.enabled = self.tagdb_enabled.isChecked()
        c.tagdb.auto_repair_story = self.tagdb_auto_repair.isChecked()
        c.tagdb.auto_repair_advisory = self.tagdb_auto_repair_advisory.isChecked()
        c.tagdb.csv_path = self.tagdb_csv.text().strip()
        c.tagdb.alias_path = self.tagdb_alias.text().strip()
        c.tagdb.report_unknown = self.tagdb_report_unknown.isChecked()
        c.tagdb.report_aliases = self.tagdb_report_aliases.isChecked()
        c.tagdb.auto_canonical_alias = self.tagdb_auto_canonical.isChecked()
        c.tagger.auto_verify_after_render = self.tagger_auto_verify.isChecked()
        c.tagger.enabled = self.tagger_enabled.isChecked()
        c.tagger.auto_rewrite = self.tagger_auto_rewrite.isChecked()
        c.tagger.max_rerender = int(self.tagger_max_rerender.value())
        c.tagger.model_path = self.tagger_model.text().strip()
        c.tagger.device = self.tagger_device.currentText()
        c.tagger.cast_threshold = float(self.tagger_cast.value())
        c.tagger.layer_threshold = float(self.tagger_layer.value())
        c.rag.enabled = self.rag_enabled.isChecked()
        c.rag.queries = self.rag_queries.toPlainText()
        c.rag.source = str(self.rag_source.currentData() or "yande")
        c.rag.proxy = self.rag_proxy.text().strip()
        c.rag.login = self.rag_login.text().strip()
        c.rag.api_key = self.rag_api_key.text().strip()
        c.rag.max_examples = int(self.rag_max.value())
        c.rag.min_score = int(self.rag_min_score.value())
        c.generation.template = self.template.text().strip()
        c.ui.language = self.language.currentValue()
        save_config(c)
        self.accept()
