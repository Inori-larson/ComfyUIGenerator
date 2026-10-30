"""Main window for the ComfyUI Generator desktop app (M1)."""

from __future__ import annotations

import copy
import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from comfyui_generator.core.assets import Assets
from comfyui_generator.core.comfy import ComfyClient
from comfyui_generator.core.config import (
    AppConfig, load_config, load_template, resolve_template, save_config,
)
from comfyui_generator.core.detailers import build_detailer_choices, filter_detector_models, local_detectors
from comfyui_generator.core.jobs import Task, build_tasks
from comfyui_generator.core.lora_info import is_style_lora, lora_tag_info
from comfyui_generator.core.lora_sources import lora_entries
from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.project import (
    clear_story_partial, list_projects, load_project, load_session,
    load_story_partial, move_to_trash, new_project, save_project,
    save_session, save_story_partial,
)
from comfyui_generator.core.services import ComfyService
from comfyui_generator.core.single import FRAMING_TAGS, SingleOptions
from comfyui_generator.core.storyboard import (
    StoryboardOptions, extract_premise_beats, premise_from_json,
    shots_from_json, slugify,
)
from comfyui_generator.core.tag_cache import load_tag_cache, update_tag_cache
from comfyui_generator.core.tags import append_tags, estimate_tokens
from comfyui_generator.core.translate import translate_to_tags
from comfyui_generator.ui.branding import app_icon, logo_pixmap
from comfyui_generator.ui.dialogs import (
    CompareDialog, ProjectDialog, ShotDetailsDialog, TagReferenceDialog, TrashDialog,
)
from comfyui_generator.ui.settings_dialog import SettingsDialog
from comfyui_generator.ui.widgets import SearchComboBox, WrappingTabs
from comfyui_generator.ui.workers import AssetsWorker, AutoTranslateWorker, ConnectWorker, LoraTagsWorker, PromptWorker, RenderWorker, TagTranslateWorker

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
DEFAULT_POSITIVE_EXTRA_TAGS = [
    "masterpiece", "best quality", "absurdres", "ultra-detailed", "extremely detailed",
    "sharp focus", "highres", "official art",
    "beautiful detailed eyes", "beautiful detailed face",
]
DEFAULT_POSITIVE_EXTRA_ZH_TAGS = [
    "杰作", "最佳质量", "极高分辨率", "超详细", "极详细",
    "清晰聚焦", "高分辨率", "官方艺术",
    "美丽的详细眼睛", "美丽的详细面部",
]
DEFAULT_NEGATIVE_EXTRA_TAGS = [
    "lowres", "worst quality", "low quality", "normal quality", "bad anatomy",
    "bad hands", "missing fingers", "extra fingers", "fewer fingers", "mutated hands",
    "poorly drawn hands", "poorly drawn face", "deformed", "disfigured", "mutation",
    "ugly", "blurry", "jpeg artifacts", "watermark", "signature", "text", "username",
    "extra limbs", "extra arms", "extra legs", "malformed limbs", "fused fingers",
    "long neck", "cloned face",
    "western cartoon", "censor", "censored",
    "bar censor", "mosaic censoring", "convenient censoring", "blurry pussy",
    "poorly drawn pussy", "unfinished", "sketch",
]
DEFAULT_NEGATIVE_EXTRA_ZH_TAGS = [
    "低分辨率", "最差质量", "低质量", "正常质量", "糟糕的解剖结构",
    "糟糕的手", "缺少手指", "多余的手指", "手指过少", "变异的手",
    "画得很差的手", "画得很差的脸", "变形", "毁容", "突变",
    "丑陋", "模糊", "jpeg 压缩伪影", "水印", "签名", "文字", "用户名",
    "多余肢体", "多余手臂", "多余的腿", "畸形肢体", "融合的手指",
    "长脖子", "重复的脸", "欧美卡通", "打码", "已打码",
    "条形打码", "马赛克打码", "便利打码", "模糊的阴道",
    "画得很差的阴道", "未完成", "草图",
]
DEFAULT_POSITIVE_EXTRA_EN = ", ".join(DEFAULT_POSITIVE_EXTRA_TAGS)
DEFAULT_POSITIVE_EXTRA_ZH = "，".join(DEFAULT_POSITIVE_EXTRA_ZH_TAGS)
DEFAULT_NEGATIVE_EXTRA_EN = ", ".join(DEFAULT_NEGATIVE_EXTRA_TAGS)
DEFAULT_NEGATIVE_EXTRA_ZH = "，".join(DEFAULT_NEGATIVE_EXTRA_ZH_TAGS)
DEFAULT_EXTRA_PAIRS = dict(zip(
    DEFAULT_POSITIVE_EXTRA_TAGS + DEFAULT_NEGATIVE_EXTRA_TAGS,
    DEFAULT_POSITIVE_EXTRA_ZH_TAGS + DEFAULT_NEGATIVE_EXTRA_ZH_TAGS,
))
FRAMING_LABELS = [
    ("自动（由模型决定）", "auto"),
    ("全身", "full_body"),
    ("半身", "upper_body"),
    ("特写", "close_up"),
    ("头像", "portrait"),
    ("广角", "wide"),
]

PROMPT_EN_ROLE = int(Qt.ItemDataRole.UserRole)
PROMPT_ZH_ROLE = PROMPT_EN_ROLE + 1
OUTLINE_ROLE = PROMPT_ZH_ROLE + 1
CAST_ROLE = OUTLINE_ROLE + 1
SCRIPT_ROLE = CAST_ROLE + 1
PHASE_ROLE = SCRIPT_ROLE + 1
CLOTHING_ROLE = PHASE_ROLE + 1
CHARACTERS_ROLE = CLOTHING_ROLE + 1
CHARACTER_STATES_ROLE = CHARACTERS_ROLE + 1
SCENE_ROLE = CHARACTER_STATES_ROLE + 1


def _label(text: str, name: str = "Section") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Generator")
        self.setWindowIcon(app_icon())
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
        self.assets_worker: AssetsWorker | None = None
        self.prompt_worker: PromptWorker | None = None
        self.render_worker: RenderWorker | None = None
        self.tasks_by_id: dict[str, Any] = {}
        self.task_rows: dict[str, int] = {}
        self.row_task_ids: dict[int, str] = {}
        self.previews: dict[str, bytes] = {}
        self.final_bytes: dict[str, bytes] = {}
        self._icon_last: dict[str, float] = {}
        self._lora_info_cache: dict[str, dict] = {}
        self._reference_tags: list[str] = []
        self._lora_paths: dict[str, str] = {}
        self._online_tried: set[str] = set()
        self.lora_tags_worker: LoraTagsWorker | None = None
        self._character_lora_names: set[str] = set()
        self._style_lora_names: set[str] = set()
        self._body_lora_names: set[str] = set()
        self._action_lora_names: set[str] = set()
        self._clothing_lora_names: set[str] = set()
        self._syncing_tags = False
        self._tag_cache_path = str(self.cfg.root / "cache" / "tag_translation.json")
        update_tag_cache(self._tag_cache_path, DEFAULT_EXTRA_PAIRS)
        self._positive_extra_en = DEFAULT_POSITIVE_EXTRA_EN
        self._positive_extra_zh = DEFAULT_POSITIVE_EXTRA_ZH
        self._negative_extra_en = DEFAULT_NEGATIVE_EXTRA_EN
        self._negative_extra_zh = DEFAULT_NEGATIVE_EXTRA_ZH
        self._activation_en = ""
        self._activation_zh = ""
        self._auto_timers: dict[str, QTimer] = {}
        self._auto_workers: dict[str, AutoTranslateWorker] = {}
        self._auto_pending: set[str] = set()
        self._body_watch_dir = ""
        self.body_watcher = QFileSystemWatcher(self)
        self.body_watcher.directoryChanged.connect(self._on_body_dir_changed)
        self.body_refresh_timer = QTimer(self)
        self.body_refresh_timer.setSingleShot(True)
        self.body_refresh_timer.timeout.connect(self._refresh_body_loras)
        self._style_watch_dir = ""
        self.style_watcher = QFileSystemWatcher(self)
        self.style_watcher.directoryChanged.connect(self._on_style_dir_changed)
        self.style_refresh_timer = QTimer(self)
        self.style_refresh_timer.setSingleShot(True)
        self.style_refresh_timer.timeout.connect(self._refresh_style_loras)
        self._action_watch_dir = ""
        self.action_watcher = QFileSystemWatcher(self)
        self.action_watcher.directoryChanged.connect(self._on_action_dir_changed)
        self.action_refresh_timer = QTimer(self)
        self.action_refresh_timer.setSingleShot(True)
        self.action_refresh_timer.timeout.connect(self._refresh_action_loras)
        self._clothing_watch_dir = ""
        self.clothing_watcher = QFileSystemWatcher(self)
        self.clothing_watcher.directoryChanged.connect(self._on_clothing_dir_changed)
        self.clothing_refresh_timer = QTimer(self)
        self.clothing_refresh_timer.setSingleShot(True)
        self.clothing_refresh_timer.timeout.connect(self._refresh_clothing_loras)
        self.current_pixmap: QPixmap | None = None
        self.current_task_id: str | None = None
        self.project: dict[str, Any] | None = None
        self._run_prefix = ""
        self._run_signature = ""
        self.detailer_rows: list[tuple[str, QCheckBox, QDoubleSpinBox, dict[str, Any]]] = []
        self._detailer_state: dict[str, dict[str, Any]] = {}
        self._render_after_prompt = False
        self._rewrite_row: int | None = None
        self._syncing_shots = False
        self._single_prompt_en = ""
        self._single_prompt_zh = ""
        self._restoring_state = False

        self._build_ui()
        self._build_menu()
        self._init_defaults()
        self._setup_auto_translate()
        self._restore_ui_state()
        self._update_partial_button()
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(15000)
        self._state_timer.timeout.connect(self._save_ui_state)
        self._state_timer.start()
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
        self.main_split = split
        self.main_vsplit = vsplit
        root.addWidget(vsplit, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        actions = [
            ("新建项目", "Ctrl+N", self.new_project_clicked),
            ("打开项目…", "Ctrl+O", self.open_project_clicked),
            ("保存项目", "Ctrl+S", self.save_project_clicked),
            (None, None, None),
            ("打开输出目录", None, self.open_output_dir),
            ("退出", None, self.close),
        ]
        for text, shortcut, slot in actions:
            if text is None:
                file_menu.addSeparator()
                continue
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)

        tools_menu = self.menuBar().addMenu("工具")
        for text, slot in (("回收站…", self.open_trash), ("变体对比…", self.compare_variants)):
            action = QAction(text, self)
            action.triggered.connect(slot)
            tools_menu.addAction(action)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(30))
        logo.setFixedSize(30, 30)
        row.addWidget(logo)
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
        panel.setMinimumWidth(390)
        panel.setMaximumWidth(580)
        return panel

    def _build_single_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(_label("角色标签（会拼入提示词）"))
        self.single_role = QPlainTextEdit()
        self.single_role.setPlaceholderText("例：yixuan \\(zenless zone zero\\), solo, hairclip")
        self.single_role.setFixedHeight(52)
        layout.addWidget(self.single_role)

        layout.addWidget(_label("初始服装"))
        self.single_clothing = QPlainTextEdit()
        self.single_clothing.setPlaceholderText("例：black blazer, black pantyhose")
        self.single_clothing.setFixedHeight(44)
        layout.addWidget(self.single_clothing)

        layout.addWidget(_label("大场景"))
        self.single_scene = QLineEdit()
        self.single_scene.setPlaceholderText("例：同一住宅客厅")
        layout.addWidget(self.single_scene)

        layout.addWidget(_label("画面描述"))
        self.single_desc = QPlainTextEdit()
        self.single_desc.setPlaceholderText("例：晴天，仪玄在公园长椅上吃冰淇淋，微笑看镜头")
        self.single_desc.setFixedHeight(80)
        layout.addWidget(self.single_desc)

        layout.addWidget(_label("其它（可选）"))
        self.single_extra = QPlainTextEdit()
        self.single_extra.setPlaceholderText("例：夜晚，暖色台灯光")
        self.single_extra.setFixedHeight(44)
        layout.addWidget(self.single_extra)

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
        self.btn_single_external = QPushButton("外部 AI 生成提示词")
        self.btn_single_external.clicked.connect(
            lambda: self.generate_single(False, True))
        layout.addWidget(self.btn_single_external)

        layout.addWidget(_label("提示词（中文，可手动修改）"))
        self.single_prompt = QPlainTextEdit()
        self.single_prompt.setPlaceholderText("模型生成后显示中文，可删改；出图时自动转回英文标签")
        layout.addWidget(self.single_prompt, 1)
        self.single_prompt_stats = _label("英文标签 0 · 约 2 tokens", "Hint")
        layout.addWidget(self.single_prompt_stats)
        self.single_prompt.textChanged.connect(self._on_single_prompt_changed)
        hint = _label("只显示中文；点“生成图片”时自动映射为英文 Danbooru 标签。没有提示词时可直接用激活标签出图", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

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
        layout.setSpacing(6)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(3)

        form_layout.addWidget(_label("角色标签（会拼入提示词）"))
        self.story_role = QPlainTextEdit()
        self.story_role.setPlaceholderText("例：yixuan \\(zenless zone zero\\), solo, hairclip")
        self.story_role.setFixedHeight(44)
        form_layout.addWidget(self.story_role)

        form_layout.addWidget(_label("初始服装"))
        self.story_clothing = QPlainTextEdit()
        self.story_clothing.setPlaceholderText("例：hairclip, puritan collar, black blazer, black pantyhose")
        self.story_clothing.setFixedHeight(40)
        form_layout.addWidget(self.story_clothing)

        form_layout.addWidget(_label("大场景"))
        self.story_scene = QLineEdit()
        self.story_scene.setPlaceholderText("例：同一住宅；细地点可由模型延伸到卧室、厨房、浴室")
        form_layout.addWidget(self.story_scene)

        form_layout.addWidget(_label("剧情（可带 01. 02. 编号）"))
        self.story_premise = QPlainTextEdit()
        self.story_premise.setPlaceholderText("例：01. 她回家…… 02. 她坐在沙发上……")
        self.story_premise.setFixedHeight(76)
        form_layout.addWidget(self.story_premise)

        form_layout.addWidget(_label("其它（可选）"))
        self.story_extra = QPlainTextEdit()
        self.story_extra.setPlaceholderText("例：夜晚，暖色台灯光，情绪克制")
        self.story_extra.setFixedHeight(40)
        form_layout.addWidget(self.story_extra)

        row = QHBoxLayout()
        row.addWidget(_label("分镜数", "Hint"))
        self.story_shots = QSpinBox()
        self.story_shots.setRange(1, 200)
        self.story_shots.setValue(6)
        row.addWidget(self.story_shots)
        self.btn_story_prompt = QPushButton("生成分镜")
        self.btn_story_prompt.clicked.connect(lambda: self.generate_story())
        row.addWidget(self.btn_story_prompt, 1)
        form_layout.addLayout(row)
        self.btn_story_external = QPushButton("外部 AI 生成分镜")
        self.btn_story_external.clicked.connect(lambda: self.generate_story(True))
        form_layout.addWidget(self.btn_story_external)
        self.btn_restore_partial = QPushButton("恢复上次未完成分镜")
        self.btn_restore_partial.clicked.connect(self.restore_partial_story)
        form_layout.addWidget(self.btn_restore_partial)
        self.btn_continue_partial = QPushButton("继续未完成分镜")
        self.btn_continue_partial.clicked.connect(self.continue_partial_story)
        form_layout.addWidget(self.btn_continue_partial)

        self.shot_table = QTableWidget(0, 4)
        self.shot_table.setHorizontalHeaderLabels(["锁", "镜号", "名称", "画面提示词（中文，可编辑）"])
        self.shot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.shot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.shot_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                        | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.shot_table.itemChanged.connect(self._on_shot_item_changed)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(form)
        splitter.addWidget(self.shot_table)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 520])
        self.shot_table.setMinimumHeight(180)
        layout.addWidget(splitter, 1)
        self.shot_stats = _label("0 镜 · 0 英文标签 · 约 0 tokens", "Hint")
        layout.addWidget(self.shot_stats)
        hint = _label("分镜只显示中文；出图时自动映射为英文 Danbooru 标签。空镜可直接用激活标签出图", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        tools = QHBoxLayout()
        for text, slot in (("+ 添加", self.add_shot_row), ("全选", self.select_all_shots),
                           ("删除选中", self.remove_shot_row), ("删除全部", self.clear_shot_rows)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        layout.addLayout(tools)

        move_tools = QHBoxLayout()
        for text, slot in (("↑ 上移", lambda: self.move_shot(-1)), ("↓ 下移", lambda: self.move_shot(1))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            move_tools.addWidget(btn)
        move_tools.addStretch(1)
        layout.addLayout(move_tools)

        self.btn_rewrite_shot = QPushButton("改写选中镜…")
        self.btn_rewrite_shot.clicked.connect(self.rewrite_selected_shot)
        layout.addWidget(self.btn_rewrite_shot)

        self.btn_shot_details = QPushButton("查看分镜详情…")
        self.btn_shot_details.clicked.connect(self.show_shot_details)
        layout.addWidget(self.btn_shot_details)

        json_row = QHBoxLayout()
        self.btn_export_shots = QPushButton("导出全部分镜 JSON")
        self.btn_export_shots.clicked.connect(self.export_shots_json)
        self.btn_import_shots = QPushButton("上传任意分镜 JSON")
        self.btn_import_shots.clicked.connect(self.import_shots_json)
        json_row.addWidget(self.btn_export_shots)
        json_row.addWidget(self.btn_import_shots)
        layout.addLayout(json_row)

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
        self.tabs = WrappingTabs()
        self.tabs.addTab(self._build_models_tab(), "模型")
        self.tabs.addTab(self._build_character_tab(), "角色")
        self.tabs.addTab(self._build_style_lora_tab(), "风格")
        self.tabs.addTab(self._build_body_lora_tab(), "身体")
        self.tabs.addTab(self._build_action_lora_tab(), "动作")
        self.tabs.addTab(self._build_clothing_lora_tab(), "服装")
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
        form.addWidget(_label("Ollama 模型（可替换，可输入）"))
        self.llm_combo = SearchComboBox(placeholder="选择或输入 Ollama 模型名", allow_free_text=True)
        form.addWidget(self.llm_combo)
        form.addWidget(_label("底模（Checkpoint，可输入）"))
        self.ckpt_combo = SearchComboBox(placeholder="选择或输入 Checkpoint 名", allow_free_text=True)
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

    def _make_lora_table(self) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["名称", "强度"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return table

    def _build_character_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("角色 LoRA（可多选）"))
        self.lora_table = self._make_lora_table()
        self.lora_table.itemChanged.connect(self._on_lora_item_changed)
        self.lora_table.cellClicked.connect(
            lambda row, col: self._toggle_lora_row(self.lora_table, row, col))
        layout.addWidget(self.lora_table, 1)
        hint = _label("勾选 LoRA 只生成「参考标签」；激活标签默认空，需手动填写或从参考标签选择", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.btn_scan_loras_char = QPushButton("重新扫描 LoRA")
        self.btn_scan_loras_char.clicked.connect(self.refresh_loras)
        layout.addWidget(self.btn_scan_loras_char)
        layout.addWidget(_label("激活标签（英文，可编辑）"))
        self.tags_edit = QPlainTextEdit()
        self.tags_edit.setFixedHeight(100)
        self.tags_edit.setPlaceholderText("默认为空；输入英文 Booru 标签，中文对照自动生成")
        self.tags_edit.textChanged.connect(self._update_tag_estimate)
        layout.addWidget(self.tags_edit)
        layout.addWidget(_label("中文对照（只读）"))
        self.tags_zh = QPlainTextEdit()
        self.tags_zh.setReadOnly(True)
        self.tags_zh.setFixedHeight(80)
        self.tags_zh.setPlaceholderText("英文标签的中文对照")
        layout.addWidget(self.tags_zh)
        tags_hint = _label("英文是实际出图标签；中文只读，由模型自动翻译生成", "Hint")
        tags_hint.setWordWrap(True)
        layout.addWidget(tags_hint)
        self.tag_estimate = _label("标签 0 · 约 2 tokens", "Hint")
        layout.addWidget(self.tag_estimate)
        row_tags = QHBoxLayout()
        self.btn_reference = QPushButton("参考标签（0）")
        self.btn_reference.setEnabled(False)
        self.btn_reference.clicked.connect(self.open_reference_tags)
        self.btn_clear_tags = QPushButton("清空")
        self.btn_clear_tags.clicked.connect(self._clear_activation_tags)
        row_tags.addWidget(self.btn_reference)
        row_tags.addWidget(self.btn_clear_tags)
        layout.addLayout(row_tags)
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

    def _build_style_lora_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("风格 LoRA（可多选）"))
        self.style_lora_table = self._make_lora_table()
        self.style_lora_table.cellClicked.connect(
            lambda row, col: self._toggle_lora_row(self.style_lora_table, row, col))
        layout.addWidget(self.style_lora_table, 1)
        hint = _label(
            "文件名含 style / screencap / hrf / aesthetic 等会自动归入这里；"
            "勾选后自动把该 LoRA 的触发词加入出图，不影响角色标签。", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.btn_scan_loras_style = QPushButton("重新扫描 LoRA")
        self.btn_scan_loras_style.clicked.connect(self.refresh_loras)
        layout.addWidget(self.btn_scan_loras_style)
        layout.addStretch(1)
        return page

    def _build_body_lora_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("身体部位 LoRA（可多选）"))
        self.body_lora_table = self._make_lora_table()
        self.body_lora_table.cellClicked.connect(
            lambda row, col: self._toggle_lora_row(self.body_lora_table, row, col))
        layout.addWidget(self.body_lora_table, 1)
        hint = _label(
            "从 models/loras/身体部位 扫描；只有当前镜头涉及该 LoRA 的触发词时才加载并注入，不影响角色标签", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.btn_scan_loras_body = QPushButton("重新扫描 LoRA")
        self.btn_scan_loras_body.clicked.connect(self.refresh_loras)
        layout.addWidget(self.btn_scan_loras_body)
        layout.addStretch(1)
        return page

    def _build_action_lora_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("动作 / 姿势 LoRA（可多选）"))
        self.action_lora_table = self._make_lora_table()
        self.action_lora_table.cellClicked.connect(
            lambda row, col: self._toggle_lora_row(self.action_lora_table, row, col))
        layout.addWidget(self.action_lora_table, 1)
        hint = _label(
            "从 models/loras/动作 扫描；只有当前镜头涉及该 LoRA 的触发词时才加载并注入，不污染角色标签", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.btn_scan_loras_action = QPushButton("重新扫描 LoRA")
        self.btn_scan_loras_action.clicked.connect(self.refresh_loras)
        layout.addWidget(self.btn_scan_loras_action)
        layout.addStretch(1)
        return page

    def _build_clothing_lora_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("服装 LoRA（可多选）"))
        self.clothing_lora_table = self._make_lora_table()
        self.clothing_lora_table.cellClicked.connect(
            lambda row, col: self._toggle_lora_row(self.clothing_lora_table, row, col))
        layout.addWidget(self.clothing_lora_table, 1)
        hint = _label(
            "从 models/loras/服装 扫描；只有当前镜头涉及该 LoRA 的触发词时才加载并注入，服装状态仍由角色锁定表维护", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.btn_scan_loras_clothing = QPushButton("重新扫描 LoRA")
        self.btn_scan_loras_clothing.clicked.connect(self.refresh_loras)
        layout.addWidget(self.btn_scan_loras_clothing)
        layout.addStretch(1)
        return page

    def _build_picture_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

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
        self.sampler_combo = SearchComboBox(placeholder="选择或输入采样器", allow_free_text=True)
        layout.addWidget(self.sampler_combo)
        layout.addWidget(_label("调度器"))
        self.scheduler_combo = SearchComboBox(placeholder="选择或输入调度器", allow_free_text=True)
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
        hint = _label("递增 = 每次点击生成新种子（抽卡）；固定 = 重复同一种子；随机 = 每张随机", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(_label("每个分镜张数", "Hint"))
        self.variants_spin = QSpinBox()
        self.variants_spin.setRange(1, 8)
        row.addWidget(self.variants_spin)
        layout.addLayout(row)

        self.img2img_check = QCheckBox("启用镜头间图生图桥接")
        self.img2img_check.setChecked(True)
        layout.addWidget(self.img2img_check)
        row = QHBoxLayout()
        row.addWidget(_label("桥接重绘幅度", "Hint"))
        self.img2img_denoise = QDoubleSpinBox()
        self.img2img_denoise.setRange(0.15, 0.9)
        self.img2img_denoise.setSingleStep(0.05)
        self.img2img_denoise.setValue(0.35)
        row.addWidget(self.img2img_denoise)
        row.addStretch(1)
        layout.addLayout(row)
        img_hint = _label("30 个关键帧不变；两镜之间的过渡图张数由镜头差异自动决定，从上一镜逐渐过渡到下一镜", "Hint")
        img_hint.setWordWrap(True)
        layout.addWidget(img_hint)

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
        self.upscaler_combo = SearchComboBox(placeholder="选择或输入放大模型", allow_free_text=True)
        layout.addWidget(self.upscaler_combo)
        layout.addStretch(1)
        return page

    def _build_detailer_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("勾选需要重绘的部位；denoise 越高改动越大"))
        self.detailer_hint = _label("等待扫描检测模型…", "Hint")
        self.detailer_hint.setWordWrap(True)
        layout.addWidget(self.detailer_hint)
        self.btn_scan_assets = QPushButton("重新扫描模型")
        self.btn_scan_assets.clicked.connect(self.refresh_assets)
        layout.addWidget(self.btn_scan_assets)
        self.detailer_box = QVBoxLayout()
        self.detailer_box.setSpacing(6)
        layout.addLayout(self.detailer_box)
        layout.addStretch(1)
        return page

    def _build_prompt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("正向提示词（中文，可编辑）"))
        self.positive_extra = QPlainTextEdit()
        self.positive_extra.setFixedHeight(90)
        self.positive_extra.setPlainText(DEFAULT_POSITIVE_EXTRA_ZH)
        layout.addWidget(self.positive_extra)
        layout.addWidget(_label("负向提示词（中文，可编辑）"))
        self.negative_extra = QPlainTextEdit()
        self.negative_extra.setFixedHeight(170)
        self.negative_extra.setPlainText(DEFAULT_NEGATIVE_EXTRA_ZH)
        layout.addWidget(self.negative_extra)
        hint = _label("这里只显示中文；出图时自动映射为英文 Booru 标签", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
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
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self._queue_menu)
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
        self.gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.gallery.customContextMenuRequested.connect(self._gallery_menu)
        self.bottom_tabs.addTab(self.gallery, "画廊")
        return self.bottom_tabs

    # ---------------------------------------------------------------- defaults

    def _init_defaults(self) -> None:
        template = self.template
        settings = template.get("settings") or {}
        self.template_label.setText("模板：%s" % self.template_path.name)
        self.clip_skip.setValue(int(template.get("clip_skip", -2)))

        w = int(settings.get("width", 1024))
        h = int(settings.get("height", 1344))
        self.width_spin.setValue(w)
        self.height_spin.setValue(h)
        index = next((i for i, (_l, rw, rh) in enumerate(RESOLUTIONS) if (rw, rh) == (w, h)), None)
        self.res_combo.setCurrentIndex(index if index is not None else self.res_combo.count() - 1)

        self.steps_spin.setValue(int(settings.get("steps", 30)))
        self.cfg_spin.setValue(float(settings.get("cfg", 5.0)))
        self._fill_combo(self.sampler_combo,
                         self._merge_values(self.assets.samplers or SAMPLERS),
                         settings.get("sampler", "euler_ancestral"))
        self._fill_combo(self.scheduler_combo,
                         self._merge_values(self.assets.schedulers or SCHEDULERS),
                         settings.get("scheduler", "normal"))
        mode = settings.get("seed_mode", "increment")
        self.seed_mode.setCurrentIndex(max(0, self.seed_mode.findData(mode)))
        self.seed_spin.setValue(int(settings.get("base_seed") or random.randint(1, 2 ** 31 - 1)))

        hires = settings.get("hires") or {}
        self.hires_check.setChecked(bool(hires.get("enabled", True)))
        self.hires_scale.setValue(float(hires.get("scale", 1.5)))
        self.hires_denoise.setValue(float(hires.get("denoise", 0.4)))
        self.hires_steps.setValue(int(hires.get("steps", 20)))
        self.variants_spin.setValue(int(template.get("variants") or 1))
        img2img = settings.get("img2img") or {}
        self.img2img_check.setChecked(bool(img2img.get("enabled", True)))
        self.img2img_denoise.setValue(float(img2img.get("denoise", 0.35)))
        wildcard_dir = (self.cfg.generation.wildcards or {}).get("dir", "")
        if not wildcard_dir and self.cfg.comfy.base_dir:
            wildcard_dir = str(Path(self.cfg.comfy.base_dir) / "user" / "default" / "wildcards")
        self.wildcard_dir.setText(wildcard_dir or str(self.cfg.root / "wildcards"))
        self._populate_loras()
        self._populate_detailers()
        self._sync_body_watcher()
        self._sync_style_watcher()
        self._sync_action_watcher()
        self._sync_clothing_watcher()
        self._apply_custom_models()

    @staticmethod
    def _merge_values(*groups: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for value in group:
                key = str(value)
                if key and key not in seen:
                    seen.add(key)
                    result.append(key)
        return result

    @staticmethod
    def _combo_values(combo: SearchComboBox) -> list[str]:
        values: list[str] = []
        for index in range(combo.count()):
            data = combo.itemData(index)
            values.append(str(data if data is not None else combo.itemText(index)))
        return values

    @staticmethod
    def _scan_model_dir(folder: str, suffixes: set[str]) -> list[str]:
        if not folder:
            return []
        root = Path(folder)
        if not root.is_dir():
            return []
        values: list[str] = []
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
            if path.is_file() and path.suffix.lower() in suffixes:
                values.append(path.relative_to(root).as_posix().replace("/", "\\"))
        return values

    def _apply_custom_models(self) -> None:
        current_llm = self.llm_combo.currentValue() or self.cfg.ollama.default_model
        values = self._merge_values(self._combo_values(self.llm_combo), [current_llm])
        self.llm_combo.setValues(values)
        if current_llm:
            self.llm_combo.selectValue(current_llm)

        suffixes = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
        current_ckpt = self.ckpt_combo.currentValue() or (self.template.get("model") or "")
        values = self._merge_values(
            self._combo_values(self.ckpt_combo), [self.template.get("model") or ""],
            self._scan_model_dir(self.cfg.models.checkpoint_dir, suffixes), [current_ckpt])
        self.ckpt_combo.setValues(values)
        if current_ckpt:
            self.ckpt_combo.selectValue(current_ckpt)

        current_up = self.upscaler_combo.currentValue()
        values = self._merge_values(
            self._combo_values(self.upscaler_combo),
            self._scan_model_dir(self.cfg.models.upscaler_dir,
                                 suffixes | {".onnx"}), [current_up])
        self.upscaler_combo.setValues(values)
        if current_up:
            self.upscaler_combo.selectValue(current_up)

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
        current_llm = self.llm_combo.currentValue() or self.cfg.ollama.default_model
        models = self._merge_values(models, [current_llm])
        self.ollama_models = list(models)
        self.llm_combo.setValues(models)
        if current_llm:
            self.llm_combo.selectValue(current_llm)

        suffixes = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
        current_ckpt = self.ckpt_combo.currentValue() or (self.template.get("model") or "")
        checkpoints = self._merge_values(
            self.assets.checkpoints or [self.template.get("model") or ""],
            self._scan_model_dir(self.cfg.models.checkpoint_dir, suffixes), [current_ckpt])
        self.ckpt_combo.setValues(checkpoints)
        if current_ckpt:
            self.ckpt_combo.selectValue(current_ckpt)

        current_sampler = self.sampler_combo.currentValue() or "euler_ancestral"
        current_scheduler = self.scheduler_combo.currentValue() or "normal"
        self._fill_combo(self.sampler_combo,
                         self._merge_values(self.assets.samplers or SAMPLERS, [current_sampler]),
                         current_sampler)
        self._fill_combo(self.scheduler_combo,
                         self._merge_values(self.assets.schedulers or SCHEDULERS, [current_scheduler]),
                         current_scheduler)
        current_up = self.upscaler_combo.currentValue()
        self.upscaler_combo.setValues(self._merge_values(
            self.assets.upscalers or [],
            self._scan_model_dir(self.cfg.models.upscaler_dir, suffixes | {".onnx"}),
            [current_up]))
        if current_up:
            self.upscaler_combo.selectValue(current_up)
        self._populate_loras()
        self._populate_detailers()

    def _read_lora_table(self, table: QTableWidget) -> dict[str, tuple[bool, float]]:
        data: dict[str, tuple[bool, float]] = {}
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            spin = table.cellWidget(row, 1)
            if item and spin:
                data[self._lora_key(item.data(Qt.ItemDataRole.UserRole))] = (
                    item.checkState() == Qt.CheckState.Checked, spin.value())
        return data

    def _fill_lora_table(self, table: QTableWidget, names: list[str],
                         configured: dict[str, float],
                         current: dict[str, tuple[bool, float]]) -> None:
        configured = {self._lora_key(key): value for key, value in configured.items()}
        current = {self._lora_key(key): value for key, value in current.items()}
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for name in names:
                row = table.rowCount()
                table.insertRow(row)
                item = QTableWidgetItem(Path(name).name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setToolTip(name)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                key = self._lora_key(name)
                checked, strength = current.get(key, (key in configured, configured.get(key, 0.9)))
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                table.setItem(row, 0, item)
                spin = QDoubleSpinBox()
                spin.setRange(0, 2)
                spin.setSingleStep(0.05)
                spin.setValue(strength)
                table.setCellWidget(row, 1, spin)
        finally:
            table.blockSignals(False)

    def _body_lora_dir(self) -> str:
        folder = self.cfg.lora.body_dir.strip()
        if folder:
            return folder
        base = self.cfg.comfy.base_dir.strip()
        if base:
            candidate = Path(base) / "models" / "loras" / "身体部位"
            if candidate.is_dir():
                return str(candidate)
        return ""

    def _sync_body_watcher(self, force: bool = False) -> None:
        folder = self._body_lora_dir()
        watching = list(self.body_watcher.directories())
        if not force and folder == self._body_watch_dir and (not folder or folder in watching):
            return
        for path in watching:
            self.body_watcher.removePath(path)
        self._body_watch_dir = ""
        if folder and Path(folder).is_dir():
            self.body_watcher.addPath(folder)
            self._body_watch_dir = folder

    def _on_body_dir_changed(self, _path: str = "") -> None:
        self._sync_body_watcher(force=True)
        self.body_refresh_timer.start(800)

    def _refresh_body_loras(self) -> None:
        self._sync_body_watcher(force=True)
        if self.assets_worker and self.assets_worker.isRunning():
            self.body_refresh_timer.start(1500)
            return
        self.append_log("检测到身体 LoRA 目录变化，自动重新扫描...")
        self.refresh_loras()

    def _sync_style_watcher(self, force: bool = False) -> None:
        folder = self.cfg.lora.style_dir.strip()
        watching = list(self.style_watcher.directories())
        if not force and folder == self._style_watch_dir and (not folder or folder in watching):
            return
        for path in watching:
            self.style_watcher.removePath(path)
        self._style_watch_dir = ""
        if folder and Path(folder).is_dir():
            self.style_watcher.addPath(folder)
            self._style_watch_dir = folder

    def _on_style_dir_changed(self, _path: str = "") -> None:
        self._sync_style_watcher(force=True)
        self.style_refresh_timer.start(800)

    def _refresh_style_loras(self) -> None:
        self._sync_style_watcher(force=True)
        if self.assets_worker and self.assets_worker.isRunning():
            self.style_refresh_timer.start(1500)
            return
        self.append_log("检测到风格 LoRA 目录变化，自动重新扫描...")
        self.refresh_loras()

    def _action_lora_dir(self) -> str:
        folder = self.cfg.lora.action_dir.strip()
        if folder and Path(folder).is_dir():
            return folder
        base = self.cfg.comfy.base_dir.strip()
        if base:
            for name in ("动作", "action", "actions", "pose", "poses"):
                candidate = Path(base) / "models" / "loras" / name
                if candidate.is_dir():
                    return str(candidate)
        return folder

    def _sync_action_watcher(self, force: bool = False) -> None:
        folder = self._action_lora_dir()
        watching = list(self.action_watcher.directories())
        if not force and folder == self._action_watch_dir and (not folder or folder in watching):
            return
        for path in watching:
            self.action_watcher.removePath(path)
        self._action_watch_dir = ""
        if folder and Path(folder).is_dir():
            self.action_watcher.addPath(folder)
            self._action_watch_dir = folder

    def _on_action_dir_changed(self, _path: str = "") -> None:
        self._sync_action_watcher(force=True)
        self.action_refresh_timer.start(800)

    def _refresh_action_loras(self) -> None:
        self._sync_action_watcher(force=True)
        if self.assets_worker and self.assets_worker.isRunning():
            self.action_refresh_timer.start(1500)
            return
        self.append_log("检测到动作 LoRA 目录变化，自动重新扫描...")
        self.refresh_loras()

    def _clothing_lora_dir(self) -> str:
        folder = self.cfg.lora.clothing_dir.strip()
        if folder and Path(folder).is_dir():
            return folder
        base = self.cfg.comfy.base_dir.strip()
        if base:
            for name in ("服装", "clothing", "clothes", "outfit", "outfits"):
                candidate = Path(base) / "models" / "loras" / name
                if candidate.is_dir():
                    return str(candidate)
        return folder

    def _sync_clothing_watcher(self, force: bool = False) -> None:
        folder = self._clothing_lora_dir()
        watching = list(self.clothing_watcher.directories())
        if not force and folder == self._clothing_watch_dir and (not folder or folder in watching):
            return
        for path in watching:
            self.clothing_watcher.removePath(path)
        self._clothing_watch_dir = ""
        if folder and Path(folder).is_dir():
            self.clothing_watcher.addPath(folder)
            self._clothing_watch_dir = folder

    def _on_clothing_dir_changed(self, _path: str = "") -> None:
        self._sync_clothing_watcher(force=True)
        self.clothing_refresh_timer.start(800)

    def _refresh_clothing_loras(self) -> None:
        self._sync_clothing_watcher(force=True)
        if self.assets_worker and self.assets_worker.isRunning():
            self.clothing_refresh_timer.start(1500)
            return
        self.append_log("检测到服装 LoRA 目录变化，自动重新扫描...")
        self.refresh_loras()

    def _collect_lora_names(self, configured: dict[str, float]) -> tuple[
            list[str], list[str], list[str], list[str], list[str]]:
        comfy = list(self.assets.loras)
        fallback = comfy or list(configured)
        char_dir = self.cfg.lora.character_dir
        style_dir = self.cfg.lora.style_dir
        body_dir = self._body_lora_dir()
        action_dir = self._action_lora_dir()
        clothing_dir = self._clothing_lora_dir()
        if char_dir:
            character = [entry["name"] for entry in lora_entries(char_dir, comfy)]
        else:
            character = [name for name in fallback if not is_style_lora(name)]
        if style_dir:
            styles = [entry["name"] for entry in lora_entries(style_dir, comfy)]
        else:
            styles = [name for name in fallback if is_style_lora(name)]

        base = self.cfg.comfy.base_dir.strip()
        lora_root = Path(base) / "models" / "loras" if base else None

        def scan_scope(folder: str) -> list[str]:
            if not folder:
                return []
            names: list[str] = []
            for entry in lora_entries(folder, comfy):
                name = entry["name"]
                if not entry["resolved"] and lora_root is not None:
                    try:
                        name = Path(entry["path"]).relative_to(lora_root).as_posix()
                    except ValueError:
                        pass
                names.append(name)
            return names

        body = scan_scope(body_dir)
        action = scan_scope(action_dir)
        clothing = scan_scope(clothing_dir)

        scoped_sets = [
            {name.lower() for name in values}
            for values in (body, action, clothing)
        ]
        scoped = set().union(*scoped_sets) if scoped_sets else set()
        if scoped:
            character = [name for name in character if name.lower() not in scoped]
            styles = [name for name in styles if name.lower() not in scoped]

        if char_dir:
            character_set = {name.lower() for name in character}
            styles = [name for name in styles if name.lower() not in character_set]
        if style_dir:
            style_set = {name.lower() for name in styles}
            character = [name for name in character if name.lower() not in style_set]

        for name in configured:
            if name.lower() in scoped:
                continue
            target_style = name in styles or (name not in character and is_style_lora(name))
            if target_style and name not in styles:
                styles.append(name)
            elif not target_style and name not in character:
                character.append(name)

        def unique(values: list[str]) -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            for value in values:
                key = value.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(value)
            return result

        return (unique(character), unique(styles), unique(body),
                unique(action), unique(clothing))

    def _populate_loras(self) -> None:
        configured: dict[str, float] = {}
        for lora in (self.template.get("loras") or
                     ([self.template["lora"]] if self.template.get("lora") else [])):
            if lora.get("name"):
                configured[self._lora_key(lora["name"])] = float(lora.get("strength", 0.9))
        (character_names, style_names, body_names,
         action_names, clothing_names) = self._collect_lora_names(configured)
        folders = (self.cfg.lora.character_dir, self.cfg.lora.style_dir,
                   self._body_lora_dir(), self._action_lora_dir(),
                   self._clothing_lora_dir())
        if self.assets.loras and any(folders):
            for folder in folders:
                if not folder:
                    continue
                for entry in lora_entries(folder, self.assets.loras):
                    if not entry["resolved"]:
                        self.append_log(
                            "警告：%s 不在 ComfyUI LoRA 列表中，请加入搜索路径" % entry["display"])
        self._character_lora_names = {self._lora_key(name) for name in character_names}
        self._style_lora_names = {self._lora_key(name) for name in style_names}
        self._body_lora_names = {self._lora_key(name) for name in body_names}
        self._action_lora_names = {self._lora_key(name) for name in action_names}
        self._clothing_lora_names = {self._lora_key(name) for name in clothing_names}
        self._lora_paths = {
            self._lora_key(name): self._resolve_lora_path(name)
            for name in set(character_names + style_names + body_names
                            + action_names + clothing_names)
        }
        self._fill_lora_table(self.lora_table, character_names, configured,
                              self._read_lora_table(self.lora_table))
        self._fill_lora_table(self.style_lora_table, style_names, configured,
                              self._read_lora_table(self.style_lora_table))
        self._fill_lora_table(self.body_lora_table, body_names, configured,
                              self._read_lora_table(self.body_lora_table))
        self._fill_lora_table(self.action_lora_table, action_names, configured,
                              self._read_lora_table(self.action_lora_table))
        self._fill_lora_table(self.clothing_lora_table, clothing_names, configured,
                              self._read_lora_table(self.clothing_lora_table))
        self._refresh_reference_tags()

    def refresh_loras(self) -> None:
        self._lora_info_cache.clear()
        self._online_tried.clear()
        if self.connected:
            self.refresh_assets()
        else:
            self._populate_loras()
            self.append_log("已重新扫描 LoRA：角色 %d / 风格 %d / 身体 %d / 动作 %d / 服装 %d" % (
                self.lora_table.rowCount(), self.style_lora_table.rowCount(),
                self.body_lora_table.rowCount(), self.action_lora_table.rowCount(),
                self.clothing_lora_table.rowCount()))

    def _resolve_lora_path(self, name: str) -> str:
        direct = Path(name)
        if direct.is_file():
            return str(direct)
        for folder in (self.cfg.lora.character_dir, self.cfg.lora.style_dir,
                       self._body_lora_dir(), self._action_lora_dir(),
                       self._clothing_lora_dir()):
            if not folder:
                continue
            for entry in lora_entries(folder, self.assets.loras):
                if entry["name"] == name:
                    return entry["path"]
        base = self.cfg.comfy.base_dir
        if base:
            root = Path(base) / "models" / "loras"
            relative = Path(str(name).replace("\\", os.sep).replace("/", os.sep))
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
            basename = Path(str(name).replace("\\", "/")).name.lower()
            for file in root.rglob("*"):
                if file.is_file() and file.name.lower() == basename:
                    return str(file)
        return name

    def _on_lora_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_tags or item.column() != 0:
            return
        self._sync_character_tags()

    def _toggle_lora_row(self, table: QTableWidget, row: int, column: int) -> None:
        if row < 0 or column == 0:
            return
        item = table.item(row, 0)
        if item is None:
            return
        if item.checkState() != Qt.CheckState.Checked:
            item.setCheckState(Qt.CheckState.Checked)
        elif table is self.lora_table:
            self._sync_character_tags()

    def _clear_activation_tags(self) -> None:
        self.tags_edit.clear()
        self.tags_zh.clear()
        self._activation_en = ""
        self._activation_zh = ""

    def _update_tag_estimate(self) -> None:
        text = self.tags_edit.toPlainText()
        if not text.strip():
            self.tags_zh.clear()
            self._activation_en = ""
            self._activation_zh = ""
        elif text.strip() == self._activation_zh and self._activation_en:
            text = self._activation_en
        count = len([tag for tag in text.split(",") if tag.strip()])
        tokens = estimate_tokens(text)
        self.tag_estimate.setText("标签 %d · 约 %d tokens" % (count, tokens))

    def _on_single_prompt_changed(self) -> None:
        if self.single_prompt.toPlainText().strip() == self._single_prompt_zh:
            self._update_single_prompt_stats()
        else:
            self.single_prompt_stats.setText("已修改；出图时重新统计")

    def _update_single_prompt_stats(self) -> None:
        text = self._single_prompt_en or self.single_prompt.toPlainText().strip()
        tags = [tag.strip() for tag in text.split(",") if tag.strip()]
        self.single_prompt_stats.setText(
            "英文标签 %d · 约 %d tokens" % (len(tags), estimate_tokens(tags)))

    def _setup_auto_translate(self) -> None:
        self._auto_fields = {
            "single": (self.single_prompt, "_single_prompt_en", "_single_prompt_zh",
                       self._update_single_prompt_stats),
            "positive": (self.positive_extra, "_positive_extra_en", "_positive_extra_zh", None),
            "negative": (self.negative_extra, "_negative_extra_en", "_negative_extra_zh", None),
            "activation": (self.tags_edit, "_activation_en", "_activation_zh",
                           self._update_tag_estimate),
        }
        for key, (field, _en, _zh, _callback) in self._auto_fields.items():
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda name=key: self._run_auto_translate(name))
            self._auto_timers[key] = timer
            field.textChanged.connect(lambda name=key: self._schedule_auto_translate(name))

    def _schedule_auto_translate(self, key: str) -> None:
        field, en_attr, zh_attr, _callback = self._auto_fields[key]
        text = field.toPlainText().strip()
        if not text:
            return
        if text == getattr(self, zh_attr) and getattr(self, en_attr):
            return
        self._auto_timers[key].start(350)

    def _translate_activation_now(self) -> None:
        timer = self._auto_timers.get("activation")
        if timer is not None:
            timer.start(0)

    def _run_auto_translate(self, key: str) -> None:
        field, en_attr, zh_attr, _callback = self._auto_fields[key]
        text = field.toPlainText().strip()
        if not text:
            return
        if text == getattr(self, zh_attr) and getattr(self, en_attr):
            return
        model = self._llm()
        if not model:
            return
        if key in self._auto_workers and self._auto_workers[key].isRunning():
            self._auto_pending.add(key)
            return
        worker = AutoTranslateWorker(self.cfg, model, text, self._tag_cache_path)
        worker.done.connect(
            lambda display, english, name=key, source=text:
            self._apply_auto_translate(name, display, english, source))
        worker.failed.connect(lambda msg: self.append_log("自动翻译失败：%s" % msg))
        worker.finished.connect(lambda name=key: self._on_auto_translate_finished(name))
        self._auto_workers[key] = worker
        worker.start()

    def _apply_auto_translate(self, key: str, display: str, english: str,
                              source: str) -> None:
        field, en_attr, zh_attr, callback = self._auto_fields[key]
        if field.toPlainText().strip() != source:
            return
        setattr(self, en_attr, english)
        setattr(self, zh_attr, display)
        if key == "activation":
            self.tags_zh.setPlainText(display)
            if english and re.search(r"[\u4e00-\u9fff]", source):
                field.blockSignals(True)
                try:
                    field.setPlainText(english)
                finally:
                    field.blockSignals(False)
        elif field.toPlainText().strip() != display:
            field.blockSignals(True)
            try:
                field.setPlainText(display)
            finally:
                field.blockSignals(False)
        if callback is not None:
            callback()

    def _on_auto_translate_finished(self, key: str) -> None:
        self._auto_workers.pop(key, None)
        if key in self._auto_pending:
            self._auto_pending.discard(key)
            self._schedule_auto_translate(key)

    def _checked_character_loras(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for row in range(self.lora_table.rowCount()):
            item = self.lora_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                name = item.data(Qt.ItemDataRole.UserRole)
                path = self._lora_paths.get(self._lora_key(name)) or self._resolve_lora_path(name)
                result.append((name, path))
        return result

    def _has_character_lora(self) -> bool:
        return bool(self._checked_character_loras())

    def _lora_info(self, path: str) -> dict:
        info = self._lora_info_cache.get(path)
        if info is None:
            info = lora_tag_info(path, online=False)
            self._lora_info_cache[path] = info
        return info

    @staticmethod
    def _lora_key(name: Any) -> str:
        return str(name or "").replace("/", "\\")

    @staticmethod
    def _combine_tags(lists: list[list[str]]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tags in lists:
            for tag in tags:
                key = str(tag).lower().strip()
                if key and key not in seen:
                    seen.add(key)
                    result.append(str(tag))
        return result

    def _refresh_reference_tags(self) -> None:
        entries = self._checked_character_loras()
        self._reference_tags = self._combine_tags([
            self._lora_info(path)["reference"] for _name, path in entries
        ])
        self.btn_reference.setText("参考标签（%d）" % len(self._reference_tags))
        self.btn_reference.setEnabled(bool(self._reference_tags))

    def _sync_character_tags(self) -> None:
        entries = self._checked_character_loras()
        if not entries:
            self._reference_tags = []
            self.btn_reference.setText("参考标签（0）")
            self.btn_reference.setEnabled(False)
            return
        references: list[list[str]] = []
        sources: set[str] = set()
        pending: list[tuple[str, str]] = []
        for name, path in entries:
            info = self._lora_info(path)
            references.append(info["reference"])
            sources.add(info["source"])
            if (self.cfg.lora.online_lookup and path not in self._online_tried
                    and not info["source"].startswith("safetensors")
                    and Path(path).is_file()):
                pending.append((name, path))

        self._reference_tags = self._combine_tags(references)
        self.btn_reference.setText("参考标签（%d）" % len(self._reference_tags))
        self.btn_reference.setEnabled(bool(self._reference_tags))
        if self._reference_tags:
            self.append_log("参考标签 %d 个（%s）；激活标签保持为空，需手动填写或从参考标签选择" % (
                len(self._reference_tags), "、".join(sorted(sources))))
        else:
            self.append_log("未从 LoRA 元数据提取到参考标签（可手动填写激活标签）")

        if pending and not (self.lora_tags_worker and self.lora_tags_worker.isRunning()):
            for _name, path in pending:
                self._online_tried.add(path)
            worker = LoraTagsWorker(pending, self.cfg.lora.civitai_base or "https://civitai.red")
            worker.done.connect(self._on_lora_tags_done)
            worker.failed.connect(self._on_lora_tags_failed)
            worker.finished.connect(self._on_lora_tags_finished)
            self.lora_tags_worker = worker
            self.append_log("正在访问 Civitai 查询 %d 个 LoRA 的触发词…" % len(pending))
            worker.start()

    def _on_lora_tags_done(self, results: list[tuple[str, str, dict]]) -> None:
        for _name, path, info in results:
            self._lora_info_cache[path] = info
            if info["reference"]:
                self.append_log("Civitai 返回 %d 个参考标签（%s）" % (
                    len(info["reference"]), Path(path).name))
            else:
                self.append_log("Civitai 未找到触发词（%s）" % Path(path).name)
        self._sync_character_tags()

    def _on_lora_tags_failed(self, message: str) -> None:
        self.append_log("Civitai 查询失败：%s" % message)

    def _on_lora_tags_finished(self) -> None:
        self.lora_tags_worker = None
        self._sync_character_tags()

    def open_reference_tags(self) -> None:
        if not self._reference_tags:
            QMessageBox.information(self, "提示", "先勾选角色 LoRA。")
            return
        dialog = TagReferenceDialog(
            self._reference_tags, self, cfg=self.cfg, model=self._llm(),
            cache_path=self._tag_cache_path)
        if dialog.exec():
            selected = dialog.selected_tags()
            combined = append_tags(self._character_tags(), ", ".join(selected))
            self._activation_en = combined
            self._activation_zh = ""
            self.tags_edit.setPlainText(combined)
            self.tags_zh.clear()
            self._translate_activation_now()
            self.append_log("已加入 %d 个参考标签" % len(selected))

    def _populate_detailers(self) -> None:
        checked = {key for key, box, _spin, _choice in self.detailer_rows if box.isChecked()}
        values = {key: spin.value() for key, _box, spin, _choice in self.detailer_rows}
        state = dict(self._detailer_state)
        for key, box, spin, _choice in self.detailer_rows:
            state[key] = {"checked": box.isChecked(), "denoise": spin.value()}
        while self.detailer_box.count():
            item = self.detailer_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.detailer_rows.clear()
        detectors = list(dict.fromkeys([
            *(self.assets.detectors or []),
            *local_detectors(self.cfg.comfy.base_dir),
        ]))
        detectors = filter_detector_models(self.cfg.comfy.base_dir, detectors)
        choices = build_detailer_choices(detectors)
        if choices:
            self.detailer_hint.setText(
                "已扫描到 %d 个检测模型（models/ultralytics，LoRA/embedding 已忽略）" % len(choices))
        else:
            self.detailer_hint.setText(
                "未扫描到检测模型。把模型文件放入 ComfyUI 的 models/ultralytics 后点重新扫描。")
        for choice in choices:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(choice["label"])
            box.setToolTip(choice["detector"])
            saved = state.get(choice["key"], {})
            box.setChecked(bool(saved.get("checked", choice["key"] in checked)))
            layout.addWidget(box, 1)
            layout.addWidget(QLabel("denoise"))
            spin = QDoubleSpinBox()
            spin.setRange(0.05, 0.9)
            spin.setSingleStep(0.05)
            spin.setValue(float(saved.get("denoise", values.get(
                choice["key"], choice["denoise"]))))
            layout.addWidget(spin)
            self.detailer_box.addWidget(row)
            self.detailer_rows.append((choice["key"], box, spin, choice))
            state[choice["key"]] = {"checked": box.isChecked(), "denoise": spin.value()}
        self._detailer_state = state

    def refresh_assets(self) -> None:
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI。")
            return
        if self.assets_worker and self.assets_worker.isRunning():
            return
        self.btn_scan_assets.setEnabled(False)
        self.statusBar().showMessage("正在重新扫描模型…")
        worker = AssetsWorker(self.cfg)
        worker.done.connect(self._on_assets_refreshed)
        worker.failed.connect(self._on_assets_failed)
        worker.finished.connect(lambda: self.btn_scan_assets.setEnabled(True))
        self.assets_worker = worker
        worker.start()

    def _on_assets_refreshed(self, assets: Assets) -> None:
        self.assets = assets
        self._populate_from_assets(self.ollama_models)
        self.append_log("模型列表已刷新：检测器 %d 个" % len(assets.detectors))
        self.statusBar().showMessage("模型列表已刷新")

    def _on_assets_failed(self, message: str) -> None:
        self.append_log("刷新模型失败：%s" % message)
        self.statusBar().showMessage("刷新模型失败")

    # ---------------------------------------------------------------- template / project

    def _single_fields(self) -> dict[str, str]:
        return {
            "role": self.single_role.toPlainText().strip(),
            "clothing": self.single_clothing.toPlainText().strip(),
            "scene": self.single_scene.text().strip(),
            "plot": self.single_desc.toPlainText().strip(),
            "extra": self.single_extra.toPlainText().strip(),
        }

    def _single_input_text(self) -> str:
        fields = self._single_fields()
        parts: list[str] = []
        if fields["role"]:
            parts.append("角色标签：%s" % fields["role"])
        if fields["clothing"]:
            parts.append("初始服装：%s" % fields["clothing"])
        if fields["scene"]:
            parts.append("大场景：%s" % fields["scene"])
        if fields["plot"]:
            parts.append("画面：%s" % fields["plot"])
        if fields["extra"]:
            parts.append("其它：%s" % fields["extra"])
        return "\n".join(parts)

    def _set_single_fields(self, fields: dict[str, Any]) -> None:
        self.single_role.setPlainText(str(fields.get("role", "")))
        self.single_clothing.setPlainText(str(fields.get("clothing", "")))
        self.single_scene.setText(str(fields.get("scene", "")))
        self.single_desc.setPlainText(str(fields.get("plot", "")))
        self.single_extra.setPlainText(str(fields.get("extra", "")))

    def _story_fields(self) -> dict[str, str]:
        return {
            "role": self.story_role.toPlainText().strip(),
            "clothing": self.story_clothing.toPlainText().strip(),
            "scene": self.story_scene.text().strip(),
            "plot": self.story_premise.toPlainText().strip(),
            "extra": self.story_extra.toPlainText().strip(),
        }

    def _story_premise_text(self) -> str:
        fields = self._story_fields()
        parts: list[str] = []
        if fields["role"]:
            parts.append("角色：%s" % fields["role"])
        if fields["clothing"]:
            parts.append("初始服装：%s" % fields["clothing"])
        if fields["scene"]:
            parts.append("大场景：%s" % fields["scene"])
        if fields["plot"]:
            parts.append("剧情：\n%s" % fields["plot"])
        if fields["extra"]:
            parts.append("其它：%s" % fields["extra"])
        return "\n".join(parts)

    @staticmethod
    def _parse_story_text(text: str) -> dict[str, str]:
        fields = {"role": "", "clothing": "", "scene": "", "plot": "", "extra": ""}
        aliases = (
            ("初始服装标签", "clothing"), ("初始服装", "clothing"),
            ("初始装扮", "clothing"), ("服装", "clothing"),
            ("大场景", "scene"), ("场景", "scene"),
            ("角色设定", "role"), ("角色标签", "role"), ("角色", "role"),
            ("人物设定", "role"), ("人物", "role"),
            ("剧情", "plot"), ("画面", "plot"),
            ("其它", "extra"), ("其他", "extra"), ("额外", "extra"),
        )
        current = "plot"
        found = False
        for line in str(text or "").splitlines():
            stripped = line.strip()
            matched = None
            for prefix, key in aliases:
                if not stripped.startswith(prefix):
                    continue
                remainder = stripped[len(prefix):]
                if remainder and remainder[0] not in "：: ":
                    continue
                rest = remainder.lstrip("：:").strip()
                matched = (key, rest)
                break
            if matched:
                current = matched[0]
                found = True
                if matched[1]:
                    fields[current] = matched[1]
            else:
                fields[current] = (fields[current] + "\n" + line).strip()
        if not found:
            fields["plot"] = str(text or "").strip()
        return fields

    def _set_story_fields(self, fields: dict[str, Any]) -> None:
        self.story_role.setPlainText(str(fields.get("role", "")))
        self.story_clothing.setPlainText(str(fields.get("clothing", "")))
        self.story_scene.setText(str(fields.get("scene", "")))
        self.story_premise.setPlainText(str(fields.get("plot", "")))
        self.story_extra.setPlainText(str(fields.get("extra", "")))

    def _style_positive(self) -> str:
        return (self.template.get("style") or {}).get("positive", "")

    def _character_tags(self) -> str:
        text = self.tags_edit.toPlainText().strip()
        if not text:
            return ""
        if text == self._activation_en and self._activation_en:
            return text
        if text == self._activation_zh and self._activation_en:
            return self._activation_en
        if re.search(r"[\u4e00-\u9fff]", text):
            resolved = self._resolve_chinese_texts([text])
            english = resolved[0] if resolved and resolved[0] else ""
            if english:
                self._activation_en = english
                self._activation_zh = text
                return english
        return text

    def _has_activation_tags(self) -> bool:
        return bool(self._character_tags())

    def _activation_tags(self) -> list[str]:
        return [tag.strip() for tag in self._character_tags().split(",") if tag.strip()]

    def _body_activation_tags(self) -> list[str]:
        groups: list[list[str]] = []
        for lora in self._selected_loras(self.body_lora_table):
            path = self._lora_paths.get(self._lora_key(lora["name"])) or self._resolve_lora_path(lora["name"])
            groups.append(self._lora_info(path).get("triggers", []))
        return self._combine_tags(groups)

    def _action_activation_tags(self) -> list[str]:
        groups: list[list[str]] = []
        for lora in self._selected_loras(self.action_lora_table):
            path = self._lora_paths.get(self._lora_key(lora["name"])) or self._resolve_lora_path(lora["name"])
            groups.append(self._lora_info(path).get("triggers", []))
        return self._combine_tags(groups)

    def _clothing_activation_tags(self) -> list[str]:
        groups: list[list[str]] = []
        for lora in self._selected_loras(self.clothing_lora_table):
            path = self._lora_paths.get(self._lora_key(lora["name"])) or self._resolve_lora_path(lora["name"])
            groups.append(self._lora_info(path).get("triggers", []))
        return self._combine_tags(groups)

    def _style_activation_tags(self) -> list[str]:
        groups: list[list[str]] = []
        for lora in self._selected_loras(self.style_lora_table):
            path = self._lora_paths.get(self._lora_key(lora["name"])) or self._resolve_lora_path(lora["name"])
            groups.append(self._lora_info(path).get("triggers", []))
        return self._combine_tags(groups)

    def _resolve_chinese_texts(self, texts: list[str]) -> list[str]:
        cache = load_tag_cache(self._tag_cache_path)
        reverse: dict[str, str] = {}
        for english, chinese in cache.items():
            if chinese and chinese not in reverse:
                reverse[chinese] = english
        rows: list[list[str]] = []
        unknown: set[str] = set()
        for text in texts:
            tokens = [token.strip() for token in re.split(r"[,，、]", text or "") if token.strip()]
            rows.append(tokens)
            for token in tokens:
                if token in reverse:
                    continue
                if any("\u4e00" <= char <= "\u9fff" for char in token):
                    unknown.add(token)
        unknown_map: dict[str, str] = {}
        model = self._llm()
        if unknown and model:
            client = OllamaClient(self.cfg.ollama.base_url)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                values = translate_to_tags(client, model, sorted(unknown), batch_size=1)
                for token, english in zip(sorted(unknown), values):
                    if english:
                        unknown_map[token] = english
            except Exception as exc:
                self.append_log("中文转英文标签失败：%s" % exc)
            finally:
                QApplication.restoreOverrideCursor()
                try:
                    client.unload(model)
                except Exception:
                    pass
        result: list[str] = []
        for tokens in rows:
            parts = []
            for token in tokens:
                parts.append(reverse.get(token) or unknown_map.get(token) or token)
            result.append(", ".join(parts))
        return result

    def _resolve_single_en(self) -> str:
        text = self.single_prompt.toPlainText().strip()
        if not text:
            self._update_single_prompt_stats()
            return ""
        if text == self._single_prompt_zh and self._single_prompt_en:
            self._update_single_prompt_stats()
            return self._single_prompt_en
        resolved = self._resolve_chinese_texts([text])
        if resolved and resolved[0]:
            self._single_prompt_en = resolved[0]
            self._single_prompt_zh = text
            self._update_single_prompt_stats()
            return resolved[0]
        self._update_single_prompt_stats()
        return self._single_prompt_en or text

    def _build_style(self) -> dict[str, Any]:
        style = copy.deepcopy(self.template.get("style") or {})
        extra_pos_zh = self.positive_extra.toPlainText().strip()
        extra_neg_zh = self.negative_extra.toPlainText().strip()
        extra_pos = extra_pos_zh
        extra_neg = extra_neg_zh
        if extra_pos_zh and extra_pos_zh != self._positive_extra_zh:
            resolved = self._resolve_chinese_texts([extra_pos_zh])
            extra_pos = (resolved[0] if resolved and resolved[0] else self._positive_extra_en)
            self._positive_extra_en = extra_pos
            self._positive_extra_zh = extra_pos_zh
        elif extra_pos_zh:
            extra_pos = self._positive_extra_en
        if extra_neg_zh and extra_neg_zh != self._negative_extra_zh:
            resolved = self._resolve_chinese_texts([extra_neg_zh])
            extra_neg = (resolved[0] if resolved and resolved[0] else self._negative_extra_en)
            self._negative_extra_en = extra_neg
            self._negative_extra_zh = extra_neg_zh
        elif extra_neg_zh:
            extra_neg = self._negative_extra_en
        if extra_pos:
            style["positive"] = append_tags(style.get("positive", ""), extra_pos)
        if extra_neg:
            style["negative"] = append_tags(style.get("negative", ""), extra_neg)
        return style

    def _selected_loras(self, table: QTableWidget) -> list[dict[str, Any]]:
        result = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            spin = table.cellWidget(row, 1)
            if item and spin and item.checkState() == Qt.CheckState.Checked:
                result.append({"name": item.data(Qt.ItemDataRole.UserRole), "strength": spin.value()})
        return result

    def _build_loras(self) -> list[dict[str, Any]]:
        result = (self._selected_loras(self.lora_table)
                  + self._selected_loras(self.style_lora_table))
        for table, scope in ((self.body_lora_table, "body"),
                             (self.action_lora_table, "action"),
                             (self.clothing_lora_table, "clothing")):
            items = self._selected_loras(table)
            for item in items:
                path = (self._lora_paths.get(self._lora_key(item["name"]))
                        or self._resolve_lora_path(item["name"]))
                info = self._lora_info(path)
                item["scope"] = scope
                item["triggers"] = list(info.get("triggers", []))
                if scope in ("action", "clothing"):
                    item["reference"] = list(info.get("reference", []))[:160]
            result.extend(items)
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
            "img2img": {
                "enabled": self.img2img_check.isChecked(),
                "denoise": self.img2img_denoise.value(),
            },
        }

    def _build_project(self, mode: str, shots: list[dict[str, Any]], text: str) -> dict[str, Any]:
        data = copy.deepcopy(self.template)
        data["model"] = self.ckpt_combo.currentValue() or self.template.get("model", "")
        data["clip_skip"] = self.clip_skip.value()
        data["loras"] = self._build_loras()
        data.pop("lora", None)
        data["character"] = copy.deepcopy(self.template.get("character") or {})
        if mode == "story":
            data["character"]["tags"] = (
                self.story_role.toPlainText().strip() or self._character_tags())
        else:
            data["character"]["tags"] = (
                self.single_role.toPlainText().strip() or self._character_tags())
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
        data["style"]["lora_tags"] = ", ".join(self._style_activation_tags())
        data["body"] = {"tags": ", ".join(self._body_activation_tags())}
        data["action"] = {"tags": ", ".join(self._action_activation_tags())}
        data["clothing"] = {"tags": ", ".join(self._clothing_activation_tags())}
        data["story_fields"] = self._story_fields()
        data["single_fields"] = self._single_fields()
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

    def generate_single(self, then_render: bool = False,
                        external: bool = False) -> None:
        if self.prompt_worker and self.prompt_worker.isRunning():
            return
        text = self._single_input_text()
        if not text:
            QMessageBox.information(self, "提示", "请先输入角色标签、画面或场景。")
            return
        if external:
            if not (self.cfg.external_llm.base_url and self.cfg.external_llm.model):
                QMessageBox.information(
                    self, "提示", "请先在设置里填写外部 API 的 Base URL 和模型。")
                return
        else:
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
            setting="",
            character_tags=(self.single_role.toPlainText().strip()
                            or self._character_tags()),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora(),
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "single", text, single_options=options,
                              use_external=external)
        worker.single_ready.connect(self._on_single_prompt)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在生成单图提示词…")
        worker.start()

    def _on_single_prompt(self, result: dict[str, str]) -> None:
        prompt = result.get("prompt", "")
        prompt_zh = result.get("prompt_zh", "")
        self._single_prompt_en = prompt
        self._single_prompt_zh = prompt_zh or prompt
        self.single_prompt.setPlainText(self._single_prompt_zh)
        self._update_single_prompt_stats()
        self.btn_single_prompt.setText("① 重新生成提示词")
        self.btn_expand.setEnabled(True)
        self.append_log("单图提示词（中文）：%s" % self._single_prompt_zh)
        self.statusBar().showMessage("提示词已生成，可编辑后出图")
        if self._render_after_prompt:
            self._render_after_prompt = False
            self.start_render("single")

    def _write_story_partial(self, premise: str, shots: list[dict[str, Any]],
                             total: int, external: bool) -> None:
        try:
            save_story_partial({
                "premise": premise, "shots": shots,
                "total": int(total), "external": bool(external),
            }, self.cfg.root)
        except Exception:
            pass

    def _update_partial_button(self) -> None:
        data = load_story_partial(self.cfg.root)
        shots = data.get("shots") or []
        self.btn_restore_partial.setEnabled(bool(shots))
        self.btn_restore_partial.setText(
            "恢复上次未完成分镜（%d）" % len(shots) if shots
            else "恢复上次未完成分镜")
        self.btn_continue_partial.setEnabled(bool(shots))
        self.btn_continue_partial.setText(
            "继续未完成分镜（%d）" % len(shots) if shots
            else "继续未完成分镜")

    def restore_partial_story(self) -> None:
        data = load_story_partial(self.cfg.root)
        shots = data.get("shots") or []
        if not shots:
            QMessageBox.information(self, "提示", "没有可恢复的未完成分镜。")
            self._update_partial_button()
            return
        if self.shot_table.rowCount():
            answer = QMessageBox.question(
                self, "恢复未完成分镜", "用上次未完成的 %d 镜替换当前分镜？" % len(shots))
            if answer != QMessageBox.StandardButton.Yes:
                return
        premise = str(data.get("premise") or "")
        if premise:
            self._set_story_fields(self._parse_story_text(premise))
        self._fill_shot_table(shots)
        self.btn_mode_story.setChecked(True)
        self.btn_mode_single.setChecked(False)
        self._switch_mode(1)
        self.append_log("已恢复上次未完成分镜：%d 镜" % len(shots))
        self.statusBar().showMessage("已恢复 %d 镜，可继续检查或出图" % len(shots))

    def continue_partial_story(self) -> None:
        data = load_story_partial(self.cfg.root)
        shots = data.get("shots") or []
        if not shots:
            QMessageBox.information(self, "提示", "没有可继续的未完成分镜。")
            self._update_partial_button()
            return
        premise = str(data.get("premise") or "")
        total = int(data.get("total") or max(len(shots), self.story_shots.value()))
        if premise:
            self._set_story_fields(self._parse_story_text(premise))
        self.story_shots.setValue(total)
        self.btn_mode_story.setChecked(True)
        self.btn_mode_single.setChecked(False)
        self._switch_mode(1)
        external = bool(data.get(
            "external", bool(self.cfg.external_llm.base_url and self.cfg.external_llm.model)))
        self.generate_story(external=external, initial_shots=shots)

    def generate_story(self, external: bool = False,
                       initial_shots: list[dict[str, Any]] | None = None) -> None:
        if self.prompt_worker and self.prompt_worker.isRunning():
            return
        text = self._story_premise_text()
        if not text:
            QMessageBox.information(self, "提示", "请先输入角色、剧情或场景。")
            return
        if external:
            if not (self.cfg.external_llm.base_url and self.cfg.external_llm.model):
                QMessageBox.information(
                    self, "提示", "请先在设置里填写外部 API 的 Base URL 和模型。")
                return
        else:
            if not self.connected:
                QMessageBox.information(self, "提示", "请先连接 ComfyUI / Ollama。")
                return
            if not self._llm():
                QMessageBox.information(self, "提示", "没有可用的 Ollama 模型，请先在设置/模型页选择。")
                return
        total = int(self.story_shots.value())
        options = StoryboardOptions(
            model=self._llm(), shots=total,
            chunk=2 if external else 3,
            setting="",
            character_tags=self._character_tags(),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora(),
            full_story=True,
            on_partial=lambda shots: self._write_story_partial(
                text, shots, total, external),
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "story", text, story_options=options,
                              initial_shots=initial_shots,
                              use_external=external)
        worker.story_ready.connect(self._on_story_ready)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在生成分镜…")
        worker.start()

    def _on_story_ready(self, shots: list[dict[str, str]]) -> None:
        clear_story_partial(self.cfg.root)
        self._update_partial_button()
        self._fill_shot_table(shots)
        self.append_log("分镜已生成：%d 镜" % len(shots))
        self.statusBar().showMessage("分镜已生成（共 %d 镜）" % len(shots))
        self._autosave_generated_story()

    def _autosave_generated_story(self) -> None:
        if not self.shot_table.rowCount():
            return
        try:
            text = self._story_premise_text() or self._current_text()
            shots = self._collect_shots(False)
            if not shots:
                return
            project = self._build_project("story", shots, text)
            self._reuse_project_identity(project)
            self.project = project
            path = save_project(project, self.cfg.root)
            self.append_log("已自动保存分镜项目：%s" % path)
        except Exception as exc:
            self.append_log("分镜自动保存失败：%s" % exc)

    def _set_shot_row(self, row: int, shot: dict[str, Any], locked: bool = False) -> None:
        self._syncing_shots = True
        try:
            lock_item = QTableWidgetItem("")
            lock_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            lock_item.setCheckState(Qt.CheckState.Checked if (locked or shot.get("locked")) else Qt.CheckState.Unchecked)
            lock_item.setToolTip("锁定后重新生成分镜时会保留此镜")
            self.shot_table.setItem(row, 0, lock_item)
            self.shot_table.setItem(row, 1, QTableWidgetItem(str(shot.get("id", "%02d" % (row + 1)))))
            self.shot_table.setItem(row, 2, QTableWidgetItem(str(shot.get("name", ""))))
            prompt = str(shot.get("prompt", ""))
            prompt_zh = str(shot.get("prompt_zh") or prompt)
            prompt_item = QTableWidgetItem(prompt_zh)
            prompt_item.setData(PROMPT_EN_ROLE, prompt)
            prompt_item.setData(PROMPT_ZH_ROLE, prompt_zh)
            prompt_item.setData(OUTLINE_ROLE, str(shot.get("outline", "")))
            prompt_item.setData(CAST_ROLE, str(shot.get("cast", "")))
            prompt_item.setData(SCRIPT_ROLE, str(shot.get("script", "")))
            prompt_item.setData(PHASE_ROLE, str(shot.get("phase", "")))
            prompt_item.setData(CLOTHING_ROLE, str(shot.get("clothing", "")))
            prompt_item.setData(CHARACTERS_ROLE, str(shot.get("characters", "")))
            states = shot.get("character_states") or {}
            if isinstance(states, str):
                try:
                    states = json.loads(states)
                except (TypeError, ValueError):
                    states = {}
            prompt_item.setData(CHARACTER_STATES_ROLE, json.dumps(
                states, ensure_ascii=False))
            prompt_item.setData(SCENE_ROLE, str(shot.get("scene", "")))
            self.shot_table.setItem(row, 3, prompt_item)
        finally:
            self._syncing_shots = False

    def _fill_shot_table(self, shots: list[dict[str, Any]]) -> None:
        self.shot_table.setRowCount(0)
        for shot in shots:
            row = self.shot_table.rowCount()
            self.shot_table.insertRow(row)
            self._set_shot_row(row, shot)
        if self.shot_table.rowCount():
            self.shot_table.setCurrentCell(0, 3)
        self._update_shot_stats()

    def _row_data(self, row: int) -> dict[str, Any]:
        lock_item = self.shot_table.item(row, 0)
        prompt_item = self.shot_table.item(row, 3)
        states: dict[str, Any] = {}
        if prompt_item:
            raw_states = prompt_item.data(CHARACTER_STATES_ROLE)
            if isinstance(raw_states, str) and raw_states.strip():
                try:
                    parsed = json.loads(raw_states)
                    states = parsed if isinstance(parsed, dict) else {}
                except (TypeError, ValueError):
                    states = {}
        return {
            "locked": bool(lock_item and lock_item.checkState() == Qt.CheckState.Checked),
            "id": self.shot_table.item(row, 1).text() if self.shot_table.item(row, 1) else "",
            "name": self.shot_table.item(row, 2).text() if self.shot_table.item(row, 2) else "",
            "prompt": prompt_item.text() if prompt_item else "",
            "prompt_en": (prompt_item.data(PROMPT_EN_ROLE) or "") if prompt_item else "",
            "prompt_zh": (prompt_item.data(PROMPT_ZH_ROLE) or "") if prompt_item else "",
            "outline": (prompt_item.data(OUTLINE_ROLE) or "") if prompt_item else "",
            "cast": (prompt_item.data(CAST_ROLE) or "") if prompt_item else "",
            "script": (prompt_item.data(SCRIPT_ROLE) or "") if prompt_item else "",
            "phase": (prompt_item.data(PHASE_ROLE) or "") if prompt_item else "",
            "clothing": (prompt_item.data(CLOTHING_ROLE) or "") if prompt_item else "",
            "characters": (prompt_item.data(CHARACTERS_ROLE) or "") if prompt_item else "",
            "character_states": states,
            "scene": (prompt_item.data(SCENE_ROLE) or "") if prompt_item else "",
        }

    def _on_shot_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_shots or item.column() != 3:
            return
        self._update_shot_stats()

    def _update_shot_stats(self) -> None:
        total_tags = 0
        total_tokens = 0
        dirty = False
        for row in range(self.shot_table.rowCount()):
            data = self._row_data(row)
            display = data["prompt"].strip()
            prompt_zh = data.get("prompt_zh", "").strip()
            prompt_en = data.get("prompt_en", "").strip()
            if display and display != prompt_zh:
                dirty = True
            if prompt_en:
                tags = [tag.strip() for tag in prompt_en.split(",") if tag.strip()]
                total_tags += len(tags)
                total_tokens += estimate_tokens(tags)
        suffix = " · 含修改待映射" if dirty else ""
        self.shot_stats.setText("%d 镜 · %d 英文标签 · 约 %d tokens%s" % (
            self.shot_table.rowCount(), total_tags, total_tokens, suffix))

    def show_shot_details(self) -> None:
        if not self.shot_table.rowCount():
            QMessageBox.information(self, "提示", "还没有分镜。")
            return
        premise = self._story_premise_text()
        outlines = extract_premise_beats(premise)
        rows: list[int] = []
        data: list[dict[str, Any]] = []
        row_outlines: list[str] = []
        for index, row in enumerate(range(self.shot_table.rowCount())):
            item = self._row_data(row)
            rows.append(row)
            outline = item.get("outline", "") or (
                outlines[index] if index < len(outlines) else "")
            row_outlines.append(outline)
            data.append({
                "id": item["id"],
                "name": item["name"],
                "prompt": item["prompt_en"] or item["prompt"] or "",
                "prompt_zh": item["prompt_zh"] or item["prompt"] or "",
            })
        dialog = ShotDetailsDialog(data, row_outlines, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.updated_shots()
        changed: list[tuple[int, str]] = []
        self._syncing_shots = True
        try:
            for row, shot in zip(rows, updated):
                id_item = self.shot_table.item(row, 1)
                name_item = self.shot_table.item(row, 2)
                if id_item:
                    id_item.setText(str(shot.get("id", "")))
                if name_item:
                    name_item.setText(str(shot.get("name", "")))
                prompt_item = self.shot_table.item(row, 3)
                if not prompt_item:
                    continue
                old_en = str(prompt_item.data(PROMPT_EN_ROLE) or "")
                new_en = str(shot.get("prompt", ""))
                if new_en and new_en != old_en:
                    prompt_item.setData(PROMPT_EN_ROLE, new_en)
                    changed.append((row, new_en))
        finally:
            self._syncing_shots = False
        self._update_shot_stats()
        if changed:
            self._translate_changed_shot_prompts(changed)
        else:
            self.append_log("分镜详情已更新")
        self.statusBar().showMessage("分镜详情已保存")

    def export_shots_json(self) -> None:
        if not self.shot_table.rowCount():
            QMessageBox.information(self, "提示", "还没有分镜。")
            return
        output_dir = Path(self.cfg.comfy.output_dir)
        default = output_dir / ("storyboard_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分镜 JSON", str(default), "JSON (*.json)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".json")
        shots: list[dict[str, Any]] = []
        for row in range(self.shot_table.rowCount()):
            item = self._row_data(row)
            shots.append({
                "id": item["id"],
                "name": item["name"],
                "prompt": item["prompt_en"] or item["prompt"] or "",
                "prompt_zh": item["prompt_zh"] or item["prompt"] or "",
                "outline": item.get("outline", ""),
                "cast": item.get("cast", ""),
            })
        premise = self._story_premise_text() or self._single_input_text()
        payload = {"version": 1, "premise": premise, "shots": shots}
        try:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.append_log("已导出 %d 个分镜：%s" % (len(shots), target))
        self.statusBar().showMessage("分镜 JSON 已导出")

    def import_shots_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入分镜 JSON（自动识别格式）", str(Path(self.cfg.comfy.output_dir)),
            "JSON (*.json)")
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            shots = shots_from_json(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入失败", "无法读取分镜 JSON：\n%s" % exc)
            return
        premise = premise_from_json(raw)
        if self.shot_table.rowCount() or (premise and premise != self._story_premise_text()):
            answer = QMessageBox.question(
                self, "替换分镜",
                "用导入的 %d 个分镜替换当前全部分镜%s？" % (
                    len(shots), "，并更新剧情前提" if premise else ""))
            if answer != QMessageBox.StandardButton.Yes:
                return
        if premise:
            self._set_story_fields(self._parse_story_text(premise))
        self._fill_shot_table(shots)
        self.append_log("已导入 %d 个分镜：%s" % (len(shots), path))
        self.statusBar().showMessage("分镜 JSON 已导入并替换")

    def _translate_changed_shot_prompts(self, changes: list[tuple[int, str]]) -> None:
        model = self._llm()
        if not model:
            self.append_log("英文提示词已更新；没有可用 Ollama 模型，中文提示词未更新")
            return
        tags: list[str] = []
        for _row, prompt in changes:
            tags.extend(tag.strip() for tag in prompt.split(",") if tag.strip())
        worker = TagTranslateWorker(self.cfg, model, tags, self._tag_cache_path)
        worker.done.connect(
            lambda mapping: self._apply_changed_shot_translations(changes, mapping))
        worker.failed.connect(
            lambda message: self.append_log("分镜详情中文翻译失败：%s" % message))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "_details_translate_worker", None))
        self._details_translate_worker = worker
        worker.start()

    def _apply_changed_shot_translations(self, changes: list[tuple[int, str]],
                                         mapping: dict[str, str]) -> None:
        self._syncing_shots = True
        try:
            for row, prompt in changes:
                if not (0 <= row < self.shot_table.rowCount()):
                    continue
                item = self.shot_table.item(row, 3)
                if not item:
                    continue
                tags = [tag.strip() for tag in prompt.split(",") if tag.strip()]
                zh = "，".join(mapping.get(tag, tag) for tag in tags)
                item.setText(zh)
                item.setData(PROMPT_ZH_ROLE, zh)
        finally:
            self._syncing_shots = False
        self._update_shot_stats()

    def _locked_rows(self) -> list[tuple[int, dict[str, Any]]]:
        result = []
        for row in range(self.shot_table.rowCount()):
            data = self._row_data(row)
            if data["locked"]:
                result.append((row, data))
        return result

    def select_all_shots(self) -> None:
        if self.shot_table.rowCount():
            self.shot_table.selectAll()
            self.shot_table.setFocus()

    def clear_shot_rows(self) -> None:
        count = self.shot_table.rowCount()
        if not count:
            return
        answer = QMessageBox.question(
            self, "删除全部分镜", "确定删除全部 %d 个分镜？" % count)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.shot_table.setRowCount(0)
        self._update_shot_stats()
        self.append_log("已删除全部分镜")
        self.statusBar().showMessage("已删除全部分镜")

    def add_shot_row(self) -> None:
        row = self.shot_table.rowCount()
        self.shot_table.insertRow(row)
        self._set_shot_row(row, {"id": "%02d" % (row + 1), "name": "shot_%02d" % (row + 1), "prompt": ""})
        self.shot_table.selectRow(row)
        self.shot_table.editItem(self.shot_table.item(row, 3))
        self._update_shot_stats()

    def remove_shot_row(self) -> None:
        rows = sorted({index.row() for index in self.shot_table.selectedIndexes()}, reverse=True)
        if not rows and self.shot_table.currentRow() >= 0:
            rows = [self.shot_table.currentRow()]
        for row in rows:
            self.shot_table.removeRow(row)
        self._renumber_shots()
        self._update_shot_stats()

    def move_shot(self, delta: int) -> None:
        row = self.shot_table.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.shot_table.rowCount()):
            return
        first = self._row_data(row)
        second = self._row_data(target)
        self._set_shot_row(row, second, locked=second["locked"])
        self._set_shot_row(target, first, locked=first["locked"])
        self.shot_table.selectRow(target)

    def _renumber_shots(self) -> None:
        for row in range(self.shot_table.rowCount()):
            item = self.shot_table.item(row, 1)
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
        prompt = self._resolve_single_en()
        initial = [{"id": "01", "name": slugify(prompt, "single") or "single",
                    "prompt": prompt,
                    "prompt_zh": self.single_prompt.toPlainText().strip() or prompt}]
        options = StoryboardOptions(
            model=self._llm(), shots=total, chunk=3,
            setting="",
            character_tags=(self.single_role.toPlainText().strip()
                            or self._character_tags()),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora(),
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "expand", self._single_input_text() or prompt,
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
        self._autosave_generated_story()

    def _on_prompt_failed(self, message: str) -> None:
        self._render_after_prompt = False
        self._update_partial_button()
        self.append_log("生成提示词失败：%s" % message)
        self.statusBar().showMessage("生成失败（可点“恢复上次未完成分镜”）")
        QMessageBox.warning(self, "生成失败", message)

    def _on_prompt_worker_finished(self) -> None:
        if not (self.render_worker and self.render_worker.isRunning()):
            self._set_generation_enabled(True)

    # ---------------------------------------------------------------- rendering

    def render_single_clicked(self) -> None:
        if not self.single_prompt.toPlainText().strip():
            if self._single_input_text():
                self.generate_single(then_render=True)
                return
            if self._has_activation_tags():
                self.start_render("single")
                return
            self.generate_single(then_render=True)
            return
        self.start_render("single")

    def _collect_shots(self, selected_only: bool, allow_empty: bool = False) -> list[dict[str, Any]]:
        rows = sorted({index.row() for index in self.shot_table.selectedIndexes()}) \
            if selected_only else list(range(self.shot_table.rowCount()))
        shots: list[dict[str, Any]] = []
        pending: list[tuple[int, int, str, str]] = []
        for row in rows:
            data = self._row_data(row)
            display = data["prompt"].strip()
            if not display and not allow_empty:
                continue
            index = len(shots)
            if not display:
                shots.append({"id": data["id"].strip() or "%02d" % (index + 1),
                              "name": data["name"].strip() or "shot_%02d" % (index + 1),
                              "prompt": "",
                              "prompt_zh": "",
                              "outline": data.get("outline", ""),
                              "cast": data.get("cast", ""),
                              "script": data.get("script", ""),
                              "phase": data.get("phase", ""),
                              "clothing": data.get("clothing", ""),
                              "characters": data.get("characters", ""),
                              "character_states": data.get("character_states") or {},
                              "scene": data.get("scene", ""),
                              "locked": data["locked"]})
                continue
            prompt_en = data.get("prompt_en", "").strip()
            prompt_zh = data.get("prompt_zh", "").strip()
            resolved = prompt_en if display == prompt_zh and prompt_en else ""
            if not resolved:
                pending.append((row, index, display, prompt_en))
            shots.append({"id": data["id"].strip() or "%02d" % (index + 1),
                          "name": data["name"].strip() or "shot_%02d" % (index + 1),
                          "prompt": resolved,
                          "prompt_zh": display,
                          "outline": data.get("outline", ""),
                          "cast": data.get("cast", ""),
                          "script": data.get("script", ""),
                          "phase": data.get("phase", ""),
                          "clothing": data.get("clothing", ""),
                          "characters": data.get("characters", ""),
                          "character_states": data.get("character_states") or {},
                          "scene": data.get("scene", ""),
                          "locked": data["locked"]})
        if pending:
            translations = self._resolve_chinese_texts([item[2] for item in pending])
            for (row, index, display, fallback), resolved in zip(pending, translations):
                text = resolved or fallback or display
                shots[index]["prompt"] = text
                item = self.shot_table.item(row, 3)
                if item:
                    self._syncing_shots = True
                    try:
                        item.setData(PROMPT_EN_ROLE, text)
                        item.setData(PROMPT_ZH_ROLE, display)
                    finally:
                        self._syncing_shots = False
        self._update_shot_stats()
        return shots

    def _run_prefix_for(self, mode: str, text: str) -> str:
        signature = "%s\n%s" % (mode, text.strip())
        if not self._run_prefix or signature != self._run_signature:
            run_id = "task_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4])
            self._run_prefix = "anime_story/" + run_id
            self._run_signature = signature
        return self._run_prefix

    def start_render(self, mode: str) -> None:
        if self.render_worker and self.render_worker.isRunning():
            return
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI。")
            return
        activation = self._has_activation_tags()
        if mode == "single":
            prompt_zh = self.single_prompt.toPlainText().strip()
            prompt = self._resolve_single_en()
            if not prompt and not activation:
                QMessageBox.information(self, "提示", "请先生成或填写提示词，或先填写激活标签。")
                return
            shots = [{"id": "01", "name": slugify(prompt, "single") or "activation",
                      "prompt": prompt, "prompt_zh": prompt_zh or prompt}]
            text = self._single_input_text() or prompt_zh or prompt or "activation"
        else:
            shots = self._collect_shots(self.chk_selected.isChecked(), allow_empty=activation)
            if not shots and activation:
                shots = [{"id": "01", "name": "activation", "prompt": "", "prompt_zh": ""}]
            if not shots:
                QMessageBox.information(self, "提示", "没有可生成的镜头，请先生成或填写分镜。")
                return
            text = self._story_premise_text() or shots[0]["prompt"] or "activation"

        project = self._build_project(mode, shots, text)
        self._reuse_project_identity(project)
        prefix = self._run_prefix_for(mode, text)
        project["prefix"] = prefix
        self.project = project
        output_dir = self.cfg.comfy.output_dir.strip()
        if output_dir:
            folder = Path(output_dir) / Path(prefix)
            folder.mkdir(parents=True, exist_ok=True)
            self.append_log("本轮图片目录：%s" % folder)
        save_project(self.project, self.cfg.root)
        self.append_log("项目已保存：%s" % self.project["id"])
        char_tags = (self.project.get("character") or {}).get("tags", "")
        if char_tags:
            self.append_log("本次生成携带角色标签 %d 个：%s" % (
                len([tag for tag in char_tags.split(",") if tag.strip()]), char_tags[:240]))
        settings = self.project["settings"]
        seed_mode = settings.get("seed_mode", "increment")
        base_seed = int(settings.get("base_seed", 1))
        img2img = settings.get("img2img") or {}
        tasks = build_tasks(self.project, shots, int(self.project["variants"]),
                            seed_mode, base_seed, auto_bridges=bool(img2img.get("enabled")))
        if seed_mode == "increment" and tasks:
            next_seed = (base_seed + len(tasks)) % (2 ** 31)
            self.seed_spin.setValue(next_seed)
            self.append_log("抽卡：本轮种子 %d..%d，下次从 %d 开始" % (
                tasks[0].seed, tasks[-1].seed, next_seed))
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
        item.setData(Qt.ItemDataRole.UserRole + 1, task.id)
        self.gallery.addItem(item)

    def _open_gallery_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():
            os.startfile(str(Path(path).parent))  # noqa: S606
            os.startfile(path)  # noqa: S606
        else:
            QMessageBox.information(self, "提示", "找不到图片文件。")

    # ---------------------------------------------------------------- M2: project / trash / compare

    def _current_mode(self) -> str:
        return "single" if self.left_stack.currentIndex() == 0 else "story"

    def _current_text(self) -> str:
        if self._current_mode() == "single":
            return self._single_input_text() or self.single_prompt.toPlainText().strip()
        return self._story_premise_text()

    def _reuse_project_identity(self, project: dict[str, Any]) -> None:
        if self.project and self.project.get("id") and self.project.get("mode") == project.get("mode"):
            project["id"] = self.project["id"]
            project["created"] = self.project.get("created", project.get("created"))
            project["outputs"] = list(self.project.get("outputs") or [])

    def _save_current_project(self) -> dict[str, Any] | None:
        mode = self._current_mode()
        text = self._current_text()
        if mode == "single":
            prompt_zh = self.single_prompt.toPlainText().strip()
            prompt = self._resolve_single_en()
            shots = [{"id": "01", "name": slugify(prompt, "single") or "single",
                      "prompt": prompt, "prompt_zh": prompt_zh or prompt}] if prompt else []
        else:
            shots = self._collect_shots(False)
        if not text and not shots:
            QMessageBox.information(self, "提示", "没有可保存的内容。")
            return None
        project = self._build_project(mode, shots, text or "untitled")
        self._reuse_project_identity(project)
        self.project = project
        path = save_project(project, self.cfg.root)
        self.append_log("项目已保存：%s" % path)
        self.statusBar().showMessage("项目已保存")
        return project

    def save_project_clicked(self) -> None:
        self._save_current_project()

    def new_project_clicked(self) -> None:
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "提示", "还有任务在生成，请先等待或取消。")
            return
        if self.shot_table.rowCount() or self.single_prompt.toPlainText().strip():
            answer = QMessageBox.question(self, "新建项目", "清空当前内容并新建项目？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.project = None
        clear_story_partial(self.cfg.root)
        self._update_partial_button()
        self._run_prefix = ""
        self._run_signature = ""
        self._single_prompt_en = ""
        self._single_prompt_zh = ""
        self.single_role.clear()
        self.single_clothing.clear()
        self.single_scene.clear()
        self.single_desc.clear()
        self.single_extra.clear()
        self.single_prompt.clear()
        self._update_single_prompt_stats()
        self.tags_edit.clear()
        self.tags_zh.clear()
        self._activation_en = ""
        self._activation_zh = ""
        self.story_role.clear()
        self.story_clothing.clear()
        self.story_scene.clear()
        self.story_premise.clear()
        self.story_extra.clear()
        self.output_name.clear()
        self.shot_table.setRowCount(0)
        self._update_shot_stats()
        self.queue_table.setRowCount(0)
        self.gallery.clear()
        self.previews.clear()
        self.final_bytes.clear()
        self.tasks_by_id.clear()
        self.task_rows.clear()
        self.row_task_ids.clear()
        self.current_task_id = None
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("生成时在这里显示实时预览")
        self.preview_info.setText("等待生成")
        self.progress.setValue(0)
        self._switch_mode(0)
        self.btn_mode_single.setChecked(True)
        self.btn_mode_story.setChecked(False)
        self._save_ui_state()
        self.append_log("已新建空白项目")
        self.statusBar().showMessage("已新建空白项目")
        QMessageBox.information(self, "新建项目", "已新建空白项目。")

    def open_project_clicked(self) -> None:
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "提示", "还有任务在生成，请先等待或取消。")
            return
        projects = list_projects(self.cfg.root)
        if not projects:
            QMessageBox.information(self, "提示", "还没有保存过项目。")
            return
        dialog = ProjectDialog(projects, self.cfg.root, self)
        if dialog.exec() and dialog.selected_path:
            self._apply_project(load_project(dialog.selected_path))

    def _ensure_combo_value(self, combo: SearchComboBox, value: str) -> None:
        if not value:
            return
        if combo.findData(value) < 0:
            items = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
            items.append((value, value))
            combo.setItems(items)
        combo.selectValue(value)

    def _append_lora_row(self, table: QTableWidget, name: str, strength: float,
                         checked: bool) -> None:
        row = table.rowCount()
        table.insertRow(row)
        item = QTableWidgetItem(Path(name).name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setToolTip(name)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        table.setItem(row, 0, item)
        spin = QDoubleSpinBox()
        spin.setRange(0, 2)
        spin.setSingleStep(0.05)
        spin.setValue(float(strength))
        table.setCellWidget(row, 1, spin)

    def _apply_table_loras(self, table: QTableWidget, desired: dict[str, float]) -> None:
        desired = {self._lora_key(name): strength for name, strength in desired.items()}
        table.blockSignals(True)
        try:
            existing = {self._lora_key(table.item(row, 0).data(Qt.ItemDataRole.UserRole))
                        for row in range(table.rowCount()) if table.item(row, 0)}
            for name, strength in desired.items():
                if name not in existing:
                    self._append_lora_row(table, name, strength, True)
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                spin = table.cellWidget(row, 1)
                if not item or not spin:
                    continue
                name = self._lora_key(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(Qt.CheckState.Checked if name in desired else Qt.CheckState.Unchecked)
                if name in desired:
                    spin.setValue(desired[name])
        finally:
            table.blockSignals(False)

    def _apply_loras(self, loras: list[dict[str, Any]]) -> None:
        desired = {item["name"]: float(item.get("strength", 0.9)) for item in loras if item.get("name")}
        character: dict[str, float] = {}
        styles: dict[str, float] = {}
        body: dict[str, float] = {}
        action: dict[str, float] = {}
        clothing: dict[str, float] = {}
        for name, strength in desired.items():
            key = self._lora_key(name)
            if key in self._body_lora_names:
                body[name] = strength
            elif key in self._action_lora_names:
                action[name] = strength
            elif key in self._clothing_lora_names:
                clothing[name] = strength
            elif key in self._style_lora_names:
                styles[name] = strength
            elif key in self._character_lora_names:
                character[name] = strength
            elif is_style_lora(name):
                styles[name] = strength
            else:
                character[name] = strength
        self._apply_table_loras(self.lora_table, character)
        self._apply_table_loras(self.style_lora_table, styles)
        self._apply_table_loras(self.body_lora_table, body)
        self._apply_table_loras(self.action_lora_table, action)
        self._apply_table_loras(self.clothing_lora_table, clothing)

    def _apply_project(self, project: dict[str, Any]) -> None:
        self.project = project
        self._run_prefix = ""
        self._run_signature = ""
        mode = project.get("mode", "story")
        if mode == "single":
            self.btn_mode_single.setChecked(True)
            self.btn_mode_story.setChecked(False)
            self._switch_mode(0)
        else:
            self.btn_mode_story.setChecked(True)
            self.btn_mode_single.setChecked(False)
            self._switch_mode(1)

        premise = project.get("premise", "")
        if mode == "single":
            self._set_single_fields(
                project.get("single_fields") or self._parse_story_text(premise))
        else:
            self._set_story_fields(
                project.get("story_fields") or self._parse_story_text(premise))
        shots = project.get("shots") or []
        self._fill_shot_table(shots)
        if mode == "single" and shots:
            prompt = shots[0].get("prompt", "")
            prompt_zh = shots[0].get("prompt_zh") or prompt
            self._single_prompt_en = prompt
            self._single_prompt_zh = prompt_zh
            self.single_prompt.setPlainText(prompt_zh)
        else:
            self._single_prompt_en = ""
            self._single_prompt_zh = ""
            self.single_prompt.clear()

        s = project.get("settings") or {}
        self.width_spin.setValue(int(s.get("width", 1024)))
        self.height_spin.setValue(int(s.get("height", 1344)))
        index = self.res_combo.findData((self.width_spin.value(), self.height_spin.value()))
        self.res_combo.setCurrentIndex(index if index >= 0 else self.res_combo.count() - 1)
        self.steps_spin.setValue(int(s.get("steps", 30)))
        self.cfg_spin.setValue(float(s.get("cfg", 5.0)))
        self._ensure_combo_value(self.sampler_combo, s.get("sampler", "euler_ancestral"))
        self._ensure_combo_value(self.scheduler_combo, s.get("scheduler", "normal"))
        mode_index = self.seed_mode.findData(s.get("seed_mode", "increment"))
        if mode_index >= 0:
            self.seed_mode.setCurrentIndex(mode_index)
        self.seed_spin.setValue(int(s.get("base_seed", 1)))
        self.variants_spin.setValue(int(project.get("variants") or 1))
        img2img = s.get("img2img") or {}
        self.img2img_check.setChecked(bool(img2img.get("enabled", True)))
        self.img2img_denoise.setValue(float(img2img.get("denoise", 0.35)))
        self.clip_skip.setValue(int(project.get("clip_skip", -2)))

        hires = s.get("hires") or {}
        self.hires_check.setChecked(bool(hires.get("enabled", True)))
        self.hires_scale.setValue(float(hires.get("scale", 1.5)))
        self.hires_denoise.setValue(float(hires.get("denoise", 0.4)))
        self.hires_steps.setValue(int(hires.get("steps", 20)))
        self._ensure_combo_value(self.upscaler_combo, hires.get("upscale_model", ""))

        self._ensure_combo_value(self.ckpt_combo, project.get("model", ""))
        loras = project.get("loras") or ([project["lora"]] if project.get("lora") else [])
        self._apply_loras(loras)

        character = project.get("character") or {}
        tags = character.get("tags", "")
        self._activation_en = tags
        self._activation_zh = ""
        self.tags_edit.setPlainText(tags)
        self.tags_zh.clear()
        self._translate_activation_now()
        ip = character.get("ipadapter") or {}
        if character.get("use_ipadapter") and ip.get("reference"):
            self.char_ref.setText(str(ip["reference"]).replace("/", "\\"))
            self.char_ref_weight.setValue(float(ip.get("weight", 0.6)))
        else:
            self.char_ref.clear()
            self.char_ref_weight.setValue(0.6)
        style_ref = project.get("style_ref") or {}
        self.style_ref_check.setChecked(bool(style_ref.get("enabled")))
        self.style_ref_edit.setText(str(style_ref.get("image", "")).replace("/", "\\") if style_ref.get("image") else "")
        self.style_ref_weight.setValue(float(style_ref.get("weight", 0.8)))

        detailer_models = {item.get("model"): item for item in (project.get("detailers") or [])}
        for _key, box, spin, choice in self.detailer_rows:
            match = detailer_models.get(choice["detector"])
            box.setChecked(match is not None)
            if match is not None:
                spin.setValue(float(match.get("denoise", choice["denoise"])))
        wildcards = project.get("wildcards") or {}
        self.wildcard_check.setChecked(bool(wildcards.get("enabled")))
        self.wildcard_dir.setText(str(wildcards.get("dir", "")))
        self.output_name.setText(project.get("name", ""))

        self.gallery.clear()
        self.previews.clear()
        self.final_bytes.clear()
        self.tasks_by_id.clear()
        self.task_rows.clear()
        self.row_task_ids.clear()
        self.queue_table.setRowCount(0)
        self.current_task_id = None
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("生成时在这里显示实时预览")
        self.preview_info.setText("已打开项目：%s" % project.get("name", ""))
        self.progress.setValue(0)
        self.append_log("已打开项目：%s（%s）" % (project.get("name"), project.get("id")))
        self.statusBar().showMessage("已打开项目：%s" % project.get("name", ""))
        self._refresh_reference_tags()
        self._save_ui_state()

    def open_trash(self) -> None:
        if not self.project:
            QMessageBox.information(self, "提示", "先保存或打开一个项目。")
            return
        TrashDialog(self.cfg.root, self.project["id"], self).exec()

    def _gallery_menu(self, pos) -> None:
        item = self.gallery.itemAt(pos)
        if item is None:
            return
        self.gallery.setCurrentItem(item)
        menu = QMenu(self)
        act_open = menu.addAction("打开文件")
        act_trash = menu.addAction("移到回收站")
        chosen = menu.exec(self.gallery.viewport().mapToGlobal(pos))
        if chosen is act_open:
            self._open_gallery_item(item)
        elif chosen is act_trash:
            self._trash_gallery_item(item)

    def _remove_project_output(self, path: str | Path) -> None:
        if not self.project:
            return
        name = Path(str(path).replace("\\", "/")).name
        outputs = self.project.get("outputs") or []
        self.project["outputs"] = [o for o in outputs if Path(str(o).replace("\\", "/")).name != name]
        save_project(self.project, self.cfg.root)

    def _trash_gallery_item(self, item: QListWidgetItem) -> None:
        if not self.project:
            QMessageBox.information(self, "提示", "先保存或打开一个项目。")
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path or not Path(path).is_file():
            QMessageBox.information(self, "提示", "找不到图片文件。")
            return
        try:
            dest = move_to_trash(path, self.project["id"], self.cfg.root)
        except Exception as exc:
            QMessageBox.warning(self, "移动失败", str(exc))
            return
        self._remove_project_output(path)
        task_id = item.data(Qt.ItemDataRole.UserRole + 1)
        if task_id:
            task = self.tasks_by_id.get(task_id)
            if task:
                task.state = "discarded"
            self.final_bytes.pop(task_id, None)
            self.previews.pop(task_id, None)
            row = self.task_rows.get(task_id)
            if row is not None:
                self.queue_table.item(row, 1).setText("已丢弃")
        self.gallery.takeItem(self.gallery.row(item))
        self.append_log("已移入回收站：%s" % dest.name)

    def _remove_gallery_task(self, task_id: str) -> None:
        for index in range(self.gallery.count() - 1, -1, -1):
            item = self.gallery.item(index)
            if item.data(Qt.ItemDataRole.UserRole + 1) == task_id:
                self.gallery.takeItem(index)

    def _discard_entry(self, entry: dict[str, Any]) -> None:
        path = entry.get("path") or ""
        if path and Path(path).is_file() and self.project:
            try:
                move_to_trash(path, self.project["id"], self.cfg.root)
            except Exception as exc:
                self.append_log("丢弃失败：%s" % exc)
                return
            self._remove_project_output(path)
        task = self.tasks_by_id.get(entry["id"])
        if task:
            task.state = "discarded"
            row = self.task_rows.get(task.id)
            if row is not None:
                self.queue_table.item(row, 1).setText("已丢弃")
        self._remove_gallery_task(entry["id"])
        self.final_bytes.pop(entry["id"], None)
        self.previews.pop(entry["id"], None)
        self.append_log("已丢弃变体：%s" % entry.get("label"))

    def compare_variants(self) -> None:
        row = self.queue_table.currentRow()
        task_id = self.row_task_ids.get(row)
        task = self.tasks_by_id.get(task_id) if task_id else None
        if task is None:
            QMessageBox.information(self, "提示", "先在队列里选中一个已完成的图。")
            return
        group = [t for t in self.tasks_by_id.values()
                 if t.shot_id == task.shot_id and t.state == "done" and t.image]
        if len(group) < 2:
            QMessageBox.information(self, "提示", "这个镜头没有多个已完成的变体。")
            return
        entries = []
        for variant in group:
            data = self.final_bytes.get(variant.id)
            local = None
            if data is None:
                try:
                    data, local = self._fetch_image(variant.image)
                except Exception as exc:
                    self.append_log("读取变体失败：%s" % exc)
                    continue
            if data:
                entries.append({"id": variant.id, "label": variant.label,
                                "data": data, "path": str(local) if local else ""})
        if len(entries) < 2:
            QMessageBox.information(self, "提示", "可对比的变体不足。")
            return
        dialog = CompareDialog(task.label, entries, self)
        if dialog.exec():
            for entry in dialog.discarded():
                self._discard_entry(entry)

    def _queue_menu(self, pos) -> None:
        row = self.queue_table.rowAt(pos.y())
        if row < 0:
            return
        self.queue_table.selectRow(row)
        menu = QMenu(self)
        act_same = menu.addAction("重试（同 seed）")
        act_new = menu.addAction("重试（换 seed）")
        act_compare = menu.addAction("变体对比")
        chosen = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if chosen is act_same:
            self._retry_task(False)
        elif chosen is act_new:
            self._retry_task(True)
        elif chosen is act_compare:
            self.compare_variants()

    def _retry_task(self, new_seed: bool) -> None:
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "提示", "还有任务在生成，请先等待或取消。")
            return
        if not self.project:
            QMessageBox.information(self, "提示", "没有可重试的项目。")
            return
        row = self.queue_table.currentRow()
        old_id = self.row_task_ids.get(row)
        old = self.tasks_by_id.get(old_id) if old_id else None
        if old is None:
            return
        seed = random.randint(0, 2 ** 31 - 1) if new_seed else old.seed
        task = Task(shot_id=old.shot_id, shot_name=old.shot_name, variant=old.variant,
                    seed=seed, shot=old.shot, label=old.label)
        self.tasks_by_id[task.id] = task
        self.task_rows[task.id] = row
        self.row_task_ids[row] = task.id
        self.current_task_id = task.id
        for col, text in ((0, task.label), (1, "等待"), (2, ""), (3, ""), (4, str(seed))):
            self.queue_table.item(row, col).setText(text)
        self.queue_table.item(row, 0).setIcon(QIcon())
        self.progress.setValue(0)
        hires = bool((self.project.get("settings") or {}).get("hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, self.project, [task], hires)
        worker.task_updated.connect(self._on_task_update)
        worker.preview.connect(self._on_preview)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_render_finished)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(lambda: self._set_generation_enabled(True))
        self.render_worker = worker
        self._set_generation_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.append_log("重试：%s（seed %d）" % (task.label, seed))
        self.statusBar().showMessage("正在重试 %s…" % task.label)
        worker.start()

    def rewrite_selected_shot(self) -> None:
        row = self.shot_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "先在分镜表里选中一行。")
            return
        data = self._row_data(row)
        if data["locked"]:
            QMessageBox.information(self, "提示", "该镜头已锁定，先取消锁定再改写。")
            return
        if not data["prompt"].strip():
            QMessageBox.information(self, "提示", "该镜头没有提示词。")
            return
        if not self.connected or not self._llm():
            QMessageBox.information(self, "提示", "请先连接 ComfyUI / Ollama 并选择模型。")
            return
        instruction, ok = QInputDialog.getText(
            self, "改写镜头", "改写要求（例：半身、回头看镜头、黄昏逆光）")
        if not ok or not instruction.strip():
            return
        current_prompt = data.get("prompt_en") or data["prompt"]
        if data["prompt"] != data.get("prompt_zh") or not data.get("prompt_en"):
            resolved = self._resolve_chinese_texts([data["prompt"]])
            if resolved and resolved[0]:
                current_prompt = resolved[0]
        worker = PromptWorker(
            self.cfg, "rewrite", self._story_premise_text(),
            model=self._llm(),
            current_prompt=current_prompt,
            instruction=instruction.strip(),
            character_tags=self._character_tags(),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora())
        self._rewrite_row = row
        worker.rewritten.connect(self._on_rewritten)
        worker.failed.connect(self._on_prompt_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self._set_generation_enabled(False)
        self.statusBar().showMessage("Ollama 模型正在改写镜头…")
        worker.start()

    def _on_rewritten(self, result: dict[str, str]) -> None:
        row = self._rewrite_row
        self._rewrite_row = None
        prompt = result.get("prompt", "")
        translation = result.get("prompt_zh", "")
        if row is not None and 0 <= row < self.shot_table.rowCount():
            item = self.shot_table.item(row, 3)
            if item:
                self._syncing_shots = True
                try:
                    item.setText(translation or prompt)
                    item.setData(PROMPT_EN_ROLE, prompt)
                    item.setData(PROMPT_ZH_ROLE, translation or prompt)
                finally:
                    self._syncing_shots = False
        self._update_shot_stats()
        self.append_log("镜头已改写（中文）：%s" % (translation or prompt))
        self.statusBar().showMessage("镜头已改写")

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
        for widget in (self.btn_single_prompt, self.btn_single_external,
                       self.btn_single_render, self.btn_story_prompt,
                       self.btn_story_external, self.btn_story_render,
                       self.btn_rewrite_shot, self.tabs):
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
        models = self._merge_values(
            [self.llm_combo.itemData(i) for i in range(self.llm_combo.count())],
            self.ollama_models)
        dialog = SettingsDialog(self.cfg, self, models=models)
        if not dialog.exec():
            return
        self.cfg = load_config()
        self.cfg.ensure_dirs()
        self.template_path = resolve_template(self.cfg)
        self.template = load_template(self.cfg)
        self._lora_info_cache.clear()
        self._online_tried.clear()
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

    def _lora_table_state(self, table: QTableWidget) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            spin = table.cellWidget(row, 1)
            if item and spin:
                name = item.data(Qt.ItemDataRole.UserRole)
                if name:
                    result[self._lora_key(name)] = {
                        "checked": item.checkState() == Qt.CheckState.Checked,
                        "strength": spin.value(),
                    }
        return result

    def _capture_ui_state(self) -> dict[str, Any]:
        shots = [self._row_data(row) for row in range(self.shot_table.rowCount())]
        detailers = dict(self._detailer_state)
        for key, box, spin, _choice in self.detailer_rows:
            detailers[key] = {"checked": box.isChecked(), "denoise": spin.value()}
        return {
            "version": 1,
            "mode": self._current_mode(),
            "window": {
                "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                "main_split": self.main_split.sizes(),
                "main_vsplit": self.main_vsplit.sizes(),
            },
            "tabs": {
                "right": self.tabs.currentIndex(),
                "bottom": self.bottom_tabs.currentIndex(),
            },
            "single": {
                **self._single_fields(),
                "framing": self.framing.currentData(),
                "prompt": self.single_prompt.toPlainText(),
                "prompt_en": self._single_prompt_en,
                "prompt_zh": self._single_prompt_zh,
            },
            "story": {
                **self._story_fields(),
                "shots_count": self.story_shots.value(),
                "shots": shots,
                "selected_only": self.chk_selected.isChecked(),
            },
            "activation": {
                "text": self.tags_edit.toPlainText(),
                "en": self._activation_en,
                "zh": self._activation_zh,
            },
            "positive": {
                "text": self.positive_extra.toPlainText(),
                "en": self._positive_extra_en,
                "zh": self._positive_extra_zh,
            },
            "negative": {
                "text": self.negative_extra.toPlainText(),
                "en": self._negative_extra_en,
                "zh": self._negative_extra_zh,
            },
            "loras": {
                "character": self._lora_table_state(self.lora_table),
                "style": self._lora_table_state(self.style_lora_table),
                "body": self._lora_table_state(self.body_lora_table),
                "action": self._lora_table_state(self.action_lora_table),
                "clothing": self._lora_table_state(self.clothing_lora_table),
            },
            "detailers": detailers,
            "options": {
                "llm": self.llm_combo.currentValue(),
                "ckpt": self.ckpt_combo.currentValue(),
                "clip_skip": self.clip_skip.value(),
                "width": self.width_spin.value(),
                "height": self.height_spin.value(),
                "steps": self.steps_spin.value(),
                "cfg": self.cfg_spin.value(),
                "sampler": self.sampler_combo.currentValue(),
                "scheduler": self.scheduler_combo.currentValue(),
                "seed_mode": self.seed_mode.currentData(),
                "base_seed": self.seed_spin.value(),
                "variants": self.variants_spin.value(),
                "output_name": self.output_name.text(),
                "hires_enabled": self.hires_check.isChecked(),
                "hires_scale": self.hires_scale.value(),
                "hires_denoise": self.hires_denoise.value(),
                "hires_steps": self.hires_steps.value(),
                "upscaler": self.upscaler_combo.currentValue(),
                "char_ref": self.char_ref.text(),
                "char_ref_weight": self.char_ref_weight.value(),
                "style_ref_enabled": self.style_ref_check.isChecked(),
                "style_ref_image": self.style_ref_edit.text(),
                "style_ref_weight": self.style_ref_weight.value(),
                "wildcard_enabled": self.wildcard_check.isChecked(),
                "wildcard_dir": self.wildcard_dir.text(),
                "img2img_enabled": self.img2img_check.isChecked(),
                "img2img_denoise": self.img2img_denoise.value(),
                "follow_preview": self.chk_follow.isChecked(),
            },
        }

    def _save_ui_state(self) -> None:
        if self._restoring_state:
            return
        try:
            save_session(self._capture_ui_state(), self.cfg.root)
        except Exception as exc:
            self.append_log("界面状态保存失败：%s" % exc)

    def _restore_lora_table(self, table: QTableWidget,
                            state: dict[str, Any]) -> None:
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                spin = table.cellWidget(row, 1)
                if not item or not spin:
                    continue
                name = item.data(Qt.ItemDataRole.UserRole)
                saved = state.get(self._lora_key(name))
                checked = bool(saved.get("checked")) if isinstance(saved, dict) else False
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                if isinstance(saved, dict) and "strength" in saved:
                    spin.setValue(float(saved["strength"]))
        finally:
            table.blockSignals(False)

    def _apply_ui_state(self, state: dict[str, Any]) -> None:
        window = state.get("window") or {}
        geometry = window.get("geometry")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(str(geometry).encode("ascii")))
            except Exception:
                pass
        self._ensure_window_on_screen()
        for splitter, key in ((self.main_split, "main_split"),
                              (self.main_vsplit, "main_vsplit")):
            sizes = window.get(key)
            if isinstance(sizes, list) and len(sizes) == splitter.count():
                splitter.setSizes([int(size) for size in sizes])

        loras = state.get("loras") or {}
        self._restore_lora_table(self.lora_table, loras.get("character") or {})
        self._restore_lora_table(self.style_lora_table, loras.get("style") or {})
        self._restore_lora_table(self.body_lora_table, loras.get("body") or {})
        self._restore_lora_table(self.action_lora_table, loras.get("action") or {})
        self._restore_lora_table(self.clothing_lora_table, loras.get("clothing") or {})

        detailers = state.get("detailers") or {}
        self._detailer_state = {
            str(key): {
                "checked": bool(value.get("checked")),
                "denoise": float(value.get("denoise", 0.3)),
            }
            for key, value in detailers.items() if isinstance(value, dict)
        }
        for key, box, spin, _choice in self.detailer_rows:
            saved = self._detailer_state.get(key)
            if saved:
                box.setChecked(bool(saved["checked"]))
                spin.setValue(float(saved["denoise"]))

        activation = state.get("activation") or {}
        self._activation_en = str(activation.get("en") or "")
        self._activation_zh = str(activation.get("zh") or "")
        text = str(activation.get("text") or self._activation_en)
        for field, value in ((self.tags_edit, text),
                             (self.tags_zh, self._activation_zh)):
            field.blockSignals(True)
            try:
                field.setPlainText(value)
            finally:
                field.blockSignals(False)
        self._update_tag_estimate()

        for name, attr, en_attr, zh_attr in (
                ("positive", self.positive_extra, "_positive_extra_en", "_positive_extra_zh"),
                ("negative", self.negative_extra, "_negative_extra_en", "_negative_extra_zh")):
            saved = state.get(name) or {}
            setattr(self, en_attr, str(saved.get("en") or ""))
            setattr(self, zh_attr, str(saved.get("zh") or ""))
            attr.blockSignals(True)
            try:
                attr.setPlainText(str(saved.get("text") or ""))
            finally:
                attr.blockSignals(False)

        single = state.get("single") or {}
        self._set_single_fields(single)
        self._single_prompt_en = str(single.get("prompt_en") or "")
        self._single_prompt_zh = str(single.get("prompt_zh") or "")
        self.single_prompt.blockSignals(True)
        try:
            self.single_prompt.setPlainText(str(single.get("prompt") or ""))
        finally:
            self.single_prompt.blockSignals(False)
        index = self.framing.findData(single.get("framing", "auto"))
        if index >= 0:
            self.framing.setCurrentIndex(index)
        self._update_single_prompt_stats()
        has_prompt = bool(self.single_prompt.toPlainText().strip())
        self.btn_expand.setEnabled(has_prompt)
        self.btn_single_prompt.setText(
            "① 重新生成提示词" if has_prompt else "① 生成提示词")

        story = state.get("story") or {}
        self._set_story_fields(story)
        self.story_shots.setValue(int(story.get("shots_count", 6)))
        saved_shots = story.get("shots") or []
        restored_shots = [{
            "id": shot.get("id", ""),
            "name": shot.get("name", ""),
            "prompt": shot.get("prompt_en") or shot.get("prompt", ""),
            "prompt_zh": shot.get("prompt") or shot.get("prompt_zh", ""),
            "outline": shot.get("outline", ""),
            "cast": shot.get("cast", ""),
            "script": shot.get("script", ""),
            "phase": shot.get("phase", ""),
            "locked": bool(shot.get("locked")),
        } for shot in saved_shots if isinstance(shot, dict)]
        self._fill_shot_table(restored_shots)
        for row, shot in enumerate(saved_shots):
            if row >= self.shot_table.rowCount() or not isinstance(shot, dict):
                break
            item = self.shot_table.item(row, 3)
            if item:
                item.setData(PROMPT_ZH_ROLE, str(shot.get("prompt_zh") or ""))
        self.chk_selected.setChecked(bool(story.get("selected_only")))

        options = state.get("options") or {}
        for combo, key in ((self.llm_combo, "llm"),
                           (self.ckpt_combo, "ckpt"),
                           (self.sampler_combo, "sampler"),
                           (self.scheduler_combo, "scheduler"),
                           (self.upscaler_combo, "upscaler")):
            value = str(options.get(key) or "")
            if value:
                self._ensure_combo_value(combo, value)
        self.clip_skip.setValue(int(options.get("clip_skip", -2)))
        self.width_spin.setValue(int(options.get("width", 1024)))
        self.height_spin.setValue(int(options.get("height", 1344)))
        res_index = self.res_combo.findData(
            (self.width_spin.value(), self.height_spin.value()))
        self.res_combo.setCurrentIndex(
            res_index if res_index >= 0 else self.res_combo.count() - 1)
        self.width_spin.setValue(int(options.get("width", 1024)))
        self.height_spin.setValue(int(options.get("height", 1344)))
        self.steps_spin.setValue(int(options.get("steps", 30)))
        self.cfg_spin.setValue(float(options.get("cfg", 5.0)))
        seed_index = self.seed_mode.findData(options.get("seed_mode", "increment"))
        if seed_index >= 0:
            self.seed_mode.setCurrentIndex(seed_index)
        self.seed_spin.setValue(int(options.get("base_seed", 0)))
        self.variants_spin.setValue(int(options.get("variants", 1)))
        self.output_name.setText(str(options.get("output_name") or ""))
        self.hires_check.setChecked(bool(options.get("hires_enabled", True)))
        self.hires_scale.setValue(float(options.get("hires_scale", 1.5)))
        self.hires_denoise.setValue(float(options.get("hires_denoise", 0.4)))
        self.hires_steps.setValue(int(options.get("hires_steps", 20)))
        self.char_ref.setText(str(options.get("char_ref") or ""))
        self.char_ref_weight.setValue(float(options.get("char_ref_weight", 0.6)))
        self.style_ref_check.setChecked(bool(options.get("style_ref_enabled")))
        self.style_ref_edit.setText(str(options.get("style_ref_image") or ""))
        self.style_ref_weight.setValue(float(options.get("style_ref_weight", 0.8)))
        self.wildcard_check.setChecked(bool(options.get("wildcard_enabled")))
        self.wildcard_dir.setText(str(options.get("wildcard_dir") or ""))
        self.img2img_check.setChecked(bool(options.get("img2img_enabled", True)))
        self.img2img_denoise.setValue(float(options.get("img2img_denoise", 0.35)))
        self.chk_follow.setChecked(bool(options.get("follow_preview", True)))

        mode = state.get("mode", "single")
        if mode == "story":
            self.btn_mode_story.setChecked(True)
            self.btn_mode_single.setChecked(False)
            self._switch_mode(1)
        else:
            self.btn_mode_single.setChecked(True)
            self.btn_mode_story.setChecked(False)
            self._switch_mode(0)
        tabs = state.get("tabs") or {}
        right = int(tabs.get("right", 0))
        if 0 <= right < self.tabs.count():
            self.tabs.setCurrentIndex(right)
        bottom = int(tabs.get("bottom", 0))
        if 0 <= bottom < self.bottom_tabs.count():
            self.bottom_tabs.setCurrentIndex(bottom)
        self._refresh_reference_tags()

    def _ensure_window_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.width() > available.width() or frame.height() > available.height():
            self.resize(min(frame.width(), available.width()),
                        min(frame.height(), available.height()))
            frame = self.frameGeometry()
        if not available.intersects(frame):
            self.move(available.center() - self.rect().center())

    def _restore_ui_state(self) -> None:
        state = load_session(self.cfg.root)
        if not state:
            return
        self._restoring_state = True
        try:
            self._apply_ui_state(state)
        except Exception as exc:
            self.append_log("界面状态恢复失败：%s" % exc)
        finally:
            self._restoring_state = False

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_ui_state()
        if self._state_timer.isActive():
            self._state_timer.stop()
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
        self._save_ui_state()
        event.accept()
