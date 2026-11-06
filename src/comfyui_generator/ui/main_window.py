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

from PySide6.QtCore import (
    QByteArray, QFileSystemWatcher, QItemSelectionModel, QSize, Qt, QTimer,
)
from PySide6.QtGui import QAction, QBrush, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel,
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
from comfyui_generator.core.continuity import (
    GRAMMAR_STYLE_CHOICES, auto_shot_grammar, character_sheet_prompt,
    normalize_continuity,
)
from comfyui_generator.core.detailers import build_detailer_choices, filter_detector_models, local_detectors
from comfyui_generator.core.jobs import Task, build_tasks
from comfyui_generator.core.lora_info import is_style_lora, lora_tag_info
from comfyui_generator.core.lora_sources import lora_display_label, lora_entries
from comfyui_generator.core.model_configs import (
    find_model_config, load_model_configs,
)
from comfyui_generator.core.ollama import OllamaClient
from comfyui_generator.core.pose import (
    CLASSIC_POSE_LABELS, POSE_PRESET_LABELS, load_pose_presets,
    save_pose_presets,
)
from comfyui_generator.core.project import (
    clear_story_partial, configure_projects_dir, list_projects, load_project,
    load_session, load_story_partial, move_to_trash, new_project, save_project,
    save_session, save_story_partial,
)
from comfyui_generator.core.quality import check_project, format_report, repair_project
from comfyui_generator.core.services import ComfyService
from comfyui_generator.core.single import FRAMING_TAGS, SingleOptions
from comfyui_generator.core.style_profile import (
    STYLE_PROFILE_CHOICES, apply_style_profile, get_style_profile,
    normalize_style_profile, style_profile_apply_settings,
)
from comfyui_generator.core.storyboard import (
    StoryboardOptions, extract_premise_beats,
    normalize_shot_casts, parse_character_profiles,
    premise_from_json, shots_from_json, slugify,
)
from comfyui_generator.core.tag_cache import load_tag_cache, update_tag_cache
from comfyui_generator.core.tags import append_tags, estimate_tokens
from comfyui_generator.core.vision import format_similarity, vision_ready
from comfyui_generator.core.translate import translate_to_tags
from comfyui_generator.core.workflow import compose_prompts
from comfyui_generator.ui.branding import app_icon, logo_pixmap
from comfyui_generator.ui.contact_sheet import build_contact_sheet, build_face_sheet
from comfyui_generator.ui.continuity_worker import ContinuityWorker
from comfyui_generator.ui.dialogs import (
    CompareDialog, ProjectDialog, ShotDetailsDialog, TagReferenceDialog, TrashDialog,
)
from comfyui_generator.ui.settings_dialog import SettingsDialog
from comfyui_generator.ui.vision_worker import VisionWorker
from comfyui_generator.ui.wheel_guard import install_wheel_guard
from comfyui_generator.ui.widgets import SearchComboBox, WrappingTabs
from comfyui_generator.ui.workers import AssetsWorker, AutoTranslateWorker, ConnectWorker, ExpansionWorker, LoraTagsWorker, PromptWorker, RenderWorker, TagTranslateWorker

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
    "masterpiece", "best quality", "amazing quality", "very aesthetic",
    "absurdres", "newest", "ultra-detailed", "extremely detailed",
    "sharp focus", "highres", "official art",
    "beautiful detailed eyes", "beautiful detailed face",
    "scenery", "volumetric lighting",
]
DEFAULT_POSITIVE_EXTRA_ZH_TAGS = [
    "杰作", "最佳质量", "惊人的质量", "非常有美感",
    "极高分辨率", "最新", "超详细", "极详细",
    "清晰聚焦", "高分辨率", "官方艺术",
    "美丽的详细眼睛", "美丽的详细面部",
    "风景", "体积光",
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


def _append_chinese_defaults(text: str, defaults: list[str]) -> str:
    items = [item.strip() for item in re.split(
        r"[,，、;；\n]+", str(text or "")) if item.strip()]
    seen = {item.lower() for item in items}
    for item in defaults:
        if item.lower() not in seen:
            items.append(item)
            seen.add(item.lower())
    return "、".join(items)


def merge_default_positive(en: str, zh: str, text: str) -> tuple[str, str, str]:
    value = str(text or "").strip()
    merged_en = append_tags(en or value, DEFAULT_POSITIVE_EXTRA_EN)
    if not value:
        return merged_en, DEFAULT_POSITIVE_EXTRA_ZH, DEFAULT_POSITIVE_EXTRA_ZH
    if re.search(r"[\u4e00-\u9fff]", value):
        merged_zh = _append_chinese_defaults(
            zh or value, DEFAULT_POSITIVE_EXTRA_ZH_TAGS)
        return merged_en, merged_zh, merged_zh
    return merged_en, zh, merged_en


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
BEAT_ROLE = PHASE_ROLE + 1
CLOTHING_ROLE = BEAT_ROLE + 1
CHARACTERS_ROLE = CLOTHING_ROLE + 1
CHARACTER_STATES_ROLE = CHARACTERS_ROLE + 1
SCENE_ROLE = CHARACTER_STATES_ROLE + 1
CLOTHING_DETAILS_ROLE = SCENE_ROLE + 1
PROMPT_GROUPS_ROLE = CLOTHING_DETAILS_ROLE + 1
CONTINUITY_STATE_ROLE = PROMPT_GROUPS_ROLE + 1
CONTINUITY_SCENE_ROLE = CONTINUITY_STATE_ROLE + 1
KEYFRAME_PROMPT_ROLE = CONTINUITY_SCENE_ROLE + 1
AI_EXPANSIONS_ROLE = KEYFRAME_PROMPT_ROLE + 1
GALLERY_PATH_ROLE = AI_EXPANSIONS_ROLE + 1
GALLERY_TASK_ROLE = GALLERY_PATH_ROLE + 1
GALLERY_IMAGE_ROLE = GALLERY_TASK_ROLE + 1
GALLERY_META_ROLE = GALLERY_IMAGE_ROLE + 1
GALLERY_FAVORITE_ROLE = GALLERY_META_ROLE + 1
GALLERY_INDEX_ROLE = GALLERY_FAVORITE_ROLE + 1


class GalleryViewerDialog(QDialog):
    def __init__(self, path: Path, metadata: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("画廊预览 - %s" % path.name)
        self.resize(1100, 820)
        self._fullscreen = False
        self._pixmap = QPixmap(str(path))
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not self._pixmap.isNull():
            self.image.setPixmap(self._pixmap)
        else:
            self.image.setText("无法读取图片")
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(160)
        self.info.setPlainText(metadata)
        layout.addWidget(self.info)
        self.button_bar = QWidget()
        buttons = QHBoxLayout(self.button_bar)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.btn_fullscreen = QPushButton("全屏")
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        open_folder = QPushButton("打开文件夹")
        open_folder.clicked.connect(
            lambda: os.startfile(str(path.parent)))  # noqa: S606
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_fullscreen)
        buttons.addWidget(open_folder)
        buttons.addWidget(close)
        layout.addWidget(self.button_bar)
        QTimer.singleShot(0, self._fit_image)

    def _fit_image(self) -> None:
        if self._pixmap.isNull():
            return
        size = self.scroll.viewport().size()
        if size.width() < 10 or size.height() < 10:
            return
        self.image.setPixmap(self._pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        self.info.setVisible(not self._fullscreen)
        self.button_bar.setVisible(not self._fullscreen)
        if self._fullscreen:
            self.showFullScreen()
            self.btn_fullscreen.setText("退出全屏")
        else:
            self.showNormal()
            self.resize(1100, 820)
            self.btn_fullscreen.setText("全屏")
        QTimer.singleShot(0, self._fit_image)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F11 or (
                event.key() == Qt.Key.Key_Escape and self._fullscreen):
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)


class GalleryCompareDialog(QDialog):
    def __init__(self, entries: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("画廊对比")
        self.resize(1200, 800)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        for index, entry in enumerate(entries):
            card = QWidget()
            card_layout = QVBoxLayout(card)
            image = QLabel()
            pixmap = QPixmap(str(entry["path"]))
            if not pixmap.isNull():
                image.setPixmap(pixmap.scaled(
                    360, 360, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(image)
            label = QLabel(str(entry.get("label") or entry["path"].name))
            label.setWordWrap(True)
            card_layout.addWidget(label)
            grid.addWidget(card, index // 3, index % 3)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def _label(text: str, name: str = "Section") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        install_wheel_guard()
        self.setWindowTitle("ComfyUI Generator")
        self.setWindowIcon(app_icon())
        self.resize(1480, 940)
        self.cfg: AppConfig = load_config()
        self.cfg.ensure_dirs()
        configure_projects_dir(
            self.cfg.root, self.cfg.projects_dir, self.cfg.single_projects_dir)
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
        self.reference_sheet_worker: RenderWorker | None = None
        self.vision_worker: VisionWorker | None = None
        self.continuity_worker: ContinuityWorker | None = None
        self.expansion_worker: ExpansionWorker | None = None
        self._pending_render: tuple[dict[str, Any], list[dict[str, Any]], int] | None = None
        self.tasks_by_id: dict[str, Any] = {}
        self.task_rows: dict[str, int] = {}
        self.row_task_ids: dict[int, str] = {}
        self.previews: dict[str, bytes] = {}
        self.final_bytes: dict[str, bytes] = {}
        self._icon_last: dict[str, float] = {}
        self._lora_info_cache: dict[str, dict] = {}
        self._selected_shot_ids: list[str] = []
        self.model_configs = load_model_configs()
        self._loading_model_config = False
        self._reference_tags: list[str] = []
        self._lora_paths: dict[str, str] = {}
        self._online_tried: set[str] = set()
        self.lora_tags_worker: LoraTagsWorker | None = None
        self._lora_label_worker: TagTranslateWorker | None = None
        self._lora_label_pending = False
        self._lora_label_translations: dict[str, str] = {}
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
        self._loading_style_profile = True
        self._pose_custom = load_pose_presets(
            self.cfg.root / "pose_presets.json")

        self._build_ui()
        self._build_menu()
        self._init_defaults()
        self._setup_auto_translate()
        self._restore_ui_state()
        self._apply_model_preset_migration()
        self._sync_model_config_to_checkpoint(apply=True)
        self._ensure_window_on_screen()
        self._loading_style_profile = False
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
        vsplit.setSizes([780, 160])
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

        self.btn_interrupt = QPushButton("打断生成")
        self.btn_interrupt.setObjectName("Primary")
        self.btn_interrupt.setEnabled(False)
        self.btn_interrupt.clicked.connect(self.interrupt_generation)
        row.addWidget(self.btn_interrupt)
        self.btn_reconnect = QPushButton("重新连接")
        self.btn_reconnect.clicked.connect(lambda: self.connect_services(False))
        self.btn_restart = QPushButton("重启 ComfyUI")
        self.btn_restart.clicked.connect(self.restart_comfy)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_output = QPushButton("打开目录")
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(580)
        return scroll

    def _build_single_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        copy_row = QHBoxLayout()
        copy_row.addStretch(1)
        self.btn_single_to_story = QPushButton("复制到连续剧情 →")
        self.btn_single_to_story.setToolTip(
            "把单图的角色、外貌、服装、场景、画面描述和其它复制到连续剧情")
        self.btn_single_to_story.clicked.connect(self.copy_single_to_story)
        copy_row.addWidget(self.btn_single_to_story)
        layout.addLayout(copy_row)
        layout.addWidget(_label("角色标签（会拼入提示词）"))
        self.single_role = QPlainTextEdit()
        self.single_role.setPlaceholderText("例：yixuan \\(zenless zone zero\\), solo, hairclip")
        self.single_role.setFixedHeight(52)
        layout.addWidget(self.single_role)

        layout.addWidget(_label("外貌 / 身材（全片锁定）"))
        self.single_appearance = QPlainTextEdit()
        self.single_appearance.setPlaceholderText(
            "例：silver hair, red eyes, long hair, tall, large breasts")
        self.single_appearance.setFixedHeight(44)
        layout.addWidget(self.single_appearance)

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

        count_row = QHBoxLayout()
        count_row.addWidget(_label("图生图张数", "Hint"))
        self.single_expand_spin = QSpinBox()
        self.single_expand_spin.setRange(0, 50)
        self.single_expand_spin.setValue(3)
        self.single_expand_spin.setToolTip("单图最多可连续生成 1 + 这个数量的图")
        count_row.addWidget(self.single_expand_spin)
        count_row.addWidget(_label("0 = 只出关键帧", "Hint"))
        count_row.addStretch(1)
        layout.addLayout(count_row)

        self.btn_single_render = QPushButton("② 生成图片")
        self.btn_single_render.setObjectName("Primary")
        self.btn_single_render.clicked.connect(self.render_single_clicked)
        layout.addWidget(self.btn_single_render)
        self.btn_single_effective = QPushButton("查看实际正负提示词…")
        self.btn_single_effective.clicked.connect(self.show_effective_prompt)
        layout.addWidget(self.btn_single_effective)

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
        copy_row = QHBoxLayout()
        self.btn_story_to_single = QPushButton("← 复制到单图")
        self.btn_story_to_single.setToolTip(
            "把连续剧情的角色、外貌、服装、场景、剧情和其它复制到单图")
        self.btn_story_to_single.clicked.connect(self.copy_story_to_single)
        copy_row.addWidget(self.btn_story_to_single)
        copy_row.addStretch(1)
        layout.addLayout(copy_row)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(3)

        form_layout.addWidget(_label("角色标签（会拼入提示词）"))
        self.story_role = QPlainTextEdit()
        self.story_role.setPlaceholderText("例：yixuan \\(zenless zone zero\\), solo, hairclip")
        self.story_role.setFixedHeight(44)
        form_layout.addWidget(self.story_role)

        form_layout.addWidget(_label("外貌 / 身材（全片锁定）"))
        self.story_appearance = QPlainTextEdit()
        self.story_appearance.setPlaceholderText(
            "例：silver hair, red eyes, long hair, tall, large breasts；多人可写：女主：…；男主：…")
        self.story_appearance.setFixedHeight(44)
        form_layout.addWidget(self.story_appearance)

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

        self.shot_table = QTableWidget(0, 6)
        self.shot_table.setHorizontalHeaderLabels([
            "锁", "镜号", "名称", "画面提示词（中文，可编辑）", "景别", "机位",
        ])
        self.shot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.shot_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.shot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.shot_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                        | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.shot_table.itemChanged.connect(self._on_shot_item_changed)
        self.shot_table.itemSelectionChanged.connect(
            self._remember_shot_selection)
        self.shot_table.cellClicked.connect(self._on_shot_cell_clicked)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_scroll.setWidget(form)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(form_scroll)
        splitter.addWidget(self.shot_table)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 260])
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
        self.btn_effective_prompt = QPushButton("查看实际正负提示词…")
        self.btn_effective_prompt.clicked.connect(self.show_effective_prompt)
        layout.addWidget(self.btn_effective_prompt)

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
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setMinimumWidth(0)
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
        self.tabs.addTab(self._build_continuity_tab(), "连贯")
        self.tabs.addTab(self._build_style_ref_tab(), "参考图")
        layout.addWidget(self.tabs)
        layout.addStretch(1)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(420)
        scroll.setMaximumWidth(560)
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
        self.ckpt_combo.currentIndexChanged.connect(
            self._on_checkpoint_changed)
        form.addWidget(self.ckpt_combo)
        form.addWidget(_label("配置选择（自动套用推荐参数）"))
        self.model_config_combo = SearchComboBox(
            placeholder="选择底模推荐配置", allow_free_text=False)
        self.model_config_combo.currentIndexChanged.connect(
            self._on_model_config_changed)
        self.model_config_combo.activated.connect(
            self._on_model_config_activated)
        form.addWidget(self.model_config_combo)
        self.btn_apply_model_config = QPushButton("应用配置")
        self.btn_apply_model_config.clicked.connect(
            self._on_model_config_changed)
        form.addWidget(self.btn_apply_model_config)
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
        layout.addWidget(_label("角色参考图 / 参考表（IPAdapter，可选）"))
        row = QHBoxLayout()
        self.char_ref = QLineEdit()
        self.char_ref.setPlaceholderText("单张角色图，或正面/侧面/背面多视图参考表")
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
        ref_hint = _label(
            "可放单张角色图，也可放多视图参考表；填写后自动用于所有镜头。"
            "参考表建议固定服装、中性背景、正面/侧面/背面。", "Hint")
        ref_hint.setWordWrap(True)
        layout.addWidget(ref_hint)
        self.btn_character_sheet = QPushButton("生成多视图角色参考表")
        self.btn_character_sheet.setToolTip(
            "按当前角色标签、外貌和初始服装生成正面/侧面/背面参考表，"
            "完成后自动填入参考图")
        self.btn_character_sheet.clicked.connect(self.generate_character_sheet)
        layout.addWidget(self.btn_character_sheet)
        layout.addStretch(1)
        return page

    def _build_style_lora_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.addWidget(_label("视觉风格方案（可选）"))
        self.style_profile_combo = SearchComboBox()
        self.style_profile_combo.setItems(STYLE_PROFILE_CHOICES)
        layout.addWidget(self.style_profile_combo)
        self.style_profile_hint = _label("", "Hint")
        self.style_profile_hint.setWordWrap(True)
        layout.addWidget(self.style_profile_hint)
        row_profile = QHBoxLayout()
        self.style_profile_prompt = QCheckBox("提示词")
        self.style_profile_prompt.setChecked(True)
        self.style_profile_prompt.setToolTip("把风格方案的正向风格词加入出图")
        self.style_profile_negative = QCheckBox("负面词")
        self.style_profile_negative.setChecked(True)
        self.style_profile_negative.setToolTip("把风格方案的冲突词加入负面提示词")
        self.style_profile_suffix = QCheckBox("后缀")
        self.style_profile_suffix.setChecked(True)
        self.style_profile_suffix.setToolTip("把风格方案的构图/质量后缀加入正向提示词")
        for box in (self.style_profile_prompt, self.style_profile_negative,
                    self.style_profile_suffix):
            row_profile.addWidget(box)
        row_profile.addStretch(1)
        layout.addLayout(row_profile)
        self.style_profile_combo.currentIndexChanged.connect(
            self._on_style_profile_changed)
        self._on_style_profile_changed()
        layout.addWidget(_label("风格 LoRA（可多选）"))
        self.style_lora_table = self._make_lora_table()
        self.style_lora_table.itemChanged.connect(self._on_lora_item_changed)
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
        self.body_lora_table.itemChanged.connect(self._on_lora_item_changed)
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
        self.action_lora_table.itemChanged.connect(self._on_lora_item_changed)
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
        self.clothing_lora_table.itemChanged.connect(self._on_lora_item_changed)
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

        self.generation_count_label = _label("", "Hint")
        self.generation_count_label.setWordWrap(True)
        layout.addWidget(self.generation_count_label)

        self.pose_check = QCheckBox("自动 OpenPose 双人骨架")
        self.pose_check.setChecked(False)
        self.pose_check.setToolTip("按剧情自动选择双人姿势并送入 ControlNet；需要 OpenPose ControlNet 模型")
        layout.addWidget(self.pose_check)
        row = QHBoxLayout()
        row.addWidget(_label("OpenPose 模型", "Hint"))
        self.pose_controlnet = SearchComboBox(
            placeholder="自动选择 openpose 模型", allow_free_text=True)
        row.addWidget(self.pose_controlnet, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("姿势预设", "Hint"))
        self.pose_preset = SearchComboBox()
        self.pose_preset.addItem("自动（按剧情）", "auto")
        for key, label in POSE_PRESET_LABELS.items():
            self.pose_preset.addItem(label, key)
        for key, label in CLASSIC_POSE_LABELS.items():
            self.pose_preset.addItem(label, key)
        row.addWidget(self.pose_preset, 1)
        row.addWidget(_label("强度", "Hint"))
        self.pose_strength = QDoubleSpinBox()
        self.pose_strength.setRange(0.0, 1.5)
        self.pose_strength.setSingleStep(0.05)
        self.pose_strength.setValue(0.7)
        row.addWidget(self.pose_strength)
        layout.addLayout(row)
        pose_hint = _label(
            "双人镜头使用整张双人骨架；没有 OpenPose 模型时自动跳过。", "Hint")
        pose_hint.setWordWrap(True)
        layout.addWidget(pose_hint)
        self.btn_pose_editor = QPushButton("预览 / 编辑所有骨架")
        self.btn_pose_editor.clicked.connect(self.open_pose_editor)
        layout.addWidget(self.btn_pose_editor)

        ref_box = QGroupBox("参考骨架（可选，优先于自动预设）")
        ref_layout = QVBoxLayout(ref_box)
        for label, attr in (
                ("双人骨架", "pose_pair_ref"),
                ("女主骨架", "pose_girl_ref"),
                ("男主骨架", "pose_boy_ref")):
            row = QHBoxLayout()
            row.addWidget(_label(label, "Hint"))
            edit = QLineEdit()
            setattr(self, attr, edit)
            row.addWidget(edit, 1)
            button = QPushButton("浏览")
            button.clicked.connect(
                lambda _checked=False, field=edit: self._pick_pose_ref(field))
            row.addWidget(button)
            ref_layout.addLayout(row)
        layout.addWidget(ref_box)

        layout.addWidget(_label("骨架微调", "Section"))
        for label, prefix in (("女主", "pose_girl"), ("男主", "pose_boy")):
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(2)
            grid.addWidget(_label(label, "Hint"), 0, 0)
            for column, (text, suffix, low, high, step, value, width) in enumerate((
                    ("X", "%", -30.0, 30.0, 1.0, 0.0, 68),
                    ("Y", "%", -30.0, 30.0, 1.0, 0.0, 68),
                    ("缩放", "", 0.5, 1.8, 0.05, 1.0, 68),
                    ("旋转", "°", -180.0, 180.0, 5.0, 0.0, 74)), 1):
                grid.addWidget(QLabel(text), 0, column)
                spin = QDoubleSpinBox()
                spin.setRange(low, high)
                spin.setSingleStep(step)
                spin.setValue(value)
                spin.setSuffix(suffix)
                spin.setFixedWidth(width)
                setattr(self, "%s_%s" % (prefix, "scale" if text == "缩放"
                                        else "rotation" if text == "旋转"
                                        else text.lower()), spin)
                grid.addWidget(spin, 1, column)
            layout.addLayout(grid)

        self.img2img_check = QCheckBox("启用单镜图生图细节扩展")
        self.img2img_check.setChecked(True)
        layout.addWidget(self.img2img_check)
        row = QHBoxLayout()
        row.addWidget(_label("每镜扩展张数", "Hint"))
        self.expand_spin = QSpinBox()
        self.expand_spin.setRange(0, 50)
        self.expand_spin.setValue(3)
        row.addWidget(self.expand_spin)
        if hasattr(self, "single_expand_spin"):
            self.expand_spin.valueChanged.connect(
                self.single_expand_spin.setValue)
            self.single_expand_spin.valueChanged.connect(
                self.expand_spin.setValue)
            self.single_expand_spin.setValue(self.expand_spin.value())
        self.expand_external = QCheckBox("扩展使用外部 AI（更稳，可能计费）")
        self.expand_external.setToolTip("使用配置的外部 OpenAI 兼容 API 生成扩展提示词")
        row.addWidget(self.expand_external)
        row.addWidget(_label("基础重绘幅度", "Hint"))
        self.img2img_denoise = QDoubleSpinBox()
        self.img2img_denoise.setRange(0.15, 0.9)
        self.img2img_denoise.setSingleStep(0.05)
        self.img2img_denoise.setValue(0.35)
        row.addWidget(self.img2img_denoise)
        row.addStretch(1)
        layout.addLayout(row)
        img_hint = _label(
            "扩展提示词由 AI 根据当前镜生成；关键帧先生成，后续每张以上一张为底图，"
            "保持角色、环境和主要动作不变，只追加细节。单图不受上下镜限制；"
            "多镜只把下一镜作为上限约束，只做单镜扩展，不做镜头间过渡。", "Hint")
        img_hint.setWordWrap(True)
        layout.addWidget(img_hint)

        self.sequence_mode_check = QCheckBox("序列模式（关键帧从起始状态开始）")
        self.sequence_mode_check.setToolTip(
            "开启后 AI 多生成一个起始状态：第 1 张作为关键帧，后续按顺序推进；"
            "分镜原文不会被覆盖。关闭时第 1 张仍是原分镜终态。")
        self.img2img_check.toggled.connect(self._sync_sequence_mode)
        layout.addWidget(self.sequence_mode_check)
        sequence_hint = _label(
            "适合抽插、拔出、射精、余韵需要明显过程的镜头；普通扩图已回退"
            "上一版 0.65-0.85，序列仍用 0.82-0.92 多张递进；保留原机位、"
            "景别、场景和姿势大类；下一镜上限对所有题材通用，"
            "下一镜没发生的动作/伤害/道具/场景变化不会提前；"
            "总张数仍然是 1 + 每镜扩展张数。", "Hint")
        sequence_hint.setWordWrap(True)
        layout.addWidget(sequence_hint)

        self.cross_shot_check = QCheckBox("跨镜沿用上一镜画面")
        self.cross_shot_check.setToolTip(
            "同一场景的下一镜以上一镜成品为底图，低重绘保持背景和人物连续；"
            "换场景、双人镜头或单图模式不会启用")
        layout.addWidget(self.cross_shot_check)
        row = QHBoxLayout()
        row.addWidget(_label("跨镜重绘幅度", "Hint"))
        self.cross_shot_denoise = QDoubleSpinBox()
        self.cross_shot_denoise.setRange(0.15, 0.8)
        self.cross_shot_denoise.setSingleStep(0.05)
        self.cross_shot_denoise.setValue(0.35)
        row.addWidget(self.cross_shot_denoise)
        row.addStretch(1)
        layout.addLayout(row)
        cross_hint = _label(
            "建议 0.25-0.45；过高会失去承接，过低会几乎复制上一镜。", "Hint")
        cross_hint.setWordWrap(True)
        layout.addWidget(cross_hint)

        layout.addWidget(_label("输出名称（可空，自动生成）"))
        self.output_name = QLineEdit()
        layout.addWidget(self.output_name)
        self.variants_spin.valueChanged.connect(self._update_generation_count)
        self.expand_spin.valueChanged.connect(self._update_generation_count)
        self.img2img_check.toggled.connect(self._update_generation_count)
        self.chk_selected.toggled.connect(self._update_generation_count)
        self._update_generation_count()
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

    def _build_continuity_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        self.auto_continuity_check = QCheckBox(
            "自动连贯模式（模型优先外部 AI）")
        self.auto_continuity_check.setToolTip(
            "生成分镜后自动提取角色/场景锚点和每镜台账；渲染前自动质检修复；"
            "渲染后自动联系表和相似度")
        self.auto_continuity_check.toggled.connect(
            self._on_auto_continuity_toggled)
        layout.addWidget(self.auto_continuity_check)
        auto_hint = _label(
            "开启后优先使用设置里的外部 OpenAI 兼容模型；没有配置时改用本地 Ollama。",
            "Hint")
        auto_hint.setWordWrap(True)
        layout.addWidget(auto_hint)
        layout.addWidget(_label("角色锚点（补充，英文标签）"))
        self.continuity_character = QPlainTextEdit()
        self.continuity_character.setFixedHeight(72)
        self.continuity_character.setPlaceholderText(
            "silver hair, red eyes, tall, large breasts, tattoo；每镜追加，不替代角色标签")
        layout.addWidget(self.continuity_character)
        layout.addWidget(_label("场景锚点（补充，英文标签）"))
        self.continuity_scene = QPlainTextEdit()
        self.continuity_scene.setFixedHeight(58)
        self.continuity_scene.setPlaceholderText(
            "bedroom, night, warm lamp, rain outside；换场景前请手动更新")
        layout.addWidget(self.continuity_scene)
        layout.addWidget(_label("连续性台账（英文标签）"))
        self.continuity_state = QPlainTextEdit()
        self.continuity_state.setFixedHeight(86)
        self.continuity_state.setPlaceholderText(
            "torn stockings, sweat, cum on thigh, exhausted；这些会追加到每镜")
        layout.addWidget(self.continuity_state)
        layout.addWidget(_label("禁止变化 / 额外负面词（英文标签）"))
        self.continuity_negative = QPlainTextEdit()
        self.continuity_negative.setFixedHeight(58)
        self.continuity_negative.setPlaceholderText(
            "different hairstyle, different location, extra characters")
        layout.addWidget(self.continuity_negative)
        layout.addWidget(_label("镜头语法", "Section"))
        self.continuity_auto = QCheckBox("新分镜自动分配景别和机位")
        self.continuity_auto.setChecked(True)
        layout.addWidget(self.continuity_auto)
        row = QHBoxLayout()
        row.addWidget(_label("语法风格", "Hint"))
        self.continuity_style = SearchComboBox()
        self.continuity_style.setItems(GRAMMAR_STYLE_CHOICES)
        row.addWidget(self.continuity_style, 1)
        layout.addLayout(row)
        self.btn_regenerate_grammar = QPushButton("按当前分镜重新分配镜头语法")
        self.btn_regenerate_grammar.clicked.connect(self.regenerate_shot_grammar)
        layout.addWidget(self.btn_regenerate_grammar)
        quality_row = QHBoxLayout()
        self.btn_quality_check = QPushButton("运行连贯质检")
        self.btn_quality_check.clicked.connect(self.run_quality_check)
        quality_row.addWidget(self.btn_quality_check)
        self.btn_quality_repair = QPushButton("质检并自动修复")
        self.btn_quality_repair.clicked.connect(self.run_quality_repair)
        quality_row.addWidget(self.btn_quality_repair)
        layout.addLayout(quality_row)
        self.contact_sheet_auto = QCheckBox("渲染完成后自动生成联系表")
        self.contact_sheet_auto.setChecked(True)
        layout.addWidget(self.contact_sheet_auto)
        sheet_row = QHBoxLayout()
        self.btn_contact_sheet = QPushButton("生成联系表")
        self.btn_contact_sheet.clicked.connect(
            lambda: self.generate_contact_sheet(False))
        sheet_row.addWidget(self.btn_contact_sheet)
        self.btn_face_sheet = QPushButton("生成人脸抽检表")
        self.btn_face_sheet.clicked.connect(
            lambda: self.generate_contact_sheet(True))
        sheet_row.addWidget(self.btn_face_sheet)
        layout.addLayout(sheet_row)
        self.similarity_auto = QCheckBox("渲染后自动做角色相似度抽检")
        layout.addWidget(self.similarity_auto)
        self.btn_similarity = QPushButton("角色/画面相似度（CLIP）")
        self.btn_similarity.clicked.connect(self.run_similarity_check)
        layout.addWidget(self.btn_similarity)
        hint = _label(
            "连续性标签会追加到每镜，不会覆盖角色/动作/服装状态机；"
            "分镜表新增“景别 / 机位”两列，可直接编辑；角色参考表在“角色”页设置。"
            "CLIP 相似度以角色参考图（没有则用第一张成品）为基准，"
            "会同时受服装和背景影响；低于 0.55 建议人工检查。",
            "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
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
        self.log_view.setMaximumBlockCount(1500)
        self.log_view.clear()
        self.bottom_tabs.addTab(self.log_view, "日志")

        gallery_panel = QWidget()
        gallery_layout = QVBoxLayout(gallery_panel)
        gallery_layout.setContentsMargins(0, 0, 0, 0)
        gallery_tools = QHBoxLayout()
        self.gallery_filter = QComboBox()
        self.gallery_filter.addItem("全部", "all")
        self.gallery_filter.addItem("仅收藏", "favorite")
        self.gallery_filter.addItem("未收藏", "plain")
        self.gallery_filter.currentIndexChanged.connect(
            self._apply_gallery_filter)
        gallery_tools.addWidget(self.gallery_filter)
        self.gallery_sort = QComboBox()
        self.gallery_sort.addItem("按镜头", "index")
        self.gallery_sort.addItem("按名称", "name")
        self.gallery_sort.addItem("收藏优先", "favorite")
        self.gallery_sort.currentIndexChanged.connect(self._sort_gallery)
        gallery_tools.addWidget(self.gallery_sort)
        gallery_tools.addStretch(1)
        self.gallery_count = QLabel("0 张")
        gallery_tools.addWidget(self.gallery_count)
        gallery_layout.addLayout(gallery_tools)

        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(110, 110))
        self.gallery.setGridSize(QSize(128, 136))
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setMovement(QListView.Movement.Static)
        self.gallery.setSpacing(6)
        self.gallery.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.gallery.setMinimumHeight(90)
        gallery_panel.setMinimumHeight(0)
        self.bottom_tabs.setMinimumHeight(120)
        self.gallery.itemDoubleClicked.connect(self._open_gallery_item)
        self.gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.gallery.customContextMenuRequested.connect(self._gallery_menu)
        gallery_layout.addWidget(self.gallery, 1)
        self.bottom_tabs.addTab(gallery_panel, "画廊")
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
        self.expand_spin.setValue(int(img2img.get("expansions", 3)))
        self.sequence_mode_check.setChecked(bool(
            img2img.get("sequence_mode", False))
            and self.img2img_check.isChecked())
        self.expand_external.setChecked(bool(img2img.get(
            "external_ai", bool(self.cfg.external_llm.base_url
                               and self.cfg.external_llm.api_key
                               and self.cfg.external_llm.model))))
        self.cross_shot_check.setChecked(bool(img2img.get("cross_shot", False)))
        self.cross_shot_denoise.setValue(float(
            img2img.get("cross_shot_denoise", 0.35)))
        self._set_pose_settings(settings.get("pose") or {})
        self._set_style_profile_settings(template.get("style_profile") or {})
        self._set_continuity_settings(template.get("continuity") or {})
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
        self._populate_model_configs()

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

    def _populate_model_configs(self) -> None:
        self._model_config_by_id = {
            str(config.get("id") or ""): config
            for config in self.model_configs}
        self._loading_model_config = True
        self.model_config_combo.blockSignals(True)
        try:
            self.model_config_combo.clear()
            self.model_config_combo.addItem("自定义 / 手动参数", "")
            for config in self.model_configs:
                config_id = str(config.get("id") or "")
                if not config_id:
                    continue
                self.model_config_combo.addItem(
                    str(config.get("label") or config_id), config_id)
        finally:
            self.model_config_combo.blockSignals(False)
            self._loading_model_config = False

    def _sync_model_config_to_checkpoint(self, *_args, apply: bool = False) -> None:
        if getattr(self, "_loading_model_config", False):
            return
        checkpoint = self.ckpt_combo.currentValue()
        config = find_model_config(self.model_configs, checkpoint)
        config_id = str(config.get("id") or "") if config else ""
        self._loading_model_config = True
        self.model_config_combo.blockSignals(True)
        try:
            self.model_config_combo.selectValue(config_id)
        finally:
            self.model_config_combo.blockSignals(False)
            self._loading_model_config = False
        if apply and config:
            self._apply_model_config(config)

    def _on_model_config_activated(self, *_args) -> None:
        self._on_model_config_changed()

    def _on_checkpoint_changed(self, *_args) -> None:
        if getattr(self, "_loading_model_config", False):
            return
        config = find_model_config(
            self.model_configs, self.ckpt_combo.currentValue())
        if config:
            self._apply_model_config(config)
        else:
            self._sync_model_config_to_checkpoint()

    def _on_model_config_changed(self, *_args) -> None:
        if getattr(self, "_loading_model_config", False):
            return
        config_id = str(self.model_config_combo.currentData() or "")
        config = getattr(self, "_model_config_by_id", {}).get(config_id)
        if config:
            self._apply_model_config(config)

    def _apply_model_config(self, config: dict[str, Any]) -> None:
        self._loading_model_config = True
        try:
            config_id = str(config.get("id") or "")
            if config_id:
                self.model_config_combo.selectValue(config_id)
            self._ensure_combo_value(
                self.ckpt_combo, str(config.get("model") or ""))
            self.clip_skip.setValue(int(config.get("clip_skip", -2)))
            width = int(config.get("width", 832))
            height = int(config.get("height", 1216))
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
            res_index = self.res_combo.findData((width, height))
            if res_index >= 0:
                self.res_combo.setCurrentIndex(res_index)
            self.steps_spin.setValue(int(config.get("steps", 28)))
            self.cfg_spin.setValue(float(config.get("cfg", 5.0)))
            self.sampler_combo.selectValue(
                str(config.get("sampler") or "euler_ancestral"))
            self.scheduler_combo.selectValue(
                str(config.get("scheduler") or "normal"))
            hires = config.get("hires") or {}
            self.hires_check.setChecked(bool(hires.get("enabled", False)))
            self.hires_scale.setValue(float(hires.get("scale", 1.5)))
            self.hires_steps.setValue(int(hires.get("steps", 20)))
            self.hires_denoise.setValue(float(hires.get("denoise", 0.4)))
            upscaler = str(config.get("upscaler") or "").strip()
            if upscaler:
                self.upscaler_combo.selectValue(upscaler)
        finally:
            self._loading_model_config = False
        self.append_log("已加载模型配置：%s" % (
            config.get("label") or config.get("id") or config.get("model")))

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
        current_pose = self.pose_controlnet.currentValue() or ""
        pose_names = [
            name for name in self.assets.controlnets
            if "openpose" in name.lower() or "open pose" in name.lower()
            or "pose" in name.lower()]
        self.pose_controlnet.setValues(
            self._merge_values(pose_names, [current_pose]))
        if current_pose:
            self.pose_controlnet.selectValue(current_pose)
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

    def _lora_label_source(self, name: str) -> str:
        return lora_display_label(name)

    def _lora_label_text(self, name: str) -> str:
        source = self._lora_label_source(name)
        return self._lora_label_translations.get(source, source)

    def _lora_tables(self) -> tuple[QTableWidget, ...]:
        return (self.lora_table, self.style_lora_table, self.body_lora_table,
                self.action_lora_table, self.clothing_lora_table)

    def _apply_lora_label_translations(self, mapping: dict[str, str]) -> None:
        for table in self._lora_tables():
            table.blockSignals(True)
            try:
                for row in range(table.rowCount()):
                    item = table.item(row, 0)
                    if not item:
                        continue
                    name = str(item.data(Qt.ItemDataRole.UserRole) or "")
                    source = self._lora_label_source(name)
                    value = mapping.get(source, "")
                    if not value or value == source:
                        continue
                    self._lora_label_translations[source] = value
                    item.setText(value)
            finally:
                table.blockSignals(False)

    def _translate_lora_labels(self) -> None:
        labels: list[str] = []
        seen: set[str] = set()
        for table in self._lora_tables():
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if not item:
                    continue
                source = self._lora_label_source(
                    str(item.data(Qt.ItemDataRole.UserRole) or ""))
                if (source and source not in seen
                        and re.search(r"[A-Za-z]", source)
                        and not re.search(r"[\u4e00-\u9fff]", source)):
                    seen.add(source)
                    labels.append(source)
        if not labels:
            return
        cache = load_tag_cache(self._tag_cache_path)
        cached = {label: cache[label] for label in labels if label in cache}
        if cached:
            self._apply_lora_label_translations(cached)
        missing = [label for label in labels if label not in cache]
        if not missing:
            return
        model = self._llm()
        if not model:
            return
        if self._lora_label_worker and self._lora_label_worker.isRunning():
            self._lora_label_pending = True
            return
        worker = TagTranslateWorker(self.cfg, model, missing,
                                    self._tag_cache_path, batch_size=20)
        worker.batch.connect(self._apply_lora_label_translations)
        worker.done.connect(self._apply_lora_label_translations)
        worker.failed.connect(lambda msg: self.append_log("LoRA 名称翻译失败：%s" % msg))
        worker.finished.connect(self._on_lora_label_translate_finished)
        self._lora_label_worker = worker
        worker.start()

    def _on_lora_label_translate_finished(self) -> None:
        self._lora_label_worker = None
        if self._lora_label_pending:
            self._lora_label_pending = False
            QTimer.singleShot(0, self._translate_lora_labels)

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
                item = QTableWidgetItem(self._lora_label_text(name))
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
                names.append(self._lora_key(name))
            return names

        character = (scan_scope(char_dir) if char_dir
                     else [self._lora_key(name) for name in fallback
                           if not is_style_lora(name)])
        styles = (scan_scope(style_dir) if style_dir
                  else [self._lora_key(name) for name in fallback
                        if is_style_lora(name)])
        body = scan_scope(body_dir)
        action = scan_scope(action_dir)
        clothing = scan_scope(clothing_dir)

        def name_key(name: str) -> str:
            return self._lora_key(name).lower()

        scoped_sets = [
            {name_key(name) for name in values}
            for values in (body, action, clothing)
        ]
        scoped = set().union(*scoped_sets) if scoped_sets else set()
        if scoped:
            character = [name for name in character if name_key(name) not in scoped]
            styles = [name for name in styles if name_key(name) not in scoped]

        if char_dir:
            character_set = {name_key(name) for name in character}
            styles = [name for name in styles if name_key(name) not in character_set]
        if style_dir:
            style_set = {name_key(name) for name in styles}
            character = [name for name in character if name_key(name) not in style_set]

        comfy_keys = {name_key(name) for name in comfy}
        for name in configured:
            key = name_key(name)
            if key in scoped:
                continue
            if comfy_keys:
                if key not in comfy_keys:
                    continue
            else:
                path = self._resolve_lora_path(name)
                if not path or not Path(path).is_file():
                    continue
            in_styles = any(name_key(value) == key for value in styles)
            in_character = any(name_key(value) == key for value in character)
            target_style = in_styles or (not in_character and is_style_lora(name))
            canonical = self._lora_key(name)
            if target_style and not in_styles:
                styles.append(canonical)
            elif not target_style and not in_character:
                character.append(canonical)

        def unique(values: list[str]) -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            for value in values:
                key = name_key(value)
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
        QTimer.singleShot(0, self._translate_lora_labels)

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
        if item.tableWidget() is self.lora_table:
            self._sync_character_tags()
        self._save_ui_state()

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
        if self.assets.detectors:
            # ComfyUI's object_info is authoritative: local files that the
            # UltralyticsDetectorProvider cannot actually load must not appear.
            detectors = list(dict.fromkeys(self.assets.detectors))
        else:
            detectors = filter_detector_models(
                self.cfg.comfy.base_dir,
                local_detectors(self.cfg.comfy.base_dir))
        detectors = [
            name for name in detectors
            if not name.replace("\\", "/").lower().startswith("segm/")
        ]
        valid_by_name = {Path(name).name: name for name in detectors}
        for old_key, saved in list(state.items()):
            if old_key in detectors:
                continue
            migrated = valid_by_name.get(Path(old_key).name)
            if not migrated:
                continue
            current = state.get(migrated) or {}
            if saved.get("checked") and not current.get("checked"):
                state[migrated] = dict(saved)
            state.pop(old_key, None)
        choices = build_detailer_choices(detectors)
        if choices:
            self.detailer_hint.setText(
                "已扫描到 %d 个 BBOX 检测模型（segm 分割模型不用于 FaceDetailer）" % len(choices))
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
            "appearance": self.single_appearance.toPlainText().strip(),
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
        if fields["appearance"]:
            parts.append("外貌身材：%s" % self._resolved_appearance("single"))
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
        self.single_appearance.setPlainText(str(fields.get("appearance", "")))
        self.single_clothing.setPlainText(str(fields.get("clothing", "")))
        self.single_scene.setText(str(fields.get("scene", "")))
        self.single_desc.setPlainText(str(fields.get("plot", "")))
        self.single_extra.setPlainText(str(fields.get("extra", "")))

    @staticmethod
    def _fields_have_content(fields: dict[str, Any]) -> bool:
        return any(str(value or "").strip() for value in fields.values())

    def copy_single_to_story(self) -> None:
        source = self._single_fields()
        if not self._fields_have_content(source):
            QMessageBox.information(self, "提示", "单图没有可复制的自然语言输入。")
            return
        if self._fields_have_content(self._story_fields()):
            answer = QMessageBox.question(
                self, "复制到连续剧情",
                "连续剧情已有输入，确定用单图内容覆盖吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._set_story_fields(source)
        self.append_log("已把单图自然语言输入复制到连续剧情。")
        self.statusBar().showMessage("已复制到连续剧情")

    def copy_story_to_single(self) -> None:
        source = self._story_fields()
        if not self._fields_have_content(source):
            QMessageBox.information(self, "提示", "连续剧情没有可复制的自然语言输入。")
            return
        if self._fields_have_content(self._single_fields()):
            answer = QMessageBox.question(
                self, "复制到单图",
                "单图已有输入，确定用连续剧情内容覆盖吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._set_single_fields(source)
        self.append_log("已把连续剧情自然语言输入复制到单图。")
        self.statusBar().showMessage("已复制到单图")

    def _story_fields(self) -> dict[str, str]:
        return {
            "role": self.story_role.toPlainText().strip(),
            "appearance": self.story_appearance.toPlainText().strip(),
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
        if fields["appearance"]:
            parts.append("外貌身材：%s" % self._resolved_appearance("story"))
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
        fields = {"role": "", "appearance": "", "clothing": "", "scene": "",
                  "plot": "", "extra": ""}
        aliases = (
            ("外貌身材", "appearance"), ("角色外貌", "appearance"),
            ("人物外貌", "appearance"), ("外貌", "appearance"),
            ("外形", "appearance"), ("身材", "appearance"), ("体型", "appearance"),
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
        self.story_appearance.setPlainText(str(fields.get("appearance", "")))
        self.story_clothing.setPlainText(str(fields.get("clothing", "")))
        self.story_scene.setText(str(fields.get("scene", "")))
        self.story_premise.setPlainText(str(fields.get("plot", "")))
        self.story_extra.setPlainText(str(fields.get("extra", "")))

    def _style_profile_settings(self) -> dict[str, Any]:
        return normalize_style_profile({
            "id": self.style_profile_combo.currentValue(),
            "use_prompt": self.style_profile_prompt.isChecked(),
            "use_negative": self.style_profile_negative.isChecked(),
            "use_suffix": self.style_profile_suffix.isChecked(),
        })

    def _set_style_profile_settings(self, value: Any) -> None:
        profile = normalize_style_profile(value)
        previous = self._loading_style_profile
        self._loading_style_profile = True
        try:
            self.style_profile_combo.selectValue(profile["id"])
            self.style_profile_prompt.setChecked(profile["use_prompt"])
            self.style_profile_negative.setChecked(profile["use_negative"])
            self.style_profile_suffix.setChecked(profile["use_suffix"])
            self._on_style_profile_changed()
        finally:
            self._loading_style_profile = previous

    def _on_style_profile_changed(self, _index: int | None = None) -> None:
        profile_id = str(self.style_profile_combo.currentValue())
        profile = get_style_profile(profile_id)
        active = profile_id != "none"
        for box in (self.style_profile_prompt, self.style_profile_negative,
                    self.style_profile_suffix):
            box.setEnabled(active)
        hint = str(profile.get("description") or "")
        if profile.get("recommended"):
            hint += "\n推荐：%s" % profile["recommended"]
        self.style_profile_hint.setText(hint)
        if not self._loading_style_profile and not self._restoring_state:
            self._apply_style_profile_preset(profile_id)

    @staticmethod
    def _match_combo_value(combo: SearchComboBox, hints: list[str]) -> str:
        values: list[str] = []
        for index in range(combo.count()):
            data = combo.itemData(index)
            values.append(str(data if data is not None else combo.itemText(index)))
        for hint in hints:
            needle = str(hint).strip().lower()
            if not needle:
                continue
            for value in values:
                if needle in value.lower():
                    combo.selectValue(value)
                    return value
        return ""

    def _match_style_lora(self, hints: list[str]) -> str:
        candidates: list[str] = []
        for row in range(self.style_lora_table.rowCount()):
            item = self.style_lora_table.item(row, 0)
            if item:
                candidates.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        candidates.extend(str(name) for name in self.assets.loras)
        base = self.cfg.comfy.base_dir.strip()
        if base:
            candidates.extend(self._scan_model_dir(
                str(Path(base) / "models" / "loras"),
                {".safetensors", ".ckpt", ".pt"}))
        seen: set[str] = set()
        unique: list[str] = []
        for name in candidates:
            key = self._lora_key(name)
            if name and key not in seen:
                seen.add(key)
                unique.append(name)
        for hint in hints:
            needle = str(hint).strip().lower()
            if not needle:
                continue
            for name in unique:
                if needle in name.lower():
                    return name
        return ""

    def _apply_style_profile_preset(self, profile_id: str) -> None:
        settings = style_profile_apply_settings({"id": profile_id})
        label = str(get_style_profile(profile_id).get("label") or profile_id)
        applied: list[str] = []
        missing: list[str] = []
        for box in (self.style_profile_prompt, self.style_profile_negative,
                    self.style_profile_suffix):
            if profile_id != "none":
                box.setChecked(True)

        checkpoint = self._match_combo_value(
            self.ckpt_combo, list(settings.get("checkpoint_hints") or []))
        if checkpoint:
            applied.append("底模 %s" % checkpoint)
        elif settings.get("checkpoint_hints"):
            missing.append("底模")

        upscaler = self._match_combo_value(
            self.upscaler_combo, list(settings.get("upscaler_hints") or []))
        if upscaler:
            applied.append("放大 %s" % upscaler)
        elif settings.get("upscaler_hints"):
            missing.append("放大模型")

        if "width" in settings and "height" in settings:
            self.width_spin.setValue(int(settings["width"]))
            self.height_spin.setValue(int(settings["height"]))
            index = self.res_combo.findData(
                (self.width_spin.value(), self.height_spin.value()))
            if index >= 0:
                self.res_combo.setCurrentIndex(index)
        for key, spin in (("steps", self.steps_spin), ("cfg", self.cfg_spin)):
            if key in settings:
                spin.setValue(float(settings[key]) if key == "cfg"
                              else int(settings[key]))
        if settings.get("sampler"):
            self._ensure_combo_value(self.sampler_combo, str(settings["sampler"]))
        if settings.get("scheduler"):
            self._ensure_combo_value(self.scheduler_combo, str(settings["scheduler"]))

        hires = settings.get("hires") or {}
        if hires:
            self.hires_check.setChecked(bool(hires.get("enabled", True)))
            if "scale" in hires:
                self.hires_scale.setValue(float(hires["scale"]))
            if "denoise" in hires:
                self.hires_denoise.setValue(float(hires["denoise"]))
            if "steps" in hires:
                self.hires_steps.setValue(int(hires["steps"]))

        hints = list(settings.get("style_lora_hints") or [])
        style_lora = self._match_style_lora(hints)
        strength = float(settings.get("style_lora_strength", 0.5))
        self._apply_table_loras(
            self.style_lora_table, {style_lora: strength} if style_lora else {})
        if style_lora:
            applied.append("风格 LoRA %s (%.2f)" % (style_lora, strength))
        elif hints:
            missing.append("风格 LoRA")

        summary = "已自动应用：%s" % (" / ".join(applied) or "无可用推荐项")
        if missing:
            summary += "\n缺失，已保留当前设置：%s" % " / ".join(missing)
        self.style_profile_hint.setText(
            self.style_profile_hint.text() + "\n" + summary)
        self.append_log("已切换风格方案「%s」：%s" % (label, summary.replace("\n", "；")))
        self.statusBar().showMessage("已应用风格方案：%s" % label)

    def _on_auto_continuity_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self.cross_shot_check.setChecked(True)
        self.contact_sheet_auto.setChecked(True)
        self.similarity_auto.setChecked(True)
        if self._external_llm_ready():
            self.expand_external.setChecked(True)
        if not self._restoring_state:
            self.append_log(
                "自动连贯模式已开启：外部模型优先，渲染前自动修复，"
                "渲染后自动联系表/相似度。")

    def _continuity_settings(self) -> dict[str, Any]:
        return normalize_continuity({
            "character": self.continuity_character.toPlainText(),
            "scene": self.continuity_scene.toPlainText(),
            "state": self.continuity_state.toPlainText(),
            "negative": self.continuity_negative.toPlainText(),
            "grammar": {
                "auto": self.continuity_auto.isChecked(),
                "style": self.continuity_style.currentValue(),
            },
        })

    def _set_continuity_settings(self, value: Any) -> None:
        data = normalize_continuity(value)
        for field, text in (
                (self.continuity_character, data["character"]),
                (self.continuity_scene, data["scene"]),
                (self.continuity_state, data["state"]),
                (self.continuity_negative, data["negative"])):
            field.blockSignals(True)
            try:
                field.setPlainText(text)
            finally:
                field.blockSignals(False)
        self.continuity_auto.setChecked(data["grammar"]["auto"])
        self.continuity_style.selectValue(data["grammar"]["style"])

    def _style_positive(self) -> str:
        style = apply_style_profile(
            self.template.get("style") or {}, self._style_profile_settings())
        return str(style.get("positive", ""))

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

    def _appearance_field(self, mode: str | None = None) -> str:
        if mode == "story":
            return self.story_appearance.toPlainText().strip()
        if mode == "single":
            return self.single_appearance.toPlainText().strip()
        return (self.story_appearance.toPlainText().strip()
                or self.single_appearance.toPlainText().strip())

    def _resolved_appearance(self, mode: str | None = None) -> str:
        text = self._appearance_field(mode)
        if not text or not re.search(r"[\u4e00-\u9fff]", text):
            return text
        parts = [part.strip() for part in re.split(r"[；;\n]+", text) if part.strip()]
        values: list[str] = []
        for part in parts:
            match = re.match(r"^([^:：]{1,24})[:：]\s*(.+)$", part)
            value = match.group(2) if match else part
            resolved = self._resolve_chinese_texts([value])
            english = resolved[0] if resolved and resolved[0] else ""
            values.append("%s：%s" % (match.group(1), english or value)
                          if match else (english or value))
        return "；".join(values) or text

    def _combined_character_tags(self, mode: str | None = None) -> str:
        if mode == "story":
            role = self.story_role.toPlainText().strip()
        elif mode == "single":
            role = self.single_role.toPlainText().strip()
        else:
            role = (self.story_role.toPlainText().strip()
                    or self.single_role.toPlainText().strip())
        appearance = self._resolved_appearance(mode)
        if mode == "story" and (":" in appearance or "：" in appearance):
            appearance = ""
        activation = self._character_tags()
        return append_tags(append_tags(role, activation), appearance)

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
        character = self._selected_loras(self.lora_table)
        for item in character:
            item["character"] = True
        result = character + self._selected_loras(self.style_lora_table)
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
        available = set(self.assets.detectors)
        result = []
        for key, box, spin, choice in self.detailer_rows:
            if not box.isChecked():
                continue
            if available and choice["detector"] not in available:
                self.append_log(
                    "跳过 ComfyUI 不支持的检测模型：%s" % choice["detector"])
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

    def _pose_settings(self) -> dict[str, Any]:
        return {
            "enabled": self.pose_check.isChecked(),
            "controlnet": self.pose_controlnet.currentValue(),
            "preset": self.pose_preset.currentValue(),
            "strength": self.pose_strength.value(),
            "custom": self._pose_custom,
            "reference": {
                "pair": self.pose_pair_ref.text().strip(),
                "girl": self.pose_girl_ref.text().strip(),
                "boy": self.pose_boy_ref.text().strip(),
            },
            "adjust": {
                "girl": {
                    "dx": self.pose_girl_x.value() / 100.0,
                    "dy": self.pose_girl_y.value() / 100.0,
                    "scale": self.pose_girl_scale.value(),
                    "rotation": self.pose_girl_rotation.value(),
                },
                "boy": {
                    "dx": self.pose_boy_x.value() / 100.0,
                    "dy": self.pose_boy_y.value() / 100.0,
                    "scale": self.pose_boy_scale.value(),
                    "rotation": self.pose_boy_rotation.value(),
                },
            },
        }

    def _set_pose_settings(self, pose: dict[str, Any]) -> None:
        custom = pose.get("custom")
        if isinstance(custom, dict):
            self._pose_custom = custom
        enabled = pose.get("enabled")
        if enabled is None:
            enabled = getattr(self.cfg.generation, "pose_enabled", True)
        controlnet = pose.get("controlnet")
        if controlnet is None:
            controlnet = getattr(self.cfg.generation, "pose_controlnet", "")
        preset = pose.get("preset")
        if preset is None:
            preset = getattr(self.cfg.generation, "pose_preset", "auto")
        strength = pose.get("strength")
        if strength is None:
            strength = getattr(self.cfg.generation, "pose_strength", 0.7)
        self.pose_check.setChecked(bool(enabled))
        self.pose_controlnet.selectValue(str(controlnet))
        self.pose_preset.selectValue(str(preset))
        self.pose_strength.setValue(float(strength))
        reference = pose.get("reference") or {}
        self.pose_pair_ref.setText(str(reference.get("pair") or ""))
        self.pose_girl_ref.setText(str(reference.get("girl") or ""))
        self.pose_boy_ref.setText(str(reference.get("boy") or ""))
        adjust = pose.get("adjust") or {}
        for key, prefix in (("girl", "pose_girl"), ("boy", "pose_boy")):
            values = adjust.get(key) or {}
            getattr(self, prefix + "_x").setValue(
                float(values.get("dx") or 0.0) * 100.0)
            getattr(self, prefix + "_y").setValue(
                float(values.get("dy") or 0.0) * 100.0)
            getattr(self, prefix + "_scale").setValue(
                float(values.get("scale") or 1.0))
            getattr(self, prefix + "_rotation").setValue(
                float(values.get("rotation") or 0.0))

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
                "expansions": self.expand_spin.value(),
                "external_ai": self.expand_external.isChecked(),
                "cross_shot": self.cross_shot_check.isChecked(),
                "cross_shot_denoise": self.cross_shot_denoise.value(),
                "sequence_mode": self.sequence_mode_check.isChecked(),
            },
            "pose": self._pose_settings(),
        }

    def _build_project(self, mode: str, shots: list[dict[str, Any]], text: str) -> dict[str, Any]:
        data = copy.deepcopy(self.template)
        data["model"] = self.ckpt_combo.currentValue() or self.template.get("model", "")
        data["clip_skip"] = self.clip_skip.value()
        data["loras"] = self._build_loras()
        data.pop("lora", None)
        data["character"] = copy.deepcopy(self.template.get("character") or {})
        data["character"]["tags"] = self._combined_character_tags(mode)
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
        data["style_profile"] = self._style_profile_settings()
        data["continuity"] = self._continuity_settings()
        data["auto_continuity"] = self.auto_continuity_check.isChecked()
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
        project["output_dir"] = self.cfg.comfy.output_dir
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
            character_tags=self._combined_character_tags("single"),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora(),
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "single", text, single_options=options,
                              use_external=external)
        worker.single_ready.connect(self._on_single_prompt)
        worker.failed.connect(self._on_prompt_failed)
        worker.canceled.connect(self._on_prompt_canceled)
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
        if (not external and self.auto_continuity_check.isChecked()
                and self._external_llm_ready()):
            external = True
            self.append_log("自动连贯模式：优先使用外部模型生成分镜。")
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
            character_tags=self._combined_character_tags("story"),
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
        worker.canceled.connect(self._on_prompt_canceled)
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
        self._start_auto_continuity(shots)

    def _external_llm_ready(self) -> bool:
        external = self.cfg.external_llm
        return bool(external.base_url and external.model)

    def _start_auto_continuity(self, shots: list[dict[str, Any]]) -> None:
        if not self.auto_continuity_check.isChecked():
            return
        if self.continuity_worker and self.continuity_worker.isRunning():
            return
        premise = self._story_premise_text()
        if not premise:
            return
        use_external = self._external_llm_ready()
        model = self.cfg.external_llm.model if use_external else self._llm()
        if not model:
            self.append_log("自动连贯跳过：没有可用的外部模型或 Ollama 模型。")
            return
        worker = ContinuityWorker(
            self.cfg, premise, shots, self._combined_character_tags("story"),
            model, use_external)
        worker.done.connect(self._on_auto_continuity_ready)
        worker.failed.connect(self._on_auto_continuity_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_auto_continuity_finished)
        self.continuity_worker = worker
        self._set_generation_enabled(False)
        self.statusBar().showMessage("正在自动提取连贯性台账...")
        self.append_log("自动连贯：使用%s模型提取角色/场景/台账。" % (
            "外部" if use_external else "本地"))
        worker.start()

    def _on_auto_continuity_ready(self, data: dict[str, Any]) -> None:
        current = self._continuity_settings()
        current.update({
            "character": str(data.get("character") or ""),
            "scene": str(data.get("scene") or ""),
            "state": "",
            "negative": str(data.get("negative") or ""),
        })
        self._set_continuity_settings(current)
        ledger = {
            str(item.get("id") or ""): item
            for item in (data.get("ledger") or []) if isinstance(item, dict)
        }
        self._syncing_shots = True
        try:
            for row in range(self.shot_table.rowCount()):
                id_item = self.shot_table.item(row, 1)
                prompt_item = self.shot_table.item(row, 3)
                if not id_item or not prompt_item:
                    continue
                entry = ledger.get(id_item.text())
                if not entry:
                    continue
                prompt_item.setData(
                    CONTINUITY_STATE_ROLE, str(entry.get("state") or ""))
                prompt_item.setData(
                    CONTINUITY_SCENE_ROLE, str(entry.get("scene") or ""))
        finally:
            self._syncing_shots = False
        self._autosave_generated_story()
        self.append_log(
            "自动连贯完成：角色锚点、场景锚点、%d 镜台账已写入。" % len(ledger))
        self.statusBar().showMessage("自动连贯完成，可检查后出图")

    def _on_auto_continuity_failed(self, message: str) -> None:
        self.append_log("自动连贯提取失败：%s" % message)
        self.statusBar().showMessage("自动连贯提取失败，保留手动锚点")

    def _on_auto_continuity_finished(self) -> None:
        self.continuity_worker = None
        self._set_generation_enabled(True)

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
            prompt_item.setData(BEAT_ROLE, str(shot.get("beat", "")))
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
            prompt_item.setData(CLOTHING_DETAILS_ROLE, json.dumps(
                shot.get("clothing_details") or {}, ensure_ascii=False))
            prompt_item.setData(PROMPT_GROUPS_ROLE, json.dumps(
                shot.get("prompt_groups") or [], ensure_ascii=False))
            prompt_item.setData(CONTINUITY_STATE_ROLE,
                                str(shot.get("continuity_state") or ""))
            prompt_item.setData(CONTINUITY_SCENE_ROLE,
                                str(shot.get("continuity_scene") or ""))
            prompt_item.setData(KEYFRAME_PROMPT_ROLE,
                                str(shot.get("keyframe_prompt") or ""))
            prompt_item.setData(AI_EXPANSIONS_ROLE, json.dumps(
                shot.get("ai_expansions") or [], ensure_ascii=False))
            self.shot_table.setItem(row, 3, prompt_item)
            self.shot_table.setItem(row, 4, QTableWidgetItem(
                str(shot.get("shot_size") or "")))
            self.shot_table.setItem(row, 5, QTableWidgetItem(
                str(shot.get("camera_angle") or "")))
        finally:
            self._syncing_shots = False

    def _fill_shot_table(self, shots: list[dict[str, Any]]) -> None:
        self._selected_shot_ids = []
        self.shot_table.setRowCount(0)
        for shot in shots:
            row = self.shot_table.rowCount()
            self.shot_table.insertRow(row)
            self._set_shot_row(row, shot)
        if self.shot_table.rowCount():
            self.shot_table.setCurrentCell(0, 3)
        self._update_shot_stats()

    def _autofill_shot_grammar(self, overwrite: bool = False) -> None:
        if not hasattr(self, "continuity_auto"):
            return
        settings = self._continuity_settings()
        if not settings["grammar"]["auto"] and not overwrite:
            return
        total = self.shot_table.rowCount()
        self.shot_table.blockSignals(True)
        try:
            for row in range(total):
                size_item = self.shot_table.item(row, 4)
                angle_item = self.shot_table.item(row, 5)
                if (not overwrite and size_item and angle_item
                        and size_item.text().strip() and angle_item.text().strip()):
                    continue
                grammar = auto_shot_grammar(row, total, settings)
                if not size_item:
                    size_item = QTableWidgetItem()
                    self.shot_table.setItem(row, 4, size_item)
                if not angle_item:
                    angle_item = QTableWidgetItem()
                    self.shot_table.setItem(row, 5, angle_item)
                size_item.setText(grammar["shot_size"])
                angle_item.setText(grammar["camera_angle"])
        finally:
            self.shot_table.blockSignals(False)

    def regenerate_shot_grammar(self) -> None:
        if not self.shot_table.rowCount():
            QMessageBox.information(self, "提示", "还没有分镜。")
            return
        self._autofill_shot_grammar(overwrite=True)
        self.append_log("已按当前镜头语法重新分配景别和机位。")

    def _quality_report_for_current(self):
        mode = self._current_mode()
        if mode == "single":
            prompt_zh = self.single_prompt.toPlainText().strip()
            prompt = self._resolve_single_en()
            shots = [{"id": "01", "name": "single", "prompt": prompt,
                      "prompt_zh": prompt_zh or prompt}] if prompt else []
            text = self._single_input_text() or prompt_zh or prompt
        else:
            shots = self._collect_shots(False, allow_empty=True)
            text = self._story_premise_text() or "quality check"
        project = self._build_project(mode, shots, text or "quality check")
        return check_project(project)

    def run_quality_check(self) -> None:
        try:
            report = self._quality_report_for_current()
        except Exception as exc:
            QMessageBox.warning(self, "质检失败", str(exc))
            return
        for line in report.lines():
            self.append_log("质检 · " + line)
        if report.critical:
            QMessageBox.warning(self, "连贯质检", format_report(report))
        elif report.warnings:
            QMessageBox.information(self, "连贯质检", format_report(report))
        else:
            QMessageBox.information(
                self, "连贯质检", "未发现连续性问题。\n" + format_report(report))
        self.statusBar().showMessage("连贯质检完成")

    def _resolve_output_image(self, image: Any) -> Path | None:
        text = str(image or "").strip()
        if not text:
            return None
        direct = Path(text)
        if direct.is_file():
            return direct
        if self.cfg.comfy.output_dir:
            local = Path(self.cfg.comfy.output_dir) / Path(
                text.replace("\\", "/"))
            if local.is_file():
                return local
        return None

    def _contact_sheet_paths(
            self, results: list[dict[str, Any]] | None = None) -> list[Path]:
        if results is not None:
            images = [item.get("image") for item in results
                      if item.get("state") == "done" and item.get("image")]
        else:
            images = list((self.project or {}).get("outputs") or [])
        paths: list[Path] = []
        seen: set[str] = set()
        for image in images:
            path = self._resolve_output_image(image)
            if path and str(path) not in seen:
                seen.add(str(path))
                paths.append(path)
        return paths

    def generate_contact_sheet(self, faces: bool = False,
                               silent: bool = False,
                               results: list[dict[str, Any]] | None = None) -> Path | None:
        paths = self._contact_sheet_paths(results)
        if not paths:
            if not silent:
                QMessageBox.information(self, "提示", "当前项目还没有可用的成品图。")
            return None
        project_id = str((self.project or {}).get("id") or "")
        folder = (self.cfg.root / "projects" / project_id / "contact_sheets"
                  if project_id else self.cfg.root / "contact_sheets")
        prefix = "faces" if faces else "storyboard"
        target = folder / ("%s_%s_%s.png" % (
            prefix, time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4]))
        title = "%s · %s" % (
            (self.project or {}).get("name") or "Project",
            "Face / Character Check" if faces else "Storyboard")
        try:
            if faces:
                build_face_sheet(paths, target, title=title)
            else:
                build_contact_sheet(paths, target, title=title)
        except Exception as exc:
            self.append_log("联系表生成失败：%s" % exc)
            if not silent:
                QMessageBox.warning(self, "联系表生成失败", str(exc))
            return None
        self.append_log("已生成%s：%s" % (
            "人脸抽检表" if faces else "联系表", target))
        self.statusBar().showMessage(
            "已生成%s" % ("人脸抽检表" if faces else "联系表"))
        if not silent:
            QMessageBox.information(
                self, "联系表", "已生成：\n%s" % target)
        return target

    def _maybe_auto_contact_sheet(self, results: list[dict[str, Any]]) -> None:
        if not self.contact_sheet_auto.isChecked():
            return
        self.generate_contact_sheet(False, silent=True, results=results)

    def _vision_reference(self, paths: list[Path]) -> Path:
        text = self.char_ref.text().strip()
        if text:
            path = Path(text)
            if path.is_file():
                return path
            resolved = self._resolve_output_image(text)
            if resolved:
                return resolved
        return paths[0]

    def run_similarity_check(self, silent: bool = False,
                             results: list[dict[str, Any]] | None = None) -> None:
        if self.vision_worker and self.vision_worker.isRunning():
            return
        paths = self._contact_sheet_paths(results)
        if not paths:
            if not silent:
                QMessageBox.information(self, "提示", "当前项目还没有可用的成品图。")
            return
        reference = self._vision_reference(paths)
        ready, reason = vision_ready(
            self.cfg.root, self.cfg.comfy.python, self.cfg.comfy.base_dir)
        if not ready:
            if "open_clip" in reason:
                if silent:
                    self.append_log(
                        "角色相似度抽检跳过：首次需要手动点击按钮安装 open_clip 依赖。")
                    return
                answer = QMessageBox.question(
                    self, "首次使用",
                    "首次使用角色相似度抽检需要安装 open_clip 依赖到应用数据目录，"
                    "约几十 MB。是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            else:
                if not silent:
                    QMessageBox.warning(self, "无法检测", reason)
                self.append_log("角色相似度检测不可用：%s" % reason)
                return
        self.append_log("角色相似度基准图：%s" % reference)
        if not self.char_ref.text().strip():
            self.append_log("未设置角色参考图，使用第一张成品作为基准。")
        worker = VisionWorker(self.cfg, reference, paths, device="cpu")
        worker.log.connect(self.append_log)
        worker.done.connect(
            lambda scores: self._on_vision_done(scores, silent))
        worker.failed.connect(
            lambda message: self._on_vision_failed(message, silent))
        worker.finished.connect(self._on_vision_finished)
        self.vision_worker = worker
        self.btn_similarity.setEnabled(False)
        self.statusBar().showMessage("正在检测角色相似度...")
        worker.start()

    def _on_vision_done(self, scores: list[dict[str, Any]],
                        silent: bool) -> None:
        text = format_similarity(scores)
        self.append_log("角色相似度抽检：\n" + text)
        low = [item for item in scores
               if item.get("score") is not None and float(item["score"]) < 0.55]
        if silent:
            message = "角色相似度抽检完成"
            if low:
                message += "，%d 张偏低，详见日志" % len(low)
            self.statusBar().showMessage(message)
            return
        if low:
            QMessageBox.warning(self, "角色相似度偏低", text)
        else:
            QMessageBox.information(self, "角色相似度抽检", text)

    def _on_vision_failed(self, message: str, silent: bool) -> None:
        self.append_log("角色相似度抽检失败：%s" % message)
        if not silent:
            QMessageBox.warning(self, "角色相似度抽检失败", message)
        self.statusBar().showMessage("角色相似度抽检失败")

    def _on_vision_finished(self) -> None:
        self.vision_worker = None
        self.btn_similarity.setEnabled(True)

    def run_quality_repair(self) -> None:
        try:
            project = self._build_project(
                self._current_mode(),
                self._collect_shots(False, allow_empty=True)
                if self._current_mode() == "story"
                else [{"id": "01", "name": "single",
                       "prompt": self._resolve_single_en()}],
                self._current_text() or "quality repair")
            repaired, changes = repair_project(project)
        except Exception as exc:
            QMessageBox.warning(self, "修复失败", str(exc))
            return
        if not changes:
            QMessageBox.information(self, "自动修复", "没有发现可安全自动修复的问题。")
            return
        self._apply_repaired_project(repaired)
        for change in changes:
            self.append_log("自动修复 · " + change)
        self.statusBar().showMessage("已自动修复 %d 项" % len(changes))
        QMessageBox.information(
            self, "自动修复", "已修复：\n" + "\n".join("- " + item for item in changes))

    def _apply_repaired_project(self, project: dict[str, Any],
                                replace_table: bool = True) -> None:
        character = project.get("character") or {}
        if not character.get("use_ipadapter"):
            self.char_ref.clear()
        style_ref = project.get("style_ref") or {}
        if style_ref.get("enabled") is False:
            self.style_ref_check.setChecked(False)
        shots = project.get("shots") or []
        if replace_table and shots:
            self._fill_shot_table(shots)

    def _preflight_quality(self, project: dict[str, Any]) -> bool:
        report = check_project(project)
        for line in report.lines():
            if line.startswith("提示："):
                continue
            self.append_log("质检 · " + line)
        if report.warnings and not report.critical:
            self.statusBar().showMessage(
                "连贯质检发现 %d 个警告，详见日志" % len(report.warnings))
        if not report.critical:
            return True
        answer = QMessageBox.warning(
            self, "连贯质检发现严重问题",
            format_report(report) + "\n\n仍要继续生成吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _row_data(self, row: int) -> dict[str, Any]:
        lock_item = self.shot_table.item(row, 0)
        prompt_item = self.shot_table.item(row, 3)
        states: dict[str, Any] = {}
        details: dict[str, Any] = {}
        prompt_groups: list[Any] = []
        ai_expansions: list[Any] = []
        if prompt_item:
            raw_states = prompt_item.data(CHARACTER_STATES_ROLE)
            if isinstance(raw_states, str) and raw_states.strip():
                try:
                    parsed = json.loads(raw_states)
                    states = parsed if isinstance(parsed, dict) else {}
                except (TypeError, ValueError):
                    states = {}
            raw_details = prompt_item.data(CLOTHING_DETAILS_ROLE)
            if isinstance(raw_details, str) and raw_details.strip():
                try:
                    parsed = json.loads(raw_details)
                    details = parsed if isinstance(parsed, dict) else {}
                except (TypeError, ValueError):
                    details = {}
            raw_groups = prompt_item.data(PROMPT_GROUPS_ROLE)
            if isinstance(raw_groups, str) and raw_groups.strip():
                try:
                    parsed = json.loads(raw_groups)
                    prompt_groups = parsed if isinstance(parsed, list) else []
                except (TypeError, ValueError):
                    prompt_groups = []
            raw_expansions = prompt_item.data(AI_EXPANSIONS_ROLE)
            if isinstance(raw_expansions, str) and raw_expansions.strip():
                try:
                    parsed = json.loads(raw_expansions)
                    ai_expansions = parsed if isinstance(parsed, list) else []
                except (TypeError, ValueError):
                    ai_expansions = []
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
            "beat": (prompt_item.data(BEAT_ROLE) or "") if prompt_item else "",
            "clothing": (prompt_item.data(CLOTHING_ROLE) or "") if prompt_item else "",
            "characters": (prompt_item.data(CHARACTERS_ROLE) or "") if prompt_item else "",
            "character_states": states,
            "clothing_details": details,
            "prompt_groups": prompt_groups,
            "scene": (prompt_item.data(SCENE_ROLE) or "") if prompt_item else "",
            "continuity_state": (prompt_item.data(CONTINUITY_STATE_ROLE) or ""
                                 if prompt_item else ""),
            "continuity_scene": (prompt_item.data(CONTINUITY_SCENE_ROLE) or ""
                                 if prompt_item else ""),
            "keyframe_prompt": (prompt_item.data(KEYFRAME_PROMPT_ROLE) or ""
                                if prompt_item else ""),
            "ai_expansions": ai_expansions,
            "shot_size": (self.shot_table.item(row, 4).text()
                          if self.shot_table.item(row, 4) else ""),
            "camera_angle": (self.shot_table.item(row, 5).text()
                             if self.shot_table.item(row, 5) else ""),
        }

    def _on_shot_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_shots or item.column() != 3:
            return
        self._syncing_shots = True
        try:
            item.setData(PROMPT_GROUPS_ROLE, "[]")
        finally:
            self._syncing_shots = False
        self._update_shot_stats()

    def _sync_sequence_mode(self, enabled: bool) -> None:
        self.sequence_mode_check.setEnabled(enabled)
        if not enabled:
            self.sequence_mode_check.setChecked(False)

    def _update_generation_count(self) -> None:
        if not hasattr(self, "generation_count_label"):
            return
        if self._current_mode() == "single":
            shots = 1
            unit = "1 个提示词"
        else:
            if self.chk_selected.isChecked():
                shots = len(self._selected_shot_rows())
            else:
                shots = self.shot_table.rowCount()
            unit = "%d 个分镜" % shots
        expansions = self.expand_spin.value() if self.img2img_check.isChecked() else 0
        variants = self.variants_spin.value()
        total = shots * variants * (1 + expansions)
        self.generation_count_label.setText(
            "预计生成 %d 张 = %s × %d 变体 × (1 + %d 张单镜扩展)" % (
                total, unit, variants, expansions))

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
        self._update_generation_count()

    @staticmethod
    def _effective_prompt_blocks(project: dict[str, Any],
                                 shot: dict[str, Any]) -> str:
        blocks: list[str] = []
        keyframe_prompt = str(shot.get("keyframe_prompt") or "").strip()
        if keyframe_prompt:
            keyframe_shot = dict(shot)
            keyframe_shot["prompt"] = keyframe_prompt
            positive, negative = compose_prompts(project, keyframe_shot)
            blocks.append("【关键帧 · 起始状态】\n正向：\n%s\n\n负向：\n%s" % (
                positive, negative))
            for index, prompt in enumerate(shot.get("ai_expansions") or [], 1):
                sequence_shot = dict(shot)
                sequence_shot["prompt"] = str(prompt)
                positive, negative = compose_prompts(project, sequence_shot)
                blocks.append("【序列 %d】\n正向：\n%s\n\n负向：\n%s" % (
                    index, positive, negative))
            return "\n\n".join(blocks)
        positive, negative = compose_prompts(project, shot)
        blocks.append("正向：\n%s\n\n负向：\n%s" % (positive, negative))
        return "\n\n".join(blocks)

    def show_effective_prompt(self) -> None:
        mode = self._current_mode()
        if mode == "single":
            prompt = self._resolve_single_en()
            if not prompt and not self._has_activation_tags():
                QMessageBox.information(self, "提示", "单图还没有提示词或激活标签。")
                return
            shot_data = {
                "id": "01", "name": "single", "prompt": prompt,
                "prompt_zh": self.single_prompt.toPlainText().strip() or prompt,
            }
            project = self._build_project(
                "single", [shot_data], self._single_input_text() or "single")
            shot = (project.get("shots") or [shot_data])[0]
        else:
            if not self.shot_table.rowCount():
                QMessageBox.information(self, "提示", "还没有分镜。")
                return
            row = self.shot_table.currentRow()
            if row < 0:
                row = 0
            shots = self._collect_shots(False, allow_empty=True)
            if row >= len(shots):
                return
            project = self._build_project(
                "story", shots, self._story_premise_text() or "story")
            shot = project["shots"][row]
        text = self._effective_prompt_blocks(project, shot)
        dialog = QDialog(self)
        dialog.setWindowTitle("实际正负提示词")
        layout = QVBoxLayout(dialog)
        hint = _label(
            "下面是实际送入 ComfyUI 的正负提示词，已包含配置的正负词、风格词、"
            "连贯锚点和镜头语法。", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        layout.addWidget(edit, 1)
        row_buttons = QHBoxLayout()
        copy_button = QPushButton("复制全部")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(edit.toPlainText()))
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)
        row_buttons.addWidget(copy_button)
        row_buttons.addStretch(1)
        row_buttons.addWidget(close_button)
        layout.addLayout(row_buttons)
        dialog.resize(820, 620)
        dialog.exec()

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
                    prompt_item.setData(PROMPT_GROUPS_ROLE, "[]")
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
                "script": item.get("script", ""),
                "phase": item.get("phase", ""),
                "beat": item.get("beat", ""),
                "shot_size": item.get("shot_size", ""),
                "camera_angle": item.get("camera_angle", ""),
                "continuity_state": item.get("continuity_state", ""),
                "continuity_scene": item.get("continuity_scene", ""),
                "keyframe_prompt": item.get("keyframe_prompt", ""),
                "ai_expansions": item.get("ai_expansions") or [],
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
            character_tags=self._combined_character_tags("single"),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora(),
        )
        self._set_generation_enabled(False)
        worker = PromptWorker(self.cfg, "expand", self._single_input_text() or prompt,
                              story_options=options, initial_shots=initial)
        worker.story_ready.connect(self._on_expanded)
        worker.failed.connect(self._on_prompt_failed)
        worker.canceled.connect(self._on_prompt_canceled)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_prompt_worker_finished)
        self.prompt_worker = worker
        self.statusBar().showMessage("Ollama 模型正在扩写分镜…")
        worker.start()

    def _on_expanded(self, shots: list[dict[str, str]]) -> None:
        self._fill_shot_table(shots)
        self._set_story_fields(self._single_fields())
        self.story_shots.setValue(len(shots))
        self.btn_mode_single.setChecked(False)
        self.btn_mode_story.setChecked(True)
        self._switch_mode(1)
        self.append_log("已改写为 %d 镜" % len(shots))
        self._autosave_generated_story()
        self._start_auto_continuity(shots)

    def _on_prompt_canceled(self, message: str) -> None:
        self._render_after_prompt = False
        self._update_partial_button()
        self.append_log(message or "已打断生成")
        self.statusBar().showMessage("已打断生成")

    def _on_prompt_failed(self, message: str) -> None:
        self._render_after_prompt = False
        self._update_partial_button()
        self.append_log("生成提示词失败：%s" % message)
        self.statusBar().showMessage("生成失败（可点“恢复上次未完成分镜”）")
        QMessageBox.warning(self, "生成失败", message)

    def _on_prompt_worker_finished(self) -> None:
        busy = any(
            worker is not None and worker.isRunning()
            for worker in (self.render_worker, self.reference_sheet_worker,
                           self.continuity_worker, self.expansion_worker,
                           self.vision_worker))
        if not busy:
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

    def _on_shot_cell_clicked(self, row: int, column: int) -> None:
        if column == 0 and row >= 0:
            index = self.shot_table.model().index(row, 0)
            self.shot_table.selectionModel().select(
                index, QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows)
            self._remember_shot_selection()

    def _remember_shot_selection(self) -> None:
        rows = sorted({index.row() for index in self.shot_table.selectedIndexes()})
        ids = []
        for row in rows:
            item = self.shot_table.item(row, 1)
            if item and item.text().strip():
                ids.append(item.text().strip())
        if ids:
            self._selected_shot_ids = ids

    def _selected_shot_rows(self) -> list[int]:
        ids = set(self._selected_shot_ids)
        rows: list[int] = []
        if ids:
            rows = [
                row for row in range(self.shot_table.rowCount())
                if (self.shot_table.item(row, 1)
                    and self.shot_table.item(row, 1).text().strip() in ids)]
        if not rows:
            rows = sorted({
                index.row() for index in self.shot_table.selectedIndexes()})
        if getattr(self, "chk_selected", None) is not None \
                and self.chk_selected.isChecked():
            checked = [
                row for row in range(self.shot_table.rowCount())
                if (self.shot_table.item(row, 0)
                    and self.shot_table.item(row, 0).checkState()
                    == Qt.CheckState.Checked)]
            rows = sorted(set(rows) | set(checked))
        return rows

    def _collect_shots(self, selected_only: bool, allow_empty: bool = False) -> list[dict[str, Any]]:
        rows = self._selected_shot_rows() if selected_only \
            else list(range(self.shot_table.rowCount()))
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
                "beat": data.get("beat", ""),
                "clothing": data.get("clothing", ""),
                "characters": data.get("characters", ""),
                "character_states": data.get("character_states") or {},
                "clothing_details": data.get("clothing_details") or {},
                "prompt_groups": data.get("prompt_groups") or [],
                              "scene": data.get("scene", ""),
                              "continuity_state": data.get("continuity_state", ""),
                              "continuity_scene": data.get("continuity_scene", ""),
                              "keyframe_prompt": data.get("keyframe_prompt", ""),
                              "ai_expansions": data.get("ai_expansions") or [],
                              "shot_size": data.get("shot_size", ""),
                              "camera_angle": data.get("camera_angle", ""),
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
                          "beat": data.get("beat", ""),
                          "clothing": data.get("clothing", ""),
                          "characters": data.get("characters", ""),
                          "character_states": data.get("character_states") or {},
                          "clothing_details": data.get("clothing_details") or {},
                          "prompt_groups": data.get("prompt_groups") or [],
                          "scene": data.get("scene", ""),
                          "continuity_state": data.get("continuity_state", ""),
                          "continuity_scene": data.get("continuity_scene", ""),
                          "keyframe_prompt": data.get("keyframe_prompt", ""),
                          "ai_expansions": data.get("ai_expansions") or [],
                          "shot_size": data.get("shot_size", ""),
                          "camera_angle": data.get("camera_angle", ""),
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
            all_shots = self._collect_shots(False, allow_empty=activation)
            selected_only = self.chk_selected.isChecked()
            if selected_only:
                selected_ids = {
                    self.shot_table.item(row, 1).text().strip()
                    for row in self._selected_shot_rows()
                    if self.shot_table.item(row, 1)
                    and self.shot_table.item(row, 1).text().strip()}
                shots = [
                    shot for shot in all_shots
                    if str(shot.get("id") or "").strip() in selected_ids]
            else:
                shots = all_shots
            if not shots and activation:
                shots = [{"id": "01", "name": "activation", "prompt": "", "prompt_zh": ""}]
            if not shots:
                QMessageBox.information(self, "提示", "没有可生成的镜头，请先生成或填写分镜。")
                return
            if selected_only:
                self.append_log("仅生成选中镜头：%d 个（%s）" % (
                    len(shots), ", ".join(
                        str(shot.get("id") or "") for shot in shots)))
            text = self._story_premise_text() or all_shots[0]["prompt"] or "activation"

        project = self._build_project(mode, all_shots if mode != "single" else shots, text)
        previous_prefix = str((self.project or {}).get("prefix") or "")
        self._reuse_project_identity(project)
        if self.auto_continuity_check.isChecked():
            project, repairs = repair_project(project)
            if repairs:
                self._apply_repaired_project(project, replace_table=False)
                if mode != "single" and selected_only:
                    ids = {str(shot.get("id") or "") for shot in shots}
                    shots = [
                        shot for shot in (project.get("shots") or [])
                        if str(shot.get("id") or "") in ids]
                else:
                    shots = list(project.get("shots") or shots)
            for change in repairs:
                self.append_log("自动连贯修复 · " + change)
        if not self._preflight_quality(project):
            return
        prefix = self._run_prefix_for(mode, text)
        project["prefix"] = prefix
        if prefix != previous_prefix:
            project["outputs"] = []
        self.project = project
        if prefix != previous_prefix:
            self._load_gallery(project)
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
        img2img = settings.get("img2img") or {}
        expansions = (int(img2img.get("expansions", 3))
                      if img2img.get("enabled", True) else 0)
        model = self._llm()
        use_external = False
        sequence_mode = bool((settings.get("img2img") or {}).get(
            "sequence_mode", False))
        external = self.cfg.external_llm
        external_ready = bool(
            external.base_url and external.api_key and external.model)
        if self.expand_external.isChecked() and external_ready:
            model = external.model
            use_external = True
        elif not model and external_ready:
            model = external.model
            use_external = True
        if sequence_mode and external_ready and not use_external:
            model = external.model
            use_external = True
            self.append_log("序列模式优先使用外部模型生成扩展状态。")
        if expansions > 0 and model:
            self._pending_render = (self.project, shots, expansions)
            worker = ExpansionWorker(
                self.cfg, shots, expansions, model=model,
                use_external=use_external, sequence=sequence_mode)
            worker.done.connect(self._on_expansions_ready)
            worker.failed.connect(self._on_expansions_failed)
            worker.canceled.connect(self._on_expansions_canceled)
            worker.log.connect(self.append_log)
            worker.finished.connect(lambda: setattr(self, "expansion_worker", None))
            self.expansion_worker = worker
            self._set_generation_enabled(False)
            self.btn_cancel.setEnabled(True)
            self.statusBar().showMessage("AI expanding prompts...")
            self.append_log("AI expansion: %s, %d prompts per shot" % (
                model, expansions))
            worker.start()
            return
        if expansions > 0:
            self.append_log("No AI model available; skipping expansion.")
        self._start_render_tasks(self.project, shots, None)

    def _on_expansions_ready(self, expansions: dict[str, list[str]]) -> None:
        pending = self._pending_render
        self._pending_render = None
        if not pending:
            return
        project, shots, count = pending
        self.append_log("AI expansion finished: %d shots" % len(expansions))
        self._start_render_tasks(project, shots, expansions)

    def _on_expansions_failed(self, message: str) -> None:
        pending = self._pending_render
        self._pending_render = None
        self.append_log("AI expansion failed; rendering keyframes only: %s" % message)
        if pending:
            project, shots, _count = pending
            self._start_render_tasks(project, shots, None)
        else:
            self._set_generation_enabled(True)

    def _on_expansions_canceled(self, message: str) -> None:
        self._pending_render = None
        self.append_log(message or "AI expansion canceled")
        self._set_generation_enabled(True)
        self.btn_cancel.setEnabled(False)

    def _sync_sequence_to_table(self, shots: list[dict[str, Any]]) -> None:
        by_id = {str(shot.get("id") or ""): shot for shot in shots}
        self._syncing_shots = True
        try:
            for row in range(self.shot_table.rowCount()):
                id_item = self.shot_table.item(row, 1)
                prompt_item = self.shot_table.item(row, 3)
                if not id_item or not prompt_item:
                    continue
                shot = by_id.get(id_item.text())
                if not shot:
                    continue
                prompt_item.setData(
                    KEYFRAME_PROMPT_ROLE, str(shot.get("keyframe_prompt") or ""))
                prompt_item.setData(AI_EXPANSIONS_ROLE, json.dumps(
                    shot.get("ai_expansions") or [], ensure_ascii=False))
        finally:
            self._syncing_shots = False

    def _start_render_tasks(self, project: dict[str, Any],
                            shots: list[dict[str, Any]],
                            expansions: dict[str, list[str]] | None) -> None:
        settings = project["settings"]
        seed_mode = settings.get("seed_mode", "increment")
        base_seed = int(settings.get("base_seed", 1))
        count = 0
        sequence = bool((settings.get("img2img") or {}).get(
            "sequence_mode", False))
        requested = int((settings.get("img2img") or {}).get("expansions", 0))
        if not expansions:
            for shot in shots:
                shot.pop("keyframe_prompt", None)
                shot.pop("ai_expansions", None)
        if expansions:
            for shot in shots:
                prompts = expansions.get(str(shot.get("id") or ""), [])
                if sequence and len(prompts) >= requested + 1:
                    shot["keyframe_prompt"] = prompts[0]
                    shot["ai_expansions"] = prompts[1:requested + 1]
                else:
                    shot.pop("keyframe_prompt", None)
                    shot["ai_expansions"] = prompts
                    if sequence and prompts:
                        self.append_log(
                            "镜头 %s 序列数据不足，回退普通扩展。" % shot.get("id"))
                count = max(count, len(shot.get("ai_expansions") or []))
        self._sync_sequence_to_table(shots)
        tasks = build_tasks(project, shots, int(project["variants"]),
                            seed_mode, base_seed, expansions=count)
        if seed_mode == "increment" and tasks:
            next_seed = (base_seed + len(tasks)) % (2 ** 31)
            self.seed_spin.setValue(next_seed)
            self.append_log("Seeds: %d..%d, next %d" % (
                tasks[0].seed, tasks[-1].seed, next_seed))
        self.tasks_by_id = {task.id: task for task in tasks}
        self.previews.clear()
        self.final_bytes.clear()
        self._reset_queue(tasks)
        self.progress.setValue(0)
        self.preview_info.setText("Preparing...")
        self.current_task_id = tasks[0].id if tasks else None

        hires = bool(settings.get("hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, project, tasks, hires)
        worker.task_updated.connect(self._on_task_update)
        worker.preview.connect(self._on_preview)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_render_finished)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(lambda: self._set_generation_enabled(True))
        self.render_worker = worker
        self._set_generation_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.statusBar().showMessage("Rendering %d images" % len(tasks))
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
        if self.project is not None and task.image:
            self._append_project_output(task.image)
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

    def _gallery_metadata(self, *, task: Any = None, shot: dict[str, Any] | None = None,
                          image: str = "", label: str = "",
                          path: str = "") -> dict[str, Any]:
        project = self.project or {}
        settings = project.get("settings") or {}
        shot = shot or {}
        return {
            "label": label or str(shot.get("name") or ""),
            "image": image,
            "path": path,
            "shot_id": str(shot.get("id") or getattr(task, "shot_id", "") or ""),
            "phase": str(shot.get("phase") or ""),
            "cast": str(shot.get("cast") or ""),
            "script": str(shot.get("script") or shot.get("outline") or ""),
            "prompt": str(shot.get("prompt") or ""),
            "negative": str(shot.get("negative") or ""),
            "model": str(project.get("model") or ""),
            "seed": str(getattr(task, "seed", "") or shot.get("seed") or ""),
            "width": str(settings.get("width") or ""),
            "height": str(settings.get("height") or ""),
            "created": str(project.get("updated") or project.get("created") or ""),
        }

    def _gallery_metadata_text(self, meta: dict[str, Any]) -> str:
        rows = [
            ("镜头", meta.get("shot_id")),
            ("标签", meta.get("label")),
            ("阶段", meta.get("phase")),
            ("Cast", meta.get("cast")),
            ("Seed", meta.get("seed")),
            ("模型", meta.get("model")),
            ("尺寸", "%sx%s" % (meta.get("width"), meta.get("height"))),
            ("时间", meta.get("created")),
            ("文件", meta.get("path")),
            ("图片引用", meta.get("image")),
            ("Script", meta.get("script")),
            ("Prompt", meta.get("prompt")),
            ("Negative", meta.get("negative")),
        ]
        return "\n".join("%s: %s" % (key, value)
                         for key, value in rows if value)

    def _append_project_output(self, image: str) -> None:
        if self.project is None or not image:
            return
        outputs = list(self.project.get("outputs") or [])
        normalized = image.replace("\\", "/")
        if normalized not in {str(item).replace("\\", "/") for item in outputs}:
            outputs.append(image)
            self.project["outputs"] = outputs

    def _make_gallery_item(self, data: bytes, meta: dict[str, Any],
                           task_id: str = "", favorite: bool = False) -> QListWidgetItem:
        image = QImage.fromData(data)
        pixmap = QPixmap.fromImage(image).scaled(
            150, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setText(meta.get("label") or Path(str(meta.get("path"))).stem)
        item.setToolTip(meta.get("path") or meta.get("image") or "")
        item.setData(GALLERY_PATH_ROLE, meta.get("path") or "")
        item.setData(GALLERY_TASK_ROLE, task_id)
        item.setData(GALLERY_IMAGE_ROLE, meta.get("image") or "")
        item.setData(GALLERY_META_ROLE, meta)
        item.setData(GALLERY_FAVORITE_ROLE, bool(favorite))
        try:
            index = int(str(meta.get("shot_id") or "0"))
        except ValueError:
            index = 0
        item.setData(GALLERY_INDEX_ROLE, index)
        if favorite:
            item.setText("★ " + item.text())
        return item

    def _add_gallery(self, task: Any, data: bytes, local: Path | None) -> None:
        image_ref = str(getattr(task, "image", "") or "")
        if image_ref and self._gallery_has_image(image_ref):
            return
        if local is None:
            cache = self.cfg.cache_dir / "gallery"
            cache.mkdir(parents=True, exist_ok=True)
            local = cache / ("%s_%s.png" % (task.label, task.id))
            local.write_bytes(data)
        meta = self._gallery_metadata(
            task=task, shot=getattr(task, "shot", None) or {},
            image=image_ref, label=str(getattr(task, "label", "") or ""),
            path=str(local))
        favorite = image_ref in set((self.project or {}).get(
            "gallery_favorites") or [])
        self.gallery.addItem(self._make_gallery_item(
            data, meta, task_id=str(getattr(task, "id", "") or ""),
            favorite=favorite))
        self._sort_gallery()
        self._refresh_gallery_count()

    def _gallery_has_image(self, image_ref: str) -> bool:
        normalized = image_ref.replace("\\", "/")
        for index in range(self.gallery.count()):
            item = self.gallery.item(index)
            if str(item.data(GALLERY_IMAGE_ROLE) or "").replace(
                    "\\", "/") == normalized:
                return True
        return False

    def _load_gallery(self, project: dict[str, Any] | None = None) -> None:
        project = project or self.project or {}
        self.gallery.clear()
        favorites = set(project.get("gallery_favorites") or [])
        shots = list(project.get("shots") or [])
        outputs = list(project.get("outputs") or [])
        prefix = str(project.get("prefix") or "").replace("\\", "/").strip("/")
        prefix_scope = prefix + "/" if prefix else ""
        seen: set[str] = set()
        for index, image in enumerate(outputs):
            normalized = str(image).replace("\\", "/")
            if prefix_scope and not normalized.startswith(prefix_scope):
                continue
            if normalized in seen:
                continue
            path = self._resolve_output_image(image)
            if path is None:
                continue
            seen.add(normalized)
            shot = shots[index] if index < len(shots) else {}
            meta = self._gallery_metadata(
                shot=shot, image=str(image),
                label=path.stem or str(shot.get("name") or ""),
                path=str(path))
            try:
                data = path.read_bytes()
            except Exception:
                continue
            self.gallery.addItem(self._make_gallery_item(
                data, meta, favorite=normalized in {
                    str(item).replace("\\", "/") for item in favorites}))
        self._sort_gallery()
        self._refresh_gallery_count()

    def _refresh_gallery_count(self) -> None:
        visible = sum(1 for index in range(self.gallery.count())
                      if not self.gallery.item(index).isHidden())
        self.gallery_count.setText("%d / %d 张" % (
            visible, self.gallery.count()))

    def _apply_gallery_filter(self, *_args) -> None:
        mode = self.gallery_filter.currentData()
        for index in range(self.gallery.count()):
            item = self.gallery.item(index)
            favorite = bool(item.data(GALLERY_FAVORITE_ROLE))
            hidden = (mode == "favorite" and not favorite) or (
                mode == "plain" and favorite)
            item.setHidden(hidden)
        self._refresh_gallery_count()

    def _sort_gallery(self, *_args) -> None:
        mode = self.gallery_sort.currentData() if hasattr(
            self, "gallery_sort") else "index"
        items = [self.gallery.takeItem(0) for _ in range(self.gallery.count())]
        if mode == "name":
            items.sort(key=lambda item: item.text().lower())
        elif mode == "favorite":
            items.sort(key=lambda item: (
                not bool(item.data(GALLERY_FAVORITE_ROLE)),
                int(item.data(GALLERY_INDEX_ROLE) or 0)))
        else:
            items.sort(key=lambda item: int(item.data(GALLERY_INDEX_ROLE) or 0))
        for item in items:
            self.gallery.addItem(item)
        self._apply_gallery_filter()

    def _gallery_item_path(self, item: QListWidgetItem) -> Path | None:
        resolved = self._resolve_output_image(item.data(GALLERY_IMAGE_ROLE))
        if resolved is not None:
            return resolved
        path = Path(str(item.data(GALLERY_PATH_ROLE) or ""))
        return path if path.is_file() else None

    def _open_gallery_item(self, item: QListWidgetItem) -> None:
        path = self._gallery_item_path(item)
        if path is None:
            QMessageBox.information(self, "提示", "找不到图片文件。")
            return
        meta = item.data(GALLERY_META_ROLE) or {}
        GalleryViewerDialog(path, self._gallery_metadata_text(meta), self).exec()

    def _gallery_selected_items(self) -> list[QListWidgetItem]:
        selected = self.gallery.selectedItems()
        return selected or ([self.gallery.currentItem()]
                            if self.gallery.currentItem() else [])

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
        self._load_gallery(None)
        clear_story_partial(self.cfg.root)
        self._update_partial_button()
        self._run_prefix = ""
        self._run_signature = ""
        self._single_prompt_en = ""
        self._single_prompt_zh = ""
        self.single_role.clear()
        self.single_appearance.clear()
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
        self.story_appearance.clear()
        self.story_clothing.clear()
        self.story_scene.clear()
        self.story_premise.clear()
        self.story_extra.clear()
        self.output_name.clear()
        self._set_continuity_settings({})
        self.shot_table.setRowCount(0)
        self._update_shot_stats()
        self.queue_table.setRowCount(0)
        self.gallery.clear()
        self._refresh_gallery_count()
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
        item = QTableWidgetItem(self._lora_label_text(name))
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
        premise = str(project.get("premise") or "")
        normalize_shot_casts(project.get("shots") or [])
        profiles = parse_character_profiles(premise)
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
        self._set_continuity_settings(project.get("continuity") or {})
        if "auto_continuity" in project:
            self.auto_continuity_check.setChecked(
                bool(project.get("auto_continuity")))
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
        self.expand_spin.setValue(int(img2img.get("expansions", 3)))
        self.sequence_mode_check.setChecked(bool(
            img2img.get("sequence_mode", False))
            and self.img2img_check.isChecked())
        self.expand_external.setChecked(bool(img2img.get(
            "external_ai", bool(self.cfg.external_llm.base_url
                               and self.cfg.external_llm.api_key
                               and self.cfg.external_llm.model))))
        self.cross_shot_check.setChecked(bool(img2img.get("cross_shot", False)))
        self.cross_shot_denoise.setValue(float(
            img2img.get("cross_shot_denoise", 0.35)))
        self._set_pose_settings(s.get("pose") or {})
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
        self._set_style_profile_settings(project.get("style_profile") or {})

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

        self._load_gallery(project)
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
        if not item.isSelected():
            self.gallery.clearSelection()
            item.setSelected(True)
        items = self._gallery_selected_items()
        favorite = bool(item.data(GALLERY_FAVORITE_ROLE))
        menu = QMenu(self)
        act_open = menu.addAction("预览")
        act_folder = menu.addAction("打开文件夹")
        act_favorite = menu.addAction("取消收藏" if favorite else "收藏")
        redraw_label = ("重绘选中 %d 张（新 seed）" % len(items)
                        if len(items) > 1 else "重绘此图（新 seed）")
        expand_label = ("扩展选中 %d 张" % len(items)
                        if len(items) > 1 else "扩展此镜头")
        act_redraw = menu.addAction(redraw_label)
        act_expand = menu.addAction(expand_label)
        act_compare = menu.addAction("对比选中")
        act_compare.setEnabled(len(items) >= 2)
        act_sheet = menu.addAction("生成拼接图")
        act_trash = menu.addAction("移到回收站")
        chosen = menu.exec(self.gallery.viewport().mapToGlobal(pos))
        if chosen is act_open:
            self._open_gallery_item(item)
        elif chosen is act_folder:
            path = self._gallery_item_path(item)
            if path is not None:
                os.startfile(str(path.parent))  # noqa: S606
        elif chosen is act_favorite:
            self._toggle_gallery_favorite(items)
        elif chosen is act_redraw:
            self._redraw_gallery_items(items)
        elif chosen is act_expand:
            self._expand_gallery_items(items)
        elif chosen is act_compare:
            self._compare_gallery(items)
        elif chosen is act_sheet:
            self._gallery_contact_sheet(items)
        elif chosen is act_trash:
            self._trash_gallery_items(items)

    def _gallery_shot(self, item: QListWidgetItem) -> dict[str, Any] | None:
        meta = item.data(GALLERY_META_ROLE) or {}
        shot_id = str(meta.get("shot_id") or "")
        return next((shot for shot in (self.project or {}).get("shots") or []
                     if str(shot.get("id") or "") == shot_id), None)

    def _expand_gallery_items(self, items: list[QListWidgetItem]) -> None:
        if (self.expansion_worker and self.expansion_worker.isRunning()) or (
                self.render_worker and self.render_worker.isRunning()):
            QMessageBox.information(self, "提示", "正在生成，请等待当前任务结束。")
            return
        if not self.project:
            QMessageBox.information(self, "提示", "没有可用的项目。")
            return
        shots: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            shot = self._gallery_shot(item)
            if shot is None:
                continue
            shot_id = str(shot.get("id") or "")
            if shot_id in seen:
                continue
            seen.add(shot_id)
            shots.append(dict(shot))
        if not shots:
            QMessageBox.information(self, "提示", "找不到对应镜头。")
            return
        count = int(self.expand_spin.value())
        if count <= 0:
            QMessageBox.information(self, "提示", "请先设置扩展张数。")
            return
        external = self.cfg.external_llm
        external_ready = bool(
            external.base_url and external.api_key and external.model)
        use_external = bool(self.expand_external.isChecked() and external_ready)
        model = external.model if use_external else self._llm()
        if not model:
            QMessageBox.information(self, "提示", "没有可用的提示词模型。")
            return
        sequence = bool((self.project.get("settings") or {}).get(
            "img2img", {}).get("sequence_mode", False))
        self._pending_gallery_expand = (shots, count)
        worker = ExpansionWorker(
            self.cfg, shots, count, model=model,
            use_external=use_external, sequence=sequence)
        worker.done.connect(self._on_gallery_expansions_ready)
        worker.failed.connect(self._on_gallery_expansions_failed)
        worker.log.connect(self.append_log)
        worker.finished.connect(lambda: setattr(self, "expansion_worker", None))
        self.expansion_worker = worker
        self._set_generation_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.append_log("画廊扩展：%d 镜，每镜 %d 张" % (len(shots), count))
        worker.start()

    def _on_gallery_expansions_ready(self, expansions: dict[str, list[str]]) -> None:
        pending = getattr(self, "_pending_gallery_expand", None)
        self._pending_gallery_expand = None
        if not pending or not self.project:
            self._set_generation_enabled(True)
            return
        shots, count = pending
        tasks = []
        for shot in shots:
            prompts = list(
                expansions.get(str(shot.get("id") or "")) or [])[:count]
            for index, prompt in enumerate(prompts, 1):
                expanded = dict(shot)
                expanded["prompt"] = prompt
                task = Task(
                    shot_id=str(shot.get("id") or ""),
                    shot_name=str(shot.get("name") or ""),
                    variant=index, seed=random.randint(0, 2 ** 31 - 1),
                    shot=expanded,
                    label="%s_gallery_e%02d_%s" % (
                        shot.get("id"), index, uuid.uuid4().hex[:4]))
                self.tasks_by_id[task.id] = task
                tasks.append(task)
        if not tasks:
            self.append_log("画廊扩展没有返回可用提示词。")
            self._set_generation_enabled(True)
            return
        hires = bool((self.project.get("settings") or {}).get(
            "hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, self.project, tasks, hires)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_gallery_redraw_finished)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(lambda: self._set_generation_enabled(True))
        self.render_worker = worker
        self.btn_cancel.setEnabled(True)
        self.append_log("画廊扩展渲染：%d 张" % len(tasks))
        worker.start()

    def _on_gallery_expansions_failed(self, message: str) -> None:
        self._pending_gallery_expand = None
        self._set_generation_enabled(True)
        self.append_log("画廊扩展失败：%s" % message)

    def _redraw_gallery_items(self, items: list[QListWidgetItem]) -> None:
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "提示", "正在生成，请等待当前任务结束。")
            return
        if not self.project:
            QMessageBox.information(self, "提示", "没有可用的项目。")
            return
        tasks = []
        for item in items:
            shot = self._gallery_shot(item)
            if shot is None:
                continue
            shot_id = str(shot.get("id") or "")
            seed = random.randint(0, 2 ** 31 - 1)
            task = Task(
                shot_id=shot_id, shot_name=str(shot.get("name") or ""),
                variant=1, seed=seed, shot=dict(shot),
                label="%s_gallery_%s" % (shot_id, uuid.uuid4().hex[:4]))
            self.tasks_by_id[task.id] = task
            tasks.append(task)
        if not tasks:
            QMessageBox.information(self, "提示", "找不到对应镜头。")
            return
        hires = bool((self.project.get("settings") or {}).get(
            "hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, self.project, tasks, hires)
        worker.task_updated.connect(self._on_task_update)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_gallery_redraw_finished)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(lambda: self._set_generation_enabled(True))
        self.render_worker = worker
        self._set_generation_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.append_log("画廊重绘：%d 张，seed %s" % (
            len(tasks), ", ".join(str(task.seed) for task in tasks)))
        worker.start()

    def _on_gallery_redraw_finished(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            if result.get("state") == "done":
                self._on_task_done(str(result.get("id") or ""))

    def _save_gallery_favorites(self) -> None:
        if self.project is None:
            return
        favorites = []
        for index in range(self.gallery.count()):
            item = self.gallery.item(index)
            if item.data(GALLERY_FAVORITE_ROLE):
                image = str(item.data(GALLERY_IMAGE_ROLE) or "")
                if image:
                    favorites.append(image)
        self.project["gallery_favorites"] = favorites
        save_project(self.project, self.cfg.root)

    def _toggle_gallery_favorite(self, items: list[QListWidgetItem]) -> None:
        if not items:
            return
        target = not bool(items[0].data(GALLERY_FAVORITE_ROLE))
        for item in items:
            item.setData(GALLERY_FAVORITE_ROLE, target)
            text = item.text()
            if target and not text.startswith("★ "):
                item.setText("★ " + text)
            elif not target and text.startswith("★ "):
                item.setText(text[2:])
        self._save_gallery_favorites()
        self._sort_gallery()

    def _compare_gallery(self, items: list[QListWidgetItem]) -> None:
        entries = []
        for item in items:
            path = self._gallery_item_path(item)
            if path is not None:
                entries.append({"path": path, "label": item.text()})
        if len(entries) < 2:
            QMessageBox.information(self, "提示", "至少选择两张图片。")
            return
        GalleryCompareDialog(entries, self).exec()

    def _gallery_contact_sheet(self, items: list[QListWidgetItem]) -> None:
        paths = [path for path in (self._gallery_item_path(item)
                                  for item in items) if path is not None]
        if not paths:
            QMessageBox.information(self, "提示", "没有可用的图片。")
            return
        project_id = str((self.project or {}).get("id") or "")
        folder = (self.cfg.root / "projects" / project_id / "contact_sheets"
                  if project_id else self.cfg.root / "contact_sheets")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("gallery_%s_%s.png" % (
            time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4]))
        title = "%s - Gallery" % ((self.project or {}).get("name") or "Project")
        try:
            build_contact_sheet(paths, target, title=title)
            self.append_log("画廊拼接图：%s" % target)
            os.startfile(str(target))  # noqa: S606
        except Exception as exc:
            QMessageBox.warning(self, "生成失败", str(exc))

    def _remove_project_output(self, image: str | Path) -> None:
        if not self.project:
            return
        target = str(image).replace("\\", "/")
        target_path = Path(target)
        target_resolved = (str(target_path.resolve()).replace("\\", "/")
                           if target_path.is_file() else "")

        def matches(item: str) -> bool:
            value = str(item).replace("\\", "/")
            if value == target:
                return True
            resolved = self._resolve_output_image(item)
            return bool(target_resolved and resolved and
                        str(resolved.resolve()).replace("\\", "/") == target_resolved)

        outputs = self.project.get("outputs") or []
        self.project["outputs"] = [item for item in outputs if not matches(item)]
        favorites = self.project.get("gallery_favorites") or []
        self.project["gallery_favorites"] = [
            item for item in favorites if not matches(item)]
        save_project(self.project, self.cfg.root)

    def _trash_gallery_items(self, items: list[QListWidgetItem]) -> None:
        if not self.project:
            QMessageBox.information(self, "提示", "先保存或打开一个项目。")
            return
        removed = 0
        for item in list(items):
            path = self._gallery_item_path(item)
            if path is None:
                continue
            try:
                dest = move_to_trash(path, self.project["id"], self.cfg.root)
            except Exception as exc:
                QMessageBox.warning(self, "移动失败", str(exc))
                continue
            image = str(item.data(GALLERY_IMAGE_ROLE) or "")
            if image:
                self._remove_project_output(image)
            task_id = str(item.data(GALLERY_TASK_ROLE) or "")
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
            removed += 1
            self.append_log("已移入回收站：%s" % dest.name)
        self._save_gallery_favorites()
        self._refresh_gallery_count()
        if removed == 0:
            QMessageBox.information(self, "提示", "找不到图片文件。")

    def _trash_gallery_item(self, item: QListWidgetItem) -> None:
        self._trash_gallery_items([item])

    def _remove_gallery_task(self, task_id: str) -> None:
        for index in range(self.gallery.count() - 1, -1, -1):
            item = self.gallery.item(index)
            if item.data(GALLERY_TASK_ROLE) == task_id:
                self.gallery.takeItem(index)
        self._refresh_gallery_count()

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
            character_tags=self._combined_character_tags(
                "story" if self.btn_mode_story.isChecked() else "single"),
            style_positive=self._style_positive(),
            strip_appearance=self._has_character_lora())
        self._rewrite_row = row
        worker.rewritten.connect(self._on_rewritten)
        worker.failed.connect(self._on_prompt_failed)
        worker.canceled.connect(self._on_prompt_canceled)
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
                    item.setData(PROMPT_GROUPS_ROLE, "[]")
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
        if done:
            self._maybe_auto_contact_sheet(results)
            if self.similarity_auto.isChecked():
                self.run_similarity_check(silent=True, results=results)

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

    def interrupt_generation(self) -> None:
        requested = False
        if self.expansion_worker and self.expansion_worker.isRunning():
            self.expansion_worker.cancel()
            requested = True
        if self.render_worker and self.render_worker.isRunning():
            self.render_worker.cancel()
            requested = True
        if self.prompt_worker and self.prompt_worker.isRunning():
            self.prompt_worker.cancel()
            requested = True
        if requested:
            self.btn_interrupt.setEnabled(False)
            self.append_log("已请求打断生成…")
            self.statusBar().showMessage("已请求打断，正在停止…")

    # ---------------------------------------------------------------- misc

    def _switch_mode(self, index: int) -> None:
        self.left_stack.setCurrentIndex(index)
        self._update_generation_count()

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
        self.btn_interrupt.setEnabled(not enabled)
        self.btn_expand.setEnabled(enabled and bool(self.single_prompt.toPlainText().strip()))

    def append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        text = str(message or "")
        if len(text) > 700:
            text = text[:700].rstrip() + " …（完整内容见落盘日志）"
        self.log_view.appendPlainText("[%s] %s" % (stamp, text))

    def open_pose_editor(self) -> None:
        from comfyui_generator.ui.pose_dialog import PoseEditorDialog

        dialog = PoseEditorDialog(self._pose_custom, self)
        if not dialog.exec():
            return
        self._pose_custom = dialog.custom_presets()
        save_pose_presets(self.cfg.root / "pose_presets.json", self._pose_custom)
        self.append_log("骨架库已保存：%d 个预设" % len(self._pose_custom))
        self.statusBar().showMessage("骨架库已保存")

    def _pick_pose_ref(self, field: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 OpenPose 骨架图", field.text().strip(),
            "图片 (*.png *.jpg *.jpeg *.webp)")
        if path:
            field.setText(path)

    def generate_character_sheet(self) -> None:
        if self.reference_sheet_worker and self.reference_sheet_worker.isRunning():
            return
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "提示", "正在生成图片，请稍后再生成参考表。")
            return
        if not self.connected:
            QMessageBox.information(self, "提示", "请先连接 ComfyUI。")
            return
        character_tags = (self._combined_character_tags("story")
                          or self._combined_character_tags("single"))
        clothing = (self.story_clothing.toPlainText().strip()
                    or self.single_clothing.toPlainText().strip())
        if not character_tags and not clothing:
            QMessageBox.information(
                self, "提示", "请先填写角色标签、外貌或初始服装。")
            return
        prompt = character_sheet_prompt(
            character_tags, clothing, self._style_positive())
        shot = {
            "id": "ref",
            "name": "character_sheet",
            "prompt": prompt,
            "prompt_zh": prompt,
            "shot_size": "full body",
            "camera_angle": "eye level",
        }
        project = self._build_project("single", [shot], "character reference sheet")
        project["prefix"] = "anime_story/ref_%s" % time.strftime("%Y%m%d_%H%M%S")
        project["continuity"] = {}
        project["character"]["use_ipadapter"] = False
        project["character"].pop("ipadapter", None)
        settings = project.setdefault("settings", {})
        settings["img2img"] = {"enabled": False, "expansions": 0}
        pose = settings.setdefault("pose", {})
        pose["enabled"] = False
        tasks = build_tasks(
            project, [shot], 1, "fixed", int(self.seed_spin.value()),
            expansions=0)
        hires = bool(settings.get("hires", {}).get("enabled", True))
        worker = RenderWorker(self.cfg, project, tasks, hires)
        worker.task_updated.connect(self._on_reference_sheet_task)
        worker.log.connect(self.append_log)
        worker.finished_ok.connect(self._on_reference_sheet_finished)
        worker.failed.connect(self._on_reference_sheet_failed)
        worker.finished.connect(self._on_reference_sheet_worker_finished)
        self.reference_sheet_worker = worker
        self.btn_character_sheet.setEnabled(False)
        self._set_generation_enabled(False)
        self.statusBar().showMessage("正在生成角色参考表...")
        self.append_log("开始生成多视图角色参考表：%s" % prompt[:220])
        worker.start()

    def _on_reference_sheet_task(self, summary: dict[str, Any]) -> None:
        if summary.get("state") in ("running", "submitted"):
            stage = summary.get("stage") or ""
            self.statusBar().showMessage(
                "角色参考表生成中%s..." % ((" · " + stage) if stage else ""))

    def _on_reference_sheet_finished(self, results: list[dict[str, Any]]) -> None:
        image = next((str(item.get("image")) for item in results
                      if item.get("state") == "done" and item.get("image")), "")
        if not image:
            self._on_reference_sheet_failed("ComfyUI 没有返回参考表图片")
            return
        try:
            path = self._save_reference_sheet(image)
        except Exception as exc:
            self._on_reference_sheet_failed("保存参考表失败：%s" % exc)
            return
        self.char_ref.setText(str(path))
        self.append_log("角色参考表已生成并自动填入：%s" % path)
        self.statusBar().showMessage("角色参考表已生成并自动填入")

    def _save_reference_sheet(self, image: str) -> Path:
        folder = Path(r"H:\ComfyUIData\output\角色参考表")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("character_sheet_%s_%s.png" % (
            time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4]))
        source = Path(self.cfg.comfy.output_dir) / Path(str(image).replace("\\", "/"))
        if source.is_file():
            target.write_bytes(source.read_bytes())
            return target
        posix = Path(str(image).replace("\\", "/"))
        client = ComfyClient(self.cfg.comfy.base_url)
        data = client.view(posix.name,
                           str(posix.parent) if str(posix.parent) != "." else "")
        target.write_bytes(data)
        return target

    def _on_reference_sheet_failed(self, message: str) -> None:
        self.append_log("角色参考表生成失败：%s" % message)
        self.statusBar().showMessage("角色参考表生成失败")

    def _on_reference_sheet_worker_finished(self) -> None:
        self.reference_sheet_worker = None
        self.btn_character_sheet.setEnabled(True)
        self._set_generation_enabled(True)

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
            "continuity": self._continuity_settings(),
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
                "cross_shot": self.cross_shot_check.isChecked(),
                "cross_shot_denoise": self.cross_shot_denoise.value(),
                "sequence_mode": self.sequence_mode_check.isChecked(),
                "expand_count": self.expand_spin.value(),
                "expand_external": self.expand_external.isChecked(),
                "pose": self._pose_settings(),
                "style_profile": self._style_profile_settings(),
                "auto_continuity": self.auto_continuity_check.isChecked(),
                "contact_sheet_auto": self.contact_sheet_auto.isChecked(),
                "similarity_auto": self.similarity_auto.isChecked(),
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
                values = [int(size) for size in sizes]
                if key == "main_vsplit":
                    max_bottom = max(120, min(170, self.height() - 220))
                    values[-1] = max(120, min(values[-1], max_bottom))
                splitter.setSizes(values)

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
            en = str(saved.get("en") or "")
            zh = str(saved.get("zh") or "")
            text = str(saved.get("text") or "")
            if name == "positive":
                en, zh, text = merge_default_positive(en, zh, text)
            setattr(self, en_attr, en)
            setattr(self, zh_attr, zh)
            attr.blockSignals(True)
            try:
                attr.setPlainText(text)
            finally:
                attr.blockSignals(False)

        self._set_continuity_settings(state.get("continuity") or {})

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
            "beat": shot.get("beat", ""),
            "continuity_state": shot.get("continuity_state", ""),
            "continuity_scene": shot.get("continuity_scene", ""),
            "keyframe_prompt": shot.get("keyframe_prompt", ""),
            "ai_expansions": shot.get("ai_expansions") or [],
            "shot_size": shot.get("shot_size", ""),
            "camera_angle": shot.get("camera_angle", ""),
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
        self.cross_shot_check.setChecked(bool(options.get("cross_shot", False)))
        self.cross_shot_denoise.setValue(float(
            options.get("cross_shot_denoise", 0.35)))
        self.sequence_mode_check.setChecked(bool(
            options.get("sequence_mode", False))
            and self.img2img_check.isChecked())
        self.expand_spin.setValue(int(options.get("expand_count", 3)))
        self.expand_external.setChecked(bool(options.get(
            "expand_external", bool(self.cfg.external_llm.base_url
                                   and self.cfg.external_llm.api_key
                                   and self.cfg.external_llm.model))))
        pose = options.get("pose")
        if not isinstance(pose, dict):
            pose = {
                "enabled": options.get("pose_enabled"),
                "controlnet": options.get("pose_controlnet"),
                "preset": options.get("pose_preset"),
                "strength": options.get("pose_strength"),
            }
        self._set_pose_settings(pose)
        self._set_style_profile_settings(options.get("style_profile") or {})
        self.auto_continuity_check.setChecked(bool(
            options.get("auto_continuity", False)))
        self.contact_sheet_auto.setChecked(bool(
            options.get("contact_sheet_auto", True)))
        self.similarity_auto.setChecked(bool(
            options.get("similarity_auto", False)))
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

    def _apply_model_preset_migration(self) -> None:
        checkpoint = self.ckpt_combo.currentValue()
        if "noobaiXLNAIXL_epsilonPred11Version" not in checkpoint:
            return
        current = (
            self.width_spin.value(), self.height_spin.value(),
            self.steps_spin.value(), float(self.cfg_spin.value()),
            self.clip_skip.value())
        if current not in (
                (1024, 1344, 30, 5.0, -2),
                (832, 1216, 28, 5.0, -1)):
            return
        self.width_spin.setValue(832)
        self.height_spin.setValue(1216)
        res_index = self.res_combo.findData((832, 1216))
        if res_index >= 0:
            self.res_combo.setCurrentIndex(res_index)
        self.steps_spin.setValue(30)
        self.cfg_spin.setValue(5.5)
        self.clip_skip.setValue(-2)
        self.sampler_combo.selectValue("euler")
        self.scheduler_combo.selectValue("normal")
        self.hires_check.setChecked(True)
        self.hires_scale.setValue(1.5)
        self.hires_steps.setValue(20)
        self.hires_denoise.setValue(0.35)
        self._ensure_combo_value(self.upscaler_combo,
                                 "RealESRGAN_x4plus_anime_6B.pth")
        self.append_log(
            "已应用 NoobAI-XL Epsilon 1.1 清晰化参数：832x1216 / 30 steps / "
            "CFG 5.5 / Euler / clip skip 2 / Hires 1.5x")

    def _ensure_window_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        max_width = max(800, available.width() - 24)
        max_height = max(600, available.height() - 56)
        frame = self.frameGeometry()
        if frame.width() > max_width or frame.height() > max_height:
            self.resize(min(frame.width(), max_width),
                        min(frame.height(), max_height))
            frame = self.frameGeometry()
        x = min(max(frame.x(), available.left()),
                available.right() - frame.width() + 1)
        y = min(max(frame.y(), available.top()),
                available.bottom() - frame.height() + 1)
        if x != frame.x() or y != frame.y():
            self.move(x, y)

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
        if self.reference_sheet_worker and self.reference_sheet_worker.isRunning():
            answer = QMessageBox.question(
                self, "正在生成参考表", "角色参考表还在生成，确定退出并取消吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.reference_sheet_worker.cancel()
            self.reference_sheet_worker.wait(8000)
        if self.continuity_worker and self.continuity_worker.isRunning():
            answer = QMessageBox.question(
                self, "正在提取连贯性", "自动连贯提取还在运行，退出前需要等待完成。继续退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.continuity_worker.wait(120000)
        if self.vision_worker and self.vision_worker.isRunning():
            answer = QMessageBox.question(
                self, "正在检测", "角色相似度检测还在运行，退出前需要等待完成。继续退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.vision_worker.wait(120000)
        if self.prompt_worker and self.prompt_worker.isRunning():
            self.prompt_worker.wait(3000)
        if self.connect_worker and self.connect_worker.isRunning():
            self.connect_worker.wait(3000)
        if self.comfy_service.owned and not self.cfg.comfy.keep_running_on_exit:
            self.comfy_service.stop()
        self._save_ui_state()
        event.accept()
