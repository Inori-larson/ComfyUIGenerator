"""Main window for the ComfyUI Generator desktop app (M1)."""

from __future__ import annotations

import copy
import json
import os
import random
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from comfyui_generator.core.assets import Assets
from comfyui_generator.core.comfy import ComfyClient
from comfyui_generator.core.config import (
    AppConfig, load_config, load_template, resolve_template, save_config,
)
from comfyui_generator.core.detailers import build_detailer_choices
from comfyui_generator.core.jobs import build_tasks
from comfyui_generator.core.moods import MOODS, resolve_mood
from comfyui_generator.core.project import new_project, save_project
from comfyui_generator.core.services import ComfyService
from comfyui_generator.core.single import FRAMING_TAGS, SingleOptions
from comfyui_generator.core.storyboard import StoryboardOptions, slugify
from comfyui_generator.core.tags import append_tags
from comfyui_generator.ui.settings_dialog import SettingsDialog
from comfyui_generator.ui.widgets import SearchComboBox
from comfyui_generator.ui.workers import ConnectWorker, PromptWorker, RenderWorker

RESOLUTIONS = [
    ("竖屏 832x1216", 832, 1216),
    ("竖屏 1024x1344", 1024, 1344),
    ("竖屏 1024x1536", 1024, 1536),
    ("横屏 1216x832", 1216, 832),
    ("方形 1024x1024", 1024, 1024),
]
SAMPLERS = ["euler_ancestral", "euler", "dpmpp_2m", "dpmpp_2m_sde",
            "dpmpp_sde", "dpmpp_3m_sde", "ddim", "uni_pc", "heun", "lms"]
SCHEDULERS = ["normal", "karras", "exponential", "sgm_uniform", "simple", "beta", "ddim_uniform"]
FRAMING_LABELS = [
    ("自动（由模型决定）", "auto"),
    ("全身", "full_body"),
    ("半身", "upper_body"),
    ("特写", "close_up"),
    ("头像", "portrait"),
    ("广角", "wide"),
]


def _label(text: str, name: str = "Section") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Generator")
        self.resize(1480, 940)
        self.cfg: AppConfig = load_config()
        self.cfg.ensure_dirs()
        self.template_path = resolve_template(self.cfg)
        self.template = load_template(self.cfg)
        self.comfy_service = ComfyService(self.cfg)
        self.assets = Assets()
        self.ollama_models: list[str] = []
        self.connected = False

        self.connect_worker: ConnectWorker | None = None
        self.prompt_worker: PromptWorker | None = None
        self.render_worker: RenderWorker | None = None
        self.tasks_by_id: dict[str, Any] = {}
        self.task_rows: dict[str, int] = {}
        self.row_task_ids: dict[int, str] = {}
        self.previews: dict[str, bytes] = {}
        self.final_bytes: dict[str, bytes] = {}
        self._icon_last: dict[str, float] = {}
        self.current_pixmap: QPixmap | None = None
        self.current_task_id: str | None = None
        self.project: dict[str, Any] | None = None
        self.detailer_rows: list[tuple[str, QCheckBox, QDoubleSpinBox, dict[str, Any]]] = []
        self._render_after_prompt = False

        self._build_ui()
        self._init_defaults()
        if os.environ.get("CUI_NO_AUTOCONNECT") != "1":
            QTimer.singleShot(300, self.connect_services)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        vsplit = QSplitter(Qt.Orientation.Vertical)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_center())
        split.addWidget(self._build_right())
        split.setStretchFactor(1, 1)
        split.setSizes([360, 760, 400])
        vsplit.addWidget(split)
        vsplit.addWidget(self._build_bottom())
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([700, 230])
        root.addWidget(vsplit, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        row.addWidget(_label("ComfyUI Generator", "Title"))

        self.btn_mode_single = QPushButton("单图")
        self.btn_mode_story = QPushButton("连续剧情")
        for btn in (self.btn_mode_single, self.btn_mode_story):
            btn.setCheckable(True)
            btn.setObjectName("Mode")
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.btn_mode_single)
        group.addButton(self.btn_mode_story)
        self.btn_mode_single.setChecked(True)
        self.btn_mode_single.clicked.connect(lambda: self._switch_mode(0))
        self.btn_mode_story.clicked.connect(lambda: self._switch_mode(1))
        row.addSpacing(12)
        row.addWidget(self.btn_mode_single)
        row.addWidget(self.btn_mode_story)

        row.addSpacing(18)
        self.comfy_status = QLabel()
        self.comfy_status.setTextFormat(Qt.TextFormat.RichText)
        self.ollama_status = QLabel()
        self.ollama_status.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.comfy_status)
        row.addWidget(self.ollama_status)
        self._set_status("comfy", "连接中", "#e67e22")
        self._set_status("ollama", "等待连接", "#95a5a6")
        row.addStretch(1)

        self.btn_reconnect = QPushButton("重新连接")
        self.btn_reconnect.clicked.connect(lambda: self.connect_services(False))
        self.btn_restart = QPushButton("重启 ComfyUI")
        self.btn_restart.clicked.connect(self.restart_comfy)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_output = QPushButton("输出目录")
        self.btn_output.clicked.connect(self.open_output_dir)
        for btn in (self.btn_reconnect, self.btn_restart, self.btn_settings, self.btn_output):
            row.addWidget(btn)
        return bar

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 6, 10)
        layout.setSpacing(8)
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self._build_single_panel())
        self.left_stack.addWidget(self._build_story_panel())
        layout.addWidget(self.left_stack, 1)
        panel.setMinimumWidth(330)
        panel.setMaximumWidth(460)
        return panel

    def _build_single_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(_label("描述（自然语言）"))
        self.single_desc = QPlainTextEdit()
        self.single_desc.setPlaceholderText("例：晴天，仪玄在公园长椅上吃冰淇淋，微笑看镜头")
        self.single_desc.setFixedHeight(90)
        layout.addWidget(self.single_desc)

        row = QHBoxLayout()
        row.addWidget(_label("构图", "Hint"))
        self.framing = SearchComboBox()
        for text, value in FRAMING_LABELS:
            self.framing.addItem(text, value)
        row.addWidget(self.framing, 1)
        layout.addLayout(row)

        self.btn_single_prompt = QPushButton("① 生成提示词")
        self.btn_single_prompt.clicked.connect(lambda: self.generate_single(False))
        layout.addWidget(self.btn_single_prompt)

        layout.addWidget(_label("提示词（可手动修改）"))
        self.single_prompt = QPlainTextEdit()
        self.single_prompt.setPlaceholderText("模型生成后可编辑，再点击生成图片")
        layout.addWidget(self.single_prompt, 1)

        self.btn_single_render = QPushButton("② 生成图片")
        self.btn_single_render.setObjectName("Primary")
        self.btn_single_render.clicked.connect(self.render_single_clicked)
        layout.addWidget(self.btn_single_render)

        self.btn_expand = QPushButton("扩写成分镜…")
        self.btn_expand.setEnabled(False)
        self.btn_expand.clicked.connect(self.expand_single)
        layout.addWidget(self.btn_expand)
        return page

    def _build_story_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(_label("剧情（自然语言）"))
        self.story_premise = QPlainTextEdit()
        self.story_premise.setPlaceholderText("例：晴天，少女和猫在天台晒太阳")
        self.story_premise.setFixedHeight(80)
        layout.addWidget(self.story_premise)

        row = QHBoxLayout()
        row.addWidget(_label("分镜数", "Hint"))
        self.story_shots = QSpinBox()
        self.story_shots.setRange(1, 200)
        self.story_shots.setValue(6)
        row.addWidget(self.story_shots)
        self.btn_story_prompt = QPushButton("生成分镜")
        self.btn_story_prompt.clicked.connect(lambda: self.generate_story())
        row.addWidget(self.btn_story_prompt, 1)
        layout.addLayout(row)

        self.shot_table = QTableWidget(0, 3)
        self.shot_table.setHorizontalHeaderLabels(["镜号", "名称", "画面提示词（可编辑）"])
        self.shot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.shot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.shot_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                        | QAbstractItemView.EditTrigger.EditKeyPressed)
        layout.addWidget(self.shot_table, 1)

        tools = QHBoxLayout()
        for text, slot in (("+ 添加", self.add_shot_row), ("− 删除", self.remove_shot_row),
                           ("↑", lambda: self.move_shot(-1)), ("↓", lambda: self.move_shot(1))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        layout.addLayout(tools)

        self.chk_selected = QCheckBox("只生成选中的镜头")
        layout.addWidget(self.chk_selected)
        self.btn_story_render = QPushButton("生成全部图片")
        self.btn_story_render.setObjectName("Primary")
        self.btn_story_render.clicked.connect(lambda: self.start_render("story"))
        layout.addWidget(self.btn_story_render)
        return page

    def _build_center(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 10, 6, 10)
        info = QHBoxLayout()
        self.preview_info = _label("等待生成", "Hint")
        info.addWidget(self.preview_info, 1)
        self.chk_follow = QCheckBox("自动跟随")
        self.chk_follow.setChecked(True)
        info.addWidget(self.chk_follow)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_render)
        info.addWidget(self.btn_cancel)
        layout.addLayout(info)

        self.preview_label = QLabel("生成时在这里显示实时预览")
        self.preview_label.setObjectName("Preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(420, 380)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.preview_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        return panel

    def _build_right(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 10, 10, 10)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_models_tab(), "模型")
        self.tabs.addTab(self._build_character_tab(), "角色")
        self.tabs.addTab(self._build_picture_tab(), "画面")
        self.tabs.addTab(self._build_hires_tab(), "高清")
        self.tabs.addTab(self._build_detailer_tab(), "重绘")
        self.tabs.addTab(self._build_prompt_tab(), "提示词")
        self.tabs.addTab(self._build_style_ref_tab(), "参考图")
        layout.addWidget(self.tabs)
        layout.addStretch(1)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(500)
        return scroll

    def _build_models_tab(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setSpacing(8)
        form.addWidget(_label("Ollama 模型（可替换）"))
        self.llm_combo = SearchComboBox()
        form.addWidget(self.llm_combo)
        form.addWidget(_label("底模（Checkpoint）"))
        self.ckpt_combo = SearchComboBox()
        form.addWidget(self.ckpt_combo)
        row = QHBoxLayout()
        row.addWidget(_label("CLIP skip", "Hint"))
        self.clip_skip = QSpinBox()
        self.clip_skip.setRange(-12, -1)
        self.clip_skip.setValue(-2)
        row.addWidget(self.clip_skip)
        row.addStretch(1)
        form.addLayout(row)
        self.template_label = _label("模板：—", "Hint")
        self.template_label.setWordWrap(True)
        form.addWidget(self.template_label)
        form.addStretch(1)
        return page

    def _build_character_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("LoRA（可多选）"))
        self.lora_table = QTableWidget(0, 2)
        self.lora_table.setHorizontalHeaderLabels(["名称", "强度"])
        self.lora_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lora_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.lora_table.verticalHeader().setVisible(False)
        self.lora_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.lora_table, 1)
        layout.addWidget(_label("角色标签（Danbooru）"))
        self.tags_edit = QPlainTextEdit()
        self.tags_edit.setFixedHeight(100)
        layout.addWidget(self.tags_edit)
        layout.addWidget(_label("角色参考图（IPAdapter，可选）"))
        row = QHBoxLayout()
        self.char_ref = QLineEdit()
        self.char_ref.setPlaceholderText("本地图片路径")
        row.addWidget(self.char_ref, 1)
        btn = QPushButton("浏览")
        btn.clicked.connect(self.pick_char_ref)
        row.addWidget(btn)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(_label("参考强度", "Hint"))
        self.char_ref_weight = QDoubleSpinBox()
        self.char_ref_weight.setRange(0, 2)
        self.char_ref_weight.setSingleStep(0.05)
        self.char_ref_weight.setValue(0.6)
        row2.addWidget(self.char_ref_weight)
        row2.addStretch(1)
        layout.addLayout(row2)
        layout.addStretch(1)
        return page

    def _build_picture_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("画面氛围"))
        self.mood_combo = SearchComboBox()
        for key, (label, _pos, _neg) in MOODS.items():
            self.mood_combo.addItem(label, key)
        layout.addWidget(self.mood_combo)

        layout.addWidget(_label("分辨率"))
        self.res_combo = SearchComboBox()
        for label, w, h in RESOLUTIONS:
            self.res_combo.addItem(label, (w, h))
        self.res_combo.addItem("自定义", None)
        self.res_combo.currentIndexChanged.connect(self._apply_resolution)
        layout.addWidget(self.res_combo)
        row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(256, 4096)
        self.width_spin.setSingleStep(64)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(256, 4096)
        self.height_spin.setSingleStep(64)
        row.addWidget(self.width_spin)
        row.addWidget(QLabel("×"))
        row.addWidget(self.height_spin)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_label("步数", "Hint"))
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 150)
        row.addWidget(self.steps_spin)
        row.addWidget(_label("CFG", "Hint"))
        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(0.5, 20)
        self.cfg_spin.setSingleStep(0.5)
        row.addWidget(self.cfg_spin)
        layout.addLayout(row)

        layout.addWidget(_label("采样器"))
        self.sampler_combo = SearchComboBox()
        layout.addWidget(self.sampler_combo)
        layout.addWidget(_label("调度器"))
        self.scheduler_combo = SearchComboBox()
        layout.addWidget(self.scheduler_combo)

        row = QHBoxLayout()
        row.addWidget(_label("种子模式", "Hint"))
        self.seed_mode = SearchComboBox()
        self.seed_mode.addItem("递增", "increment")
        self.seed_mode.addItem("固定", "fixed")
        self.seed_mode.addItem("随机", "random")
        row.addWidget(self.seed_mode, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2 ** 31 - 1)
        row.addWidget(self.seed_spin, 1)
        btn = QPushButton("随机")
        btn.clicked.connect(lambda: self.seed_spin.setValue(random.randint(1, 2 ** 31 - 1)))
        row.addWidget(btn)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_label("每个分镜张数", "Hint"))
        self.variants_spin = QSpinBox()
        self.variants_spin.setRange(1, 8)
        row.addWidget(self.variants_spin)
        layout.addLayout(row)
        layout.addWidget(_label("输出名称（可空，自动生成）"))
        self.output_name = QLineEdit()
        layout.addWidget(self.output_name)
        layout.addStretch(1)
        return page

    def _build_hires_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        self.hires_check = QCheckBox("启用高清修复（hires fix）")
        self.hires_check.setChecked(True)
        layout.addWidget(self.hires_check)
        row = QHBoxLayout()
        row.addWidget(_label("放大倍率", "Hint"))
        self.hires_scale = QDoubleSpinBox()
        self.hires_scale.setRange(1.0, 3.0)
        self.hires_scale.setSingleStep(0.1)
        row.addWidget(self.hires_scale)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("重绘幅度", "Hint"))
        self.hires_denoise = QDoubleSpinBox()
        self.hires_denoise.setRange(0, 1)
        self.hires_denoise.setSingleStep(0.05)
        row.addWidget(self.hires_denoise)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("高清步数", "Hint"))
        self.hires_steps = QSpinBox()
        self.hires_steps.setRange(1, 80)
        row.addWidget(self.hires_steps)
        layout.addLayout(row)
        layout.addWidget(_label("放大模型"))
        self.upscaler_combo = SearchComboBox()
        layout.addWidget(self.upscaler_combo)
        layout.addStretch(1)
        return page

    def _build_detailer_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("勾选需要重绘的部位；denoise 越高改动越大"))
        self.detailer_box = QVBoxLayout()
        self.detailer_box.setSpacing(6)
        layout.addLayout(self.detailer_box)
        layout.addStretch(1)
        return page

    def _build_prompt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("追加正向提示词（可空）"))
        self.positive_extra = QPlainTextEdit()
        self.positive_extra.setFixedHeight(60)
        layout.addWidget(self.positive_extra)
        layout.addWidget(_label("追加负向提示词（可空）"))
        self.negative_extra = QPlainTextEdit()
        self.negative_extra.setFixedHeight(60)
        layout.addWidget(self.negative_extra)
        self.wildcard_check = QCheckBox("启用通配符 {a|b} 与 __file__")
        layout.addWidget(self.wildcard_check)
        row = QHBoxLayout()
        self.wildcard_dir = QLineEdit()
        self.wildcard_dir.setPlaceholderText("wildcards 目录")
        row.addWidget(self.wildcard_dir, 1)
        btn = QPushButton("浏览")
        btn.clicked.connect(self.pick_wildcard_dir)
        row.addWidget(btn)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_style_ref_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        self.style_ref_check = QCheckBox("启用画风参考图（style transfer）")
        layout.addWidget(self.style_ref_check)
        row = QHBoxLayout()
        self.style_ref_edit = QLineEdit()
        row.addWidget(self.style_ref_edit, 1)
        btn = QPushButton("浏览")
        btn.clicked.connect(self.pick_style_ref)
        row.addWidget(btn)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("画风强度", "Hint"))
        self.style_ref_weight = QDoubleSpinBox()
        self.style_ref_weight.setRange(0, 2)
        self.style_ref_weight.setSingleStep(0.05)
        self.style_ref_weight.setValue(0.8)
        row.addWidget(self.style_ref_weight)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_bottom(self) -> QWidget:
        self.bottom_tabs = QTabWidget()
        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["任务", "状态", "阶段", "进度", "Seed"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            self.queue_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setIconSize(QSize(36, 36))
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.currentCellChanged.connect(self._on_queue_selected)
        self.bottom_tabs.addTab(self.queue_table, "队列")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.bottom_tabs.addTab(self.log_view, "日志")

        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(150, 150))
        self.gallery.setGridSize(QSize(170, 185))
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setMovement(QListView.Movement.Static)
        self.gallery.setSpacing(6)
        self.gallery.itemDoubleClicked.connect(self._open_gallery_item)
        self.bottom_tabs.addTab(self.gallery, "画廊")
        return self.bottom_tabs

    # ---------------------------------------------------------------- defaults

    def _init_defaults(self) -> None:
        template = self.template
        settings = template.get("settings") or {}
        self.template_label.setText("模板：%s" % self.template_path.name)
        self.tags_edit.setPlainText((template.get("character") or {}).get("tags", ""))
        self.clip_skip.setValue(int(template.get("clip_skip", -2)))

        w = int(settings.get("width", 1024))
        h = int(settings.get("height", 1344))
        self.width_spin.setValue(w)
        self.height_spin.setValue(h)
        index = next((i for i, (_l, rw, rh) in enumerate(RESOLUTIONS) if (rw, rh) == (w, h)), None)
        self.res_combo.setCurrentIndex(index if index is not None else self.res_combo.count() - 1)

        self.steps_spin.setValue(int(settings.get("steps", 30)))
        self.cfg_spin.setValue(float(settings.get("cfg", 5.0)))
        self._fill_combo(self.sampler_combo, SAMPLERS, settings.get("sampler", "euler_ancestral"))
        self._fill_combo(self.scheduler_combo, SCHEDULERS, settings.get("scheduler", "normal"))
        mode = settings.get("seed_mode", "increment")
        self.seed_mode.setCurrentIndex(max(0, self.seed_mode.findData(mode)))
        self.seed_spin.setValue(int(settings.get("base_seed") or random.randint(1, 2 ** 31 - 1)))

        hires = settings.get("hires") or {}
        self.hires_check.setChecked(bool(hires.get("enabled", True)))
        self.hires_scale.setValue(float(hires.get("scale", 1.5)))
        self.hires_denoise.setValue(float(hires.get("denoise", 0.4)))
        self.hires_steps.setValue(int(hires.get("steps", 20)))
        self.variants_spin.setValue(int(template.get("variants") or 1))
        mood = self.cfg.generation.mood or "bright"
        self.mood_combo.setCurrentIndex(max(0, self.mood_combo.findData(mood)))
        wildcard_dir = (self.cfg.generation.wildcards or {}).get("dir", "")
        if not wildcard_dir and self.cfg.comfy.base_dir:
            wildcard_dir = str(Path(self.cfg.comfy.base_dir) / "user" / "default" / "wildcards")
        self.wildcard_dir.setText(wildcard_dir or str(self.cfg.root / "wildcards"))
        self._populate_loras()
        self._populate_detailers()

    def _fill_combo(self, combo: QComboBox, values: list[str], current: str) -> None:
        if isinstance(combo, SearchComboBox):
            combo.setValues(values, current)
            return
        combo.clear()
        combo.addItems(values)
        index = combo.findText(current)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _apply_resolution(self) -> None:
        value = self.res_combo.currentData()
        if value:
            self.width_spin.setValue(value[0])
            self.height_spin.setValue(value[1])

    # ---------------------------------------------------------------- connections

    def _set_status(self, which: str, text: str, color: str) -> None:
        label = self.comfy_status if which == "comfy" else self.ollama_status
        prefix = "ComfyUI" if which == "comfy" else "Ollama"
        label.setText('<span style="color:%s">●</span> %s：%s' % (color, prefix, text))

    def connect_services(self, restart: bool = False) -> None:
        if self.connect_worker and self.connect_worker.isRunning():
            return
        self._set_status("comfy", "连接中…", "#e67e22")
        self.btn_reconnect.setEnabled(False)
        self._set_busy(True)
        worker = ConnectWorker(self.cfg, self.comfy_service, restart)
        worker.connected.connect(self._on_connected)
        worker.failed.connect(self._on_connect_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(lambda: self.btn_reconnect.setEnabled(True))
        self.connect_worker = worker
        worker.start()

    def _on_connected(self, payload: dict[str, Any]) -> None:
        self.connected = True
        self.assets = payload["assets"]
        state = "托管" if payload["state"] == "started" else "已连接"
        version = payload.get("version") or "?"
        self._set_status("comfy", "%s（%s）" % (state, version), "#27ae60")
        if payload.get("ollama_ok"):
            self._set_status("ollama", "已连接（%d 个模型）" % len(payload.get("models") or []), "#27ae60")
        else:
            self._set_status("ollama", "未连接", "#e74c3c")
        self._populate_from_assets(payload.get("models") or [])
        self._set_busy(False)
        self.append_log("ComfyUI %s，%s" % (version, state))
        if self.assets.error:
            self.append_log("资源列表读取失败：%s" % self.assets.error)
        if self.assets.missing_nodes:
            self.append_log("缺少节点：%s（重绘/参考图可能不可用）" % ", ".join(self.assets.missing_nodes))

    def _on_connect_failed(self, message: str) -> None:
        self.connected = False
        self._set_status("comfy", "连接失败", "#e74c3c")
        self._set_busy(False)
        self.append_log("连接失败：%s" % message)
        self.statusBar().showMessage("ComfyUI 连接失败，请检查设置")
        QMessageBox.warning(self, "连接失败", message)

    def _populate_from_assets(self, models: list[str]) -> None:
        self.ollama_models = list(models)
        current_llm = self.llm_combo.currentValue() or self.cfg.ollama.default_model
        self.llm_combo.setValues(models)
        if current_llm:
            self.llm_combo.selectValue(current_llm)

        current_ckpt = self.ckpt_combo.currentValue() or (self.template.get("model") or "")
        checkpoints = [c for c in (self.assets.checkpoints or [self.template.get("model") or ""]) if c]
        self.ckpt_combo.setValues(checkpoints)
        if current_ckpt:
            self.ckpt_combo.selectValue(current_ckpt)

        self._fill_combo(self.sampler_combo, self.assets.samplers or SAMPLERS,
                         self.sampler_combo.currentValue() or "euler_ancestral")
        self._fill_combo(self.scheduler_combo, self.assets.schedulers or SCHEDULERS,
                         self.scheduler_combo.currentValue() or "normal")
        current_up = self.upscaler_combo.currentValue()
        self.upscaler_combo.setValues(self.assets.upscalers or [])
        if current_up:
            self.upscaler_combo.selectValue(current_up)
        self._populate_loras()
        self._populate_detailers()

    def _populate_loras(self) -> None:
        configured: dict[str, float] = {}
        for lora in (self.template.get("loras") or
                     ([self.template["lora"]] if self.template.get("lora") else [])):
            if lora.get("name"):
                configured[lora["name"]] = float(lora.get("strength", 0.9))
        names = list(self.assets.loras) if self.assets.loras else list(configured)
        current = {}
        for row in range(self.lora_table.rowCount()):
            item = self.lora_table.item(row, 0)
            spin = self.lora_table.cellWidget(row, 1)
            if item and spin:
                current[item.data(Qt.ItemDataRole.UserRole)] = (
                    item.checkState() == Qt.CheckState.Checked, spin.value())
        self.lora_table.setRowCount(0)
        for name in names:
            row = self.lora_table.rowCount()
            self.lora_table.insertRow(row)
            item = QTableWidgetItem(Path(name).name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checked, strength = current.get(name, (name in configured, configured.get(name, 0.9)))
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.lora_table.setItem(row, 0, item)
            spin = QDoubleSpinBox()
            spin.setRange(0, 2)
            spin.setSingleStep(0.05)
            spin.setValue(strength)
            self.lora_table.setCellWidget(row, 1, spin)

    def _populate_detailers(self) -> None:
        checked = {key for key, box, _spin, _choice in self.detailer_rows if box.isChecked()}
        values = {key: spin.value() for key, _box, spin, _choice in self.detailer_rows}
        while self.detailer_box.count():
            item = self.detailer_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.detailer_rows.clear()
        for choice in build_detailer_choices(self.assets.detectors):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(choice["label"])
            box.setToolTip(choice["detector"])
            box.setChecked(choice["key"] in checked)
            layout.addWidget(box, 1)
            layout.addWidget(QLabel("denoise"))
            spin = QDoubleSpinBox()
            spin.setRange(0.05, 0.9)
            spin.setSingleStep(0.05)
            spin.setValue(values.get(choice["key"], choice["denoise"]))
            layout.addWidget(spin)
            self.detailer_box.addWidget(row)
            self.detailer_rows.append((choice["key"], box, spin, choice))

    # ---------------------------------------------------------------- template / project

    def _mood_key(self) -> str:
        return self.mood_combo.currentData() or "bright"

    def _mood_text(self) -> str:
        return MOODS.get(self._mood_key(), MOODS["bright"])[1]

    def _style_positive(self) -> str:
        return (self.template.get("style") or {}).get("positive", "")

    def _character_tags(self) -> str:
        return self.tags_edit.toPlainText().strip()

    def _build_style(self) -> dict[str, Any]:
        style = copy.deepcopy(self.template.get("style") or {})
        position, negative = resolve_mood(self._mood_key())
        if position:
            style["suffix"] = append_tags(style.get("suffix", ""), position)
            style["mood"] = position
        if negative:
            style["negative"] = append_tags(style.get("negative", ""), negative)
        extra_pos = self.positive_extra.toPlainText().strip()
        extra_neg = self.negative_extra.toPlainText().strip()
        if extra_pos:
            style["suffix"] = append_tags(style.get("suffix", ""), extra_pos)
        if extra_neg:
            style["negative"] = append_tags(style.get("negative", ""), extra_neg)
        return style

    def _build_loras(self) -> list[dict[str, Any]]:
        result = []
        for row in range(self.lora_table.rowCount()):
            item = self.lora_table.item(row, 0)
            spin = self.lora_table.cellWidget(row, 1)
            if item and spin and item.checkState() == Qt.CheckState.Checked:
                result.append({"name": item.data(Qt.ItemDataRole.UserRole), "strength": spin.value()})
        return result

    def _build_detailers(self) -> list[dict[str, Any]]:
        cfg_value = float(self.cfg_spin.value())
        result = []
        for key, box, spin, choice in self.detailer_rows:
            if not box.isChecked():
                continue
            result.append({
                "model": choice["detector"],
                "prompt": choice.get("prompt", ""),
                "denoise": spin.value(),
                "guide_size": choice.get("guide_size", 1024),
                "steps": 20,
                "cfg": cfg_value,
                "feather": 5,
            })
        return result

    def _build_settings(self) -> dict[str, Any]:
        hires = {
            "enabled": self.hires_check.isChecked(),
            "scale": self.hires_scale.value(),
            "steps": self.hires_steps.value(),
            "denoise": self.hires_denoise.value(),
            "upscale_model": self.upscaler_combo.currentValue(),
            "model_scale": 4.0,
        }
        return {
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "steps": self.steps_spin.value(),
            "cfg": self.cfg_spin.value(),
            "sampler": self.sampler_combo.currentValue(),
            "scheduler": self.scheduler_combo.currentValue(),
            "seed_mode": self.seed_mode.currentData(),
            "base_seed": self.seed_spin.value(),
            "hires": hires,
        }

    def _build_project(self, mode: str, shots: list[dict[str, Any]], text: str) -> dict[str, Any]:
        data = copy.deepcopy(self.template)
        data["model"] = self.ckpt_combo.currentValue() or self.template.get("model", "")
        data["clip_skip"] = self.clip_skip.value()
        data["loras"] = self._build_loras()
        data.pop("lora", None)
        data["character"] = copy.deepcopy(self.template.get("character") or {})
        data["character"]["tags"] = self._character_tags()
        ref = self.char_ref.text().strip()
        if ref:
            data["character"]["use_ipadapter"] = True
            data["character"]["ipadapter"] = {
                "reference": ref.replace("\\", "/"),
                "weight": self.char_ref_weight.value(),
                "preset": "PLUS (high strength)",
                "weight_type": "linear",
                "start_at": 0.0,
                "end_at": 0.8,
            }
        else:
            data["character"]["use_ipadapter"] = False
            data["character"].pop("ipadapter", None)
        data["style"] = self._build_style()
        data["settings"] = self._build_settings()
        data["variants"] = self.variants_spin.value()
        wildcard_dir = self.wildcard_dir.text().strip()
        data["wildcards"] = {"enabled": self.wildcard_check.isChecked(), "dir": wildcard_dir}
        data["detailers"] = self._build_detailers()
        if self.style_ref_check.isChecked() and self.style_ref_edit.text().strip():
            data["style_ref"] = {
                "enabled": True,
                "image": self.style_ref_edit.text().strip().replace("\\", "/"),
                "weight": self.style_ref_weight.value(),
                "preset": "PLUS (high strength)",
                "weight_type": "style transfer",
                "start_at": 0.0,
                "end_at": 1.0,
            }
        else:
            data.pop("style_ref", None)

        name = slugify(self.output_name.text().strip(), "")
        if not name:
            name = slugify("".join(ch for ch in text if ch.isascii()), "")
        if not name:
            name = time.strftime("story_%Y%m%d_%H%M%S")
        project = new_project(name, text, data, str(self.template_path), mode=mode)
        project["shots"] = shots
        project["prefix"] = "anime_story/" + name
        project["server"] = self.cfg.comfy.base_url
        return project

    # ---------------------------------------------------------------- prompt generation

    def _llm(self) -> str:
        return self.llm_combo.currentValue() or self.cfg.ollama.default_model

    def generate_single(self, then_render: bool = False) -> None:
        if self.prompt_worker and self.prompt_worker.isRunning():
            return
        text = self.single_desc.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入描述。")
            return
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI / Ollama。")
            return
        if not self._llm():
            QMessageBox.information(self, "提示", "没有可用的 Ollama 模型，请先在设置/模型页选择。")
            return
        self._render_after_prompt = then_render
        options = SingleOptions(
            model=self._llm(),
            framing=self.framing.currentData(),
            mood=self._mood_text(),
            setting="",
            character_tags=self._character_tags(),
            style_positive=self._style_positive(),
            log=self.append_log,
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "single", text, single_options=options)
        worker.single_ready.connect(self._on_single_prompt)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在生成单图提示词…")
        worker.start()

    def _on_single_prompt(self, result: dict[str, str]) -> None:
        self.single_prompt.setPlainText(result.get("prompt", ""))
        self.btn_expand.setEnabled(True)
        self.append_log("单图提示词：%s" % result.get("prompt", ""))
        self.statusBar().showMessage("提示词已生成，可编辑后出图")
        if self._render_after_prompt:
            self._render_after_prompt = False
            self.start_render("single")

    def generate_story(self) -> None:
        if self.prompt_worker and self.prompt_worker.isRunning():
            return
        text = self.story_premise.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入剧情。")
            return
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI / Ollama。")
            return
        if not self._llm():
            QMessageBox.information(self, "提示", "没有可用的 Ollama 模型，请先在设置/模型页选择。")
            return
        options = StoryboardOptions(
            model=self._llm(), shots=self.story_shots.value(), chunk=12,
            mood=self._mood_text(), setting="",
            character_tags=self._character_tags(),
            style_positive=self._style_positive(),
            log=self.append_log,
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "story", text, story_options=options)
        worker.story_ready.connect(self._on_story_ready)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在生成分镜…")
        worker.start()

    def _on_story_ready(self, shots: list[dict[str, str]]) -> None:
        self._fill_shot_table(shots)
        self.append_log("分镜已生成：%d 镜" % len(shots))
        self.statusBar().showMessage("分镜已生成（共 %d 镜）" % len(shots))

    def _fill_shot_table(self, shots: list[dict[str, str]]) -> None:
        self.shot_table.setRowCount(0)
        for shot in shots:
            row = self.shot_table.rowCount()
            self.shot_table.insertRow(row)
            self.shot_table.setItem(row, 0, QTableWidgetItem(str(shot.get("id", "%02d" % (row + 1)))))
            self.shot_table.setItem(row, 1, QTableWidgetItem(str(shot.get("name", ""))))
            self.shot_table.setItem(row, 2, QTableWidgetItem(str(shot.get("prompt", ""))))

    def add_shot_row(self) -> None:
        row = self.shot_table.rowCount()
        self.shot_table.insertRow(row)
        self.shot_table.setItem(row, 0, QTableWidgetItem("%02d" % (row + 1)))
        self.shot_table.setItem(row, 1, QTableWidgetItem("shot_%02d" % (row + 1)))
        self.shot_table.setItem(row, 2, QTableWidgetItem(""))
        self.shot_table.selectRow(row)
        self.shot_table.editItem(self.shot_table.item(row, 2))

    def remove_shot_row(self) -> None:
        rows = sorted({index.row() for index in self.shot_table.selectedIndexes()}, reverse=True)
        if not rows and self.shot_table.currentRow() >= 0:
            rows = [self.shot_table.currentRow()]
        for row in rows:
            self.shot_table.removeRow(row)
        self._renumber_shots()

    def move_shot(self, delta: int) -> None:
        row = self.shot_table.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.shot_table.rowCount()):
            return
        values = [self.shot_table.item(row, col).text() if self.shot_table.item(row, col) else ""
                  for col in range(3)]
        other = [self.shot_table.item(target, col).text() if self.shot_table.item(target, col) else ""
                 for col in range(3)]
        for col in range(3):
            self.shot_table.item(row, col).setText(other[col])
            self.shot_table.item(target, col).setText(values[col])
        self.shot_table.selectRow(target)

    def _renumber_shots(self) -> None:
        for row in range(self.shot_table.rowCount()):
            item = self.shot_table.item(row, 0)
            if item:
                item.setText("%02d" % (row + 1))

    def expand_single(self) -> None:
        prompt = self.single_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "提示", "先生成单图提示词。")
            return
        if not self._llm():
            QMessageBox.information(self, "提示", "没有可用的 Ollama 模型，请先在设置/模型页选择。")
            return
        from PySide6.QtWidgets import QInputDialog
        total, ok = QInputDialog.getInt(self, "扩写成分镜", "分镜数量：", 4, 2, 50)
        if not ok:
            return
        initial = [{"id": "01", "name": slugify(prompt, "single") or "single", "prompt": prompt}]
        options = StoryboardOptions(
            model=self._llm(), shots=total, chunk=12,
            mood=self._mood_text(), setting="",
            character_tags=self._character_tags(),
            style_positive=self._style_positive(),
            log=self.append_log,
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "expand", self.single_desc.toPlainText().strip() or prompt,
                              story_options=options, initial_shots=initial)
        worker.story_ready.connect(self._on_expanded)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在扩写分镜…")
        worker.start()

    def _on_expanded(self, shots: list[dict[str, str]]) -> None:
        self._fill_shot_table(shots)
        self.btn_mode_single.setChecked(False)
        self.btn_mode_story.setChecked(True)
        self._switch_mode(1)
        self.append_log("已扩写为 %d 镜" % len(shots))

    def _on_prompt_failed(self, message: str) -> None:
        self._render_after_prompt = False
        self.append_log("生成提示词失败：%s" % message)
        self.statusBar().showMessage("生成失败")
        QMessageBox.warning(self, "生成失败", message)

    def _on_prompt_worker_finished(self) -> None:
        if not (self.render_worker and self.render_worker.isRunning()):
            self._set_generation_enabled(True)

    # ---------------------------------------------------------------- rendering

    def render_single_clicked(self) -> None:
        if not self.single_prompt.toPlainText().strip():
            self.generate_single(then_render=True)
            return
        self.start_render("single")

    def _collect_shots(self, selected_only: bool) -> list[dict[str, str]]:
        rows = sorted({index.row() for index in self.shot_table.selectedIndexes()}) \
            if selected_only else list(range(self.shot_table.rowCount()))
        shots = []
        for row in rows:
            prompt = (self.shot_table.item(row, 2).text() if self.shot_table.item(row, 2) else "").strip()
            if not prompt:
                continue
            shot_id = (self.shot_table.item(row, 0).text().strip() if self.shot_table.item(row, 0) else "")
            name = (self.shot_table.item(row, 1).text().strip() if self.shot_table.item(row, 1) else "")
            shots.append({"id": shot_id or "%02d" % (len(shots) + 1),
                          "name": name or "shot_%02d" % (len(shots) + 1),
                          "prompt": prompt})
        return shots

    def start_render(self, mode: str) -> None:
        if self.render_worker and self.render_worker.isRunning():
            return
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI。")
            return
        if mode == "single":
            prompt = self.single_prompt.toPlainText().strip()
            if not prompt:
                QMessageBox.information(self, "提示", "请先生成或填写提示词。")
                return
            shots = [{"id": "01", "name": slugify(prompt, "single") or "single", "prompt": prompt}]
            text = self.single_desc.toPlainText().strip() or prompt
        else:
            shots = self._collect_shots(self.chk_selected.isChecked())
            if not shots:
                QMessageBox.information(self, "提示", "没有可生成的镜头，请先生成或填写分镜。")
                return
            text = self.story_premise.toPlainText().strip() or shots[0]["prompt"]

        self.project = self._build_project(mode, shots, text)
        save_project(self.project, self.cfg.root)
        self.append_log("项目已保存：%s" % self.project["id"])
        settings = self.project["settings"]
        tasks = build_tasks(self.project, shots, int(self.project["variants"]),
                            settings.get("seed_mode", "increment"), int(settings.get("base_seed", 1)))
        self.tasks_by_id = {task.id: task for task in tasks}
        self.previews.clear()
        self.final_bytes.clear()
        self._reset_queue(tasks)
        self.progress.setValue(0)
        self.preview_info.setText("准备生成…")
        self.current_task_id = tasks[0].id if tasks else None

        hires = bool(settings.get("hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, self.project, tasks, hires)
        worker.task_updated.connect(self._on_task_update)
        worker.preview.connect(self._on_preview)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_render_finished)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(lambda: self._set_generation_enabled(True))
        self.render_worker = worker
        self._set_generation_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.statusBar().showMessage("正在生成 %d 张图…" % len(tasks))
        worker.start()

    def _reset_queue(self, tasks: list[Any]) -> None:
        self.queue_table.setRowCount(0)
        self.task_rows.clear()
        self.row_task_ids.clear()
        for task in tasks:
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_table.setItem(row, 0, QTableWidgetItem(task.label))
            self.queue_table.setItem(row, 1, QTableWidgetItem("等待"))
            self.queue_table.setItem(row, 2, QTableWidgetItem(""))
            self.queue_table.setItem(row, 3, QTableWidgetItem(""))
            self.queue_table.setItem(row, 4, QTableWidgetItem(str(task.seed)))
            self.task_rows[task.id] = row
            self.row_task_ids[row] = task.id
            self.queue_table.setRowHeight(row, 40)
        if tasks:
            self.queue_table.selectRow(0)

    def _on_task_update(self, summary: dict[str, Any]) -> None:
        task_id = summary["id"]
        row = self.task_rows.get(task_id)
        if row is None:
            return
        self.queue_table.item(row, 1).setText(summary["state"])
        self.queue_table.item(row, 2).setText(summary.get("stage") or "")
        total = summary.get("total") or 0
        self.queue_table.item(row, 3).setText(
            "%s/%s" % (summary.get("step", 0), total) if total else str(summary.get("step", 0)))
        if summary["state"] == "failed":
            for col in range(5):
                self.queue_table.item(row, col).setForeground(QBrush(Qt.GlobalColor.red))
            self.append_log("[%s] 失败：%s" % (summary.get("label"), summary.get("error")))
        if summary["state"] == "done":
            self._on_task_done(task_id)
        if self.chk_follow.isChecked() and summary["state"] in ("running", "submitted"):
            self.queue_table.selectRow(row)
            self.current_task_id = task_id
            self.preview_info.setText("%s · %s %s/%s · seed %s" % (
                summary.get("label"), summary.get("stage") or "", summary.get("step", 0),
                summary.get("total") or "?", summary.get("seed")))
            if total:
                self.progress.setValue(int(summary.get("step", 0) / total * 100))

    def _on_preview(self, task_id: str, data: bytes, image_type: str) -> None:
        self.previews[task_id] = data
        now = time.time()
        if now - self._icon_last.get(task_id, 0.0) > 0.2:
            self._icon_last[task_id] = now
            self._set_row_icon(task_id, data)
        if task_id == self.current_task_id or (
                self.chk_follow.isChecked() and self.queue_table.currentRow() == self.task_rows.get(task_id)):
            self._paint(data)

    def _set_row_icon(self, task_id: str, data: bytes) -> None:
        row = self.task_rows.get(task_id)
        if row is None:
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            36, 36, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
        item = self.queue_table.item(row, 0)
        if item:
            item.setIcon(QIcon(pixmap))

    def _paint(self, data: bytes) -> None:
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self.current_pixmap = pixmap
        self._apply_pixmap()

    def _apply_pixmap(self) -> None:
        if not self.current_pixmap:
            return
        scaled = self.current_pixmap.scaled(
            self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_pixmap()

    def _on_task_done(self, task_id: str) -> None:
        task = self.tasks_by_id.get(task_id)
        if not task or not task.image:
            return
        if task_id in self.final_bytes:
            return
        try:
            data, local = self._fetch_image(task.image)
        except Exception as exc:
            self.append_log("读取成品图失败：%s" % exc)
            return
        self.final_bytes[task_id] = data
        self._set_row_icon(task_id, data)
        self._add_gallery(task, data, local)
        if self.project is not None:
            self.project.setdefault("outputs", []).append(task.image)
            save_project(self.project, self.cfg.root)
        if task_id == self.current_task_id or self.chk_follow.isChecked():
            self._paint(data)
        if self.project and self.project.get("mode") == "single":
            self.btn_expand.setEnabled(True)

    def _fetch_image(self, image: str) -> tuple[bytes, Path | None]:
        normalized = image.replace("\\", "/")
        if "/" in normalized:
            subfolder, filename = normalized.rsplit("/", 1)
        else:
            subfolder, filename = "", normalized
        if self.cfg.comfy.output_dir:
            local = Path(self.cfg.comfy.output_dir) / subfolder / filename
            if local.is_file():
                return local.read_bytes(), local
        client = ComfyClient(self.cfg.comfy.base_url)
        return client.view(filename, subfolder, "output"), None

    def _add_gallery(self, task: Any, data: bytes, local: Path | None) -> None:
        image = QImage.fromData(data)
        pixmap = QPixmap.fromImage(image).scaled(
            150, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setText(task.label)
        item.setToolTip(task.image or "")
        if local is None:
            cache = self.cfg.cache_dir / "gallery"
            cache.mkdir(parents=True, exist_ok=True)
            local = cache / (task.label + ".png")
            local.write_bytes(data)
        item.setData(Qt.ItemDataRole.UserRole, str(local))
        self.gallery.addItem(item)

    def _open_gallery_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():
            os.startfile(str(Path(path).parent))  # noqa: S606
            os.startfile(path)  # noqa: S606
        else:
            QMessageBox.information(self, "提示", "找不到图片文件。")

    def _on_queue_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        task_id = self.row_task_ids.get(row)
        if not task_id:
            return
        self.current_task_id = task_id
        task = self.tasks_by_id.get(task_id)
        if task:
            total = task.total or 0
            self.preview_info.setText("%s · %s %s/%s · seed %s" % (
                task.label, task.stage or "", task.step, total or "?", task.seed))
        if task_id in self.final_bytes:
            self._paint(self.final_bytes[task_id])
        elif task_id in self.previews:
            self._paint(self.previews[task_id])

    def _on_render_finished(self, results: list[dict[str, Any]]) -> None:
        self.btn_cancel.setEnabled(False)
        done = [r for r in results if r["state"] == "done"]
        failed = [r for r in results if r["state"] == "failed"]
        self.append_log("渲染结束：成功 %d，失败 %d" % (len(done), len(failed)))
        self.statusBar().showMessage("渲染结束：成功 %d，失败 %d" % (len(done), len(failed)))
        self.progress.setValue(100 if not failed else self.progress.value())
        if self.project and self.project.get("mode") == "single":
            self.btn_expand.setEnabled(True)

    def _on_render_failed(self, message: str) -> None:
        self.btn_cancel.setEnabled(False)
        self.append_log("渲染失败：%s" % message)
        self.statusBar().showMessage("渲染失败")
        QMessageBox.warning(self, "渲染失败", message)

    def cancel_render(self) -> None:
        if self.render_worker and self.render_worker.isRunning():
            self.render_worker.cancel()
            self.append_log("已请求取消…")
            self.statusBar().showMessage("正在取消…")

    # ---------------------------------------------------------------- misc

    def _switch_mode(self, index: int) -> None:
        self.left_stack.setCurrentIndex(index)

    def _set_busy(self, busy: bool) -> None:
        for btn in (self.btn_reconnect, self.btn_restart, self.btn_settings):
            btn.setEnabled(not busy)

    def _set_generation_enabled(self, enabled: bool) -> None:
        for widget in (self.btn_single_prompt, self.btn_single_render, self.btn_story_prompt,
                       self.btn_story_render, self.tabs):
            widget.setEnabled(enabled)
        self.btn_single_render.setEnabled(enabled)
        self.btn_story_render.setEnabled(enabled)
        self.btn_expand.setEnabled(enabled and bool(self.single_prompt.toPlainText().strip()))

    def append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_view.appendPlainText("[%s] %s" % (stamp, message))

    def pick_char_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择角色参考图", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.char_ref.setText(path.replace("/", "\\"))

    def pick_style_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择画风参考图", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.style_ref_edit.setText(path.replace("/", "\\"))
            self.style_ref_check.setChecked(True)

    def pick_wildcard_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择通配符目录")
        if path:
            self.wildcard_dir.setText(path)

    def open_output_dir(self) -> None:
        path = self.cfg.comfy.output_dir
        if path and Path(path).is_dir():
            os.startfile(path)  # noqa: S606
        else:
            QMessageBox.information(self, "提示", "输出目录不存在：%s" % (path or "(未配置)"))

    def open_settings(self) -> None:
        models = [self.llm_combo.itemData(i) for i in range(self.llm_combo.count())] or self.ollama_models
        dialog = SettingsDialog(self.cfg, self, models=models)
        if not dialog.exec():
            return
        self.cfg = load_config()
        self.cfg.ensure_dirs()
        self.template_path = resolve_template(self.cfg)
        self.template = load_template(self.cfg)
        self.comfy_service = ComfyService(self.cfg)
        self._init_defaults()
        answer = QMessageBox.question(
            self, "应用设置", "设置已保存。是否重启 ComfyUI 以应用新配置（如预览参数）？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self.connect_services(restart=answer == QMessageBox.StandardButton.Yes)

    def restart_comfy(self) -> None:
        answer = QMessageBox.question(
            self, "重启 ComfyUI", "将重启本地 ComfyUI（可能中断其他任务），继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.connect_services(restart=True)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.render_worker and self.render_worker.isRunning():
            answer = QMessageBox.question(
                self, "正在生成", "还有任务在生成，确定退出并取消吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.render_worker.cancel()
            self.render_worker.wait(8000)
        if self.prompt_worker and self.prompt_worker.isRunning():
            self.prompt_worker.wait(3000)
        if self.connect_worker and self.connect_worker.isRunning():
            self.connect_worker.wait(3000)
        if self.comfy_service.owned and not self.cfg.comfy.keep_running_on_exit:
            self.comfy_service.stop()
        event.accept()
