"""
AI翻译页面 - 完整功能版本
支持：从音效库选择文件、多AI模型、术语库翻译、应用翻译结果
"""

import logging
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QTreeWidgetItem, QListWidget, QListWidgetItem, QFrame,
    QSizePolicy
)
from PySide6.QtGui import QFont

from qfluentwidgets import (
    ScrollArea, PushButton, PrimaryPushButton, ComboBox, LineEdit,
    FluentIcon, CardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, CaptionLabel, TransparentToolButton, IconWidget,
    TableWidget, ProgressBar, TextEdit, Dialog, TreeWidget
)

# Architecture refactoring: use centralized utilities
from transcriptionist_v3.ui.utils.notifications import NotificationHelper
from transcriptionist_v3.ui.utils.workers import ApplyTranslationJobWorker, TranslateJobWorker, cleanup_thread
from transcriptionist_v3.ui.utils.hierarchical_translate_worker import HierarchicalTranslateWorker
from transcriptionist_v3.application.naming_manager.glossary import GlossaryManager
from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
from transcriptionist_v3.application.naming_manager.templates import TemplateManager, NamingTemplate
from transcriptionist_v3.application.library_manager.renaming_service import RenamingService

logger = logging.getLogger(__name__)


class AITranslatePage(QWidget):
    """AI翻译页面 - 完整功能"""
    
    # 显示上限：超过此数量时只显示部分，避免 UI 卡死/OOM
    DISPLAY_CAP = 5000
    
    translation_applied = Signal(str, str)  # 原路径, 新路径
    request_play = Signal(str)  # 请求播放文件 (绝对路径)
    request_stop_player = Signal()  # 请求停止播放以释放文件锁
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiTranslatePage")
        
        self._selected_files = []
        # v2 selection (folders/all) from LibraryPage.selection_changed
        self._library_provider = None  # type: ignore
        self._library_selection: Optional[dict] = None
        self._translation_results = {}  # 原路径 -> 翻译结果（已显示的）
        self._glossary_manager = GlossaryManager.instance()
        self._cleaning_manager = CleaningManager.instance()
        
        # 大数据量优化：保存所有翻译结果，UI 只显示部分
        self._all_translation_items: list = []  # 所有翻译结果（用于"应用全部"）
        self._displayed_count = 0  # 已显示到 UI 的数量
        
        # 使用 runtime_config 获取数据目录初始化 TemplateManager
        from pathlib import Path
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        data_dir = get_data_dir()
        self._template_manager = TemplateManager.instance(str(data_dir))
        
        # QThread workers for translation
        self._translate_thread: Optional[QThread] = None
        self._translate_worker: Optional[object] = None
        self._translate_job_thread: Optional[QThread] = None
        self._translate_job_worker: Optional[TranslateJobWorker] = None
        self._apply_job_thread: Optional[QThread] = None
        self._apply_job_worker: Optional[ApplyTranslationJobWorker] = None
        self._job_cache = {}
        
        # 撤销历史记录 (old_path, new_path)
        self._undo_stack = []
        
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        # Modern UI: Increased margins for airy feel
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(0) # Splitter handles spacing
        
        # 1. Header Area
        header_layout = QHBoxLayout()
        
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        
        title = SubtitleLabel("AI翻译")
        desc = CaptionLabel("使用AI将英文音效名称翻译为中文，支持术语库和多种AI模型")
        desc.setTextColor(Qt.GlobalColor.gray)
        desc.setStyleSheet("background: transparent")
        
        header_text.addWidget(title)
        header_text.addWidget(desc)
        header_layout.addLayout(header_text)
        header_layout.addStretch()
        
        # 规则按钮（右上角）
        self.rules_btn = PushButton(FluentIcon.BOOK_SHELF, "规则")
        self.rules_btn.clicked.connect(self._on_open_rules)
        header_layout.addWidget(self.rules_btn, 0, Qt.AlignmentFlag.AlignTop)
        
        layout.addLayout(header_layout)
        layout.addSpacing(24)
        # removed independent desc widget since it's merged into header
        
        # Custom Splitter for content
        from PySide6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)
        splitter.setChildrenCollapsible(False)
        
        # 左侧：设置和文件选择
        left_card = CardWidget()
        left_card.setMinimumWidth(320) # Ensure settings are readable
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)
        
        # 文件选择区域
        file_section = QVBoxLayout()
        file_label = SubtitleLabel("待翻译文件")
        file_section.addWidget(file_label)
        
        self.file_count_label = BodyLabel("已选择 0 个文件")
        self.file_count_label.setStyleSheet("background: transparent")
        file_section.addWidget(self.file_count_label)
        
        file_hint = CaptionLabel("在音效库中勾选文件，然后点击下方按钮")
        file_hint.setStyleSheet("background: transparent")
        file_section.addWidget(file_hint)
        
        self.clear_list_btn = PushButton(FluentIcon.DELETE, "清空待翻译列表")
        self.clear_list_btn.clicked.connect(self._on_clear_list)
        file_section.addWidget(self.clear_list_btn)
        
        left_layout.addLayout(file_section)

        # 任务状态
        task_section = QVBoxLayout()
        task_section.setSpacing(8)
        
        # 标题行
        task_title_label = SubtitleLabel("任务状态")
        task_section.addWidget(task_title_label)
        
        # 按钮行 (单独一行)
        task_btn_row = QHBoxLayout()
        task_btn_row.setSpacing(8)
        
        self.job_refresh_btn = PushButton(FluentIcon.SYNC, "刷新")
        self.job_refresh_btn.setFixedWidth(80)
        self.job_refresh_btn.clicked.connect(self._refresh_job_list)
        task_btn_row.addWidget(self.job_refresh_btn)
        
        self.job_resume_btn = PushButton(FluentIcon.PLAY, "继续/重试")
        self.job_resume_btn.setFixedWidth(100)
        self.job_resume_btn.clicked.connect(self._on_resume_job_clicked)
        task_btn_row.addWidget(self.job_resume_btn)
        
        self.job_stop_btn = PushButton(FluentIcon.CLOSE, "停止")
        self.job_stop_btn.setFixedWidth(80)
        self.job_stop_btn.clicked.connect(self._on_stop_job_clicked)
        task_btn_row.addWidget(self.job_stop_btn)
        
        task_btn_row.addStretch()  # 按钮靠左排列
        task_section.addLayout(task_btn_row)

        # 任务列表
        self.job_list = QListWidget()
        self.job_list.setFixedHeight(90)
        self.job_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.job_list.setFrameShape(QFrame.Shape.NoFrame)
        task_section.addWidget(self.job_list)

        left_layout.addLayout(task_section)
        
        # 分隔线
        left_layout.addSpacing(12)
        
        # 语言设置
        lang_section = QHBoxLayout()
        
        source_box = QVBoxLayout()
        source_label = CaptionLabel("源语言")
        source_label.setStyleSheet("background: transparent")
        source_box.addWidget(source_label)
        self.source_combo = ComboBox()
        self.source_combo.addItems(["自动检测", "英语", "日语", "韩语", "俄语", "德语", "法语", "西班牙语"])
        self.source_combo.setFixedWidth(120)
        source_box.addWidget(self.source_combo)
        lang_section.addLayout(source_box)
        
        arrow = BodyLabel("→")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet("background: transparent")
        lang_section.addWidget(arrow)
        
        target_box = QVBoxLayout()
        target_label = CaptionLabel("目标语言")
        target_label.setStyleSheet("background: transparent")
        target_box.addWidget(target_label)
        self.target_combo = ComboBox()
        self.target_combo.addItems(["简体中文", "繁体中文", "英语", "日语", "韩语"])
        self.target_combo.setFixedWidth(120)
        target_box.addWidget(self.target_combo)
        lang_section.addLayout(target_box)
        
        lang_section.addStretch()
        left_layout.addLayout(lang_section)
        
        left_layout.addStretch()
        
        # 翻译按钮
        self.translate_btn = PrimaryPushButton(FluentIcon.SEND, "开始翻译")
        self.translate_btn.setFixedHeight(48) # Modern UI: Taller button
        self.translate_btn.clicked.connect(self._on_translate)
        left_layout.addWidget(self.translate_btn)
        

        
        # 右侧：翻译结果
        right_card = CardWidget()
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)
        
        # 结果标题
        result_header = QHBoxLayout()
        result_label = SubtitleLabel("翻译结果")
        result_header.addWidget(result_label)
        result_header.addStretch()
        
        self.apply_all_btn = PushButton(FluentIcon.ACCEPT, "全部替换")
        self.apply_all_btn.clicked.connect(self._on_apply_all)
        self.apply_all_btn.setEnabled(False)
        result_header.addWidget(self.apply_all_btn)
        
        self.undo_btn = PushButton(FluentIcon.HISTORY, "撤销全部替换")
        self.undo_btn.clicked.connect(self._on_undo_all)
        self.undo_btn.setEnabled(False)
        result_header.addWidget(self.undo_btn)
        
        right_layout.addLayout(result_header)
        
        # 进度展示区域
        self.progress_container = QVBoxLayout()
        self.progress_container.setSpacing(4)
        self.progress_container.setContentsMargins(0, 8, 0, 8)
        
        # 状态文本标签
        self.progress_label = CaptionLabel("准备就绪")
        self.progress_label.setTextColor(Qt.GlobalColor.gray)
        self.progress_label.setStyleSheet("background: transparent")
        self.progress_container.addWidget(self.progress_label)
        
        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6) # 细长一点更美观
        self.progress_container.addWidget(self.progress_bar)
        
        self.progress_widget = QWidget()
        self.progress_widget.setStyleSheet("background: transparent")
        self.progress_widget.setLayout(self.progress_container)
        self.progress_widget.hide()
        right_layout.addWidget(self.progress_widget)
        
        # 结果树形列表
        self.result_tree = TreeWidget()
        self.result_tree.setColumnCount(4)
        self.result_tree.setHeaderLabels(["资源名称", "翻译结果", "状态", "操作"])
        self.result_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        header = self.result_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.result_tree.setColumnWidth(2, 90)
        self.result_tree.setColumnWidth(3, 110)
        
        self.result_tree.itemDoubleClicked.connect(self._on_result_double_clicked)
        right_layout.addWidget(self.result_tree, 1)
        
        # Add cards to splitter
        splitter.addWidget(left_card)
        splitter.addWidget(right_card)
        
        # Set stretch factors (30% settings, 70% results)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        
        layout.addWidget(splitter, 1)
        self._refresh_job_list()

    
    def set_selected_files(self, files: list):
        """设置选中的文件列表（从音效库传入）"""
        self._selected_files = files
        self.file_count_label.setText(f"已选择 {len(files)} 个文件")
        logger.info(f"AI Translate: received {len(files)} files")

    def set_library_provider(self, provider):
        """注入库页面实例，用于按需解析超大选择。"""
        self._library_provider = provider

    def set_selection(self, selection: dict):
        """
        v2：接收轻量选择描述，不在这里构建完整路径列表（避免大库卡顿）。
        真正需要路径列表时（点击开始翻译）再解析。
        """
        self._library_selection = selection
        # 避免旧的 files_checked 造成的残留/混淆
        self._selected_files = []
        count = int(selection.get("count", 0) or 0)
        self.file_count_label.setText(f"已选择 {count} 个文件")
        logger.info(f"AI Translate: selection_changed mode={selection.get('mode')} count={count}")

    def _get_active_selection(self) -> dict:
        """优先使用库页的轻量 selection；否则回退到 files 列表。"""
        if self._library_selection and self._library_selection.get("mode") != "none":
            return self._library_selection
        if self._selected_files:
            return {"mode": "files", "count": len(self._selected_files), "files": list(self._selected_files)}
        return {"mode": "none", "count": 0}

    def _normalize_job_selection(self, job, selection: dict | None) -> dict:
        """从 job 中补全 selection 缺失信息，避免空选择导致无法恢复。"""
        if not selection:
            selection = {}
        if selection.get("count") in (None, 0) and getattr(job, "total", 0):
            selection["count"] = int(job.total)
        if not selection.get("mode"):
            selection["mode"] = "none"
        return selection

    def _load_recent_translate_jobs(self) -> list:
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import Job
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_TRANSLATE,
            JOB_TYPE_APPLY_TRANSLATION,
        )

        with session_scope() as session:
            return (
                session.query(Job)
                .filter(Job.job_type.in_([JOB_TYPE_TRANSLATE, JOB_TYPE_APPLY_TRANSLATION]))
                .order_by(Job.updated_at.desc())
                .limit(20)
                .all()
            )

    def _format_job_item_text(self, job) -> str:
        status_map = {
            "pending": "待处理",
            "running": "进行中",
            "paused": "已暂停",
            "failed": "失败",
            "done": "完成",
        }
        type_map = {
            "translate": "翻译",
            "apply_translation": "应用翻译",
        }
        status = status_map.get(job.status, job.status)
        job_type = type_map.get(job.job_type, job.job_type)
        total = int(job.total or 0)
        processed = int(job.processed or 0)
        progress = f"{processed}/{total}" if total > 0 else f"{processed}"
        stamp = job.updated_at or job.created_at
        stamp_text = stamp.strftime("%m-%d %H:%M") if stamp else "-"
        return f"[{job_type}] {status}  {progress}  (ID:{job.id})  {stamp_text}"

    def _refresh_job_list(self):
        """刷新翻译任务列表。"""
        try:
            jobs = self._load_recent_translate_jobs()
        except Exception as e:
            logger.error(f"Failed to load translate jobs: {e}")
            self.job_list.clear()
            self.job_list.addItem("加载任务失败")
            return

        self.job_list.clear()
        self._job_cache = {j.id: j for j in jobs}
        if not jobs:
            self.job_list.addItem("暂无任务记录")
            return

        for job in jobs:
            text = self._format_job_item_text(job)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, job.id)
            if job.error:
                item.setToolTip(str(job.error))
            self.job_list.addItem(item)

    def _get_selected_job_id(self) -> int | None:
        item = self.job_list.currentItem()
        if not item:
            return None
        job_id = item.data(Qt.ItemDataRole.UserRole)
        return int(job_id) if job_id else None

    def _resolve_translation_model_config(self) -> tuple[str, dict, bool, str | None]:
        """读取当前翻译模型配置；返回 (api_key, model_config, use_onnx, error_message)。"""
        from transcriptionist_v3.core.config import AppConfig

        model_index = AppConfig.get("ai.model_index", 0)
        api_key = AppConfig.get("ai.api_key", "").strip()
        translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        use_onnx = (translation_model_type == "hy_mt15_onnx")

        # 模型配置映射 (包含本地模型)
        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
            3: {  # 本地模型
                "provider": "local",
                "model": AppConfig.get("ai.local_model_name", ""),
                "base_url": AppConfig.get("ai.local_base_url", "http://localhost:1234/v1"),
            },
        }
        model_config = model_configs.get(model_index, model_configs[0])

        # 本地模型时，API Key 可以为空
        if model_index == 3:
            api_key = ""
            if not model_config.get("model") or not model_config.get("base_url"):
                return "", model_config, use_onnx, "请先在设置中配置本地模型的 Base URL 和模型名称"
            return api_key, model_config, use_onnx, None

        if model_index != 3 and not api_key and not use_onnx:
            return "", model_config, use_onnx, "请在“设置 -> AI 配置”中配置 API 密钥"

        return api_key, model_config, use_onnx, None

    def _build_selection_from_items(self, items: list) -> dict:
        """从内存翻译结果构建 selection（回退路径）。"""
        files = []
        for item in items:
            path = getattr(item, "path", None)
            if path:
                files.append(str(path))
        return {"mode": "files", "count": len(files), "files": files}

    def _on_resume_job_clicked(self):
        """继续/重试选中的翻译任务。"""
        job_id = self._get_selected_job_id()
        if not job_id:
            NotificationHelper.warning(self, "提示", "请先在任务列表中选择一条任务")
            return

        job = self._job_cache.get(job_id)
        if not job:
            NotificationHelper.warning(self, "提示", "未找到任务记录，请刷新后重试")
            return

        if job.status == "running":
            NotificationHelper.info(self, "提示", "该任务正在运行中")
            return

        selection = self._normalize_job_selection(job, job.selection or {})
        if selection.get("mode") == "none":
            NotificationHelper.warning(self, "提示", "该任务缺少选择范围信息，无法恢复")
            return

        if job.job_type == "apply_translation":
            self._start_apply_translation_job(selection=selection, job_id=job_id)
            return

        api_key, model_config, _, error_msg = self._resolve_translation_model_config()
        if error_msg:
            NotificationHelper.error(self, "配置缺失", error_msg)
            return

        params = job.params or {}
        source_lang = params.get("source_lang") or self.source_combo.currentText()
        target_lang = params.get("target_lang") or self.target_combo.currentText()
        template_id = params.get("template_id") or self._template_manager.active_template_id

        self._start_translate_job(
            selection=selection,
            api_key=api_key,
            model_config=model_config,
            source_lang=source_lang,
            target_lang=target_lang,
            job_id=job_id,
            template_id=template_id,
        )

    def _on_stop_job_clicked(self):
        """停止当前运行中的翻译任务（仅对本页正在跑的任务生效）。"""
        if self._translate_job_worker and self._translate_job_thread and self._translate_job_thread.isRunning():
            self._translate_job_worker.cancel()
            NotificationHelper.info(self, "已请求停止", "翻译任务将尽快暂停")
            return
        if self._apply_job_worker and self._apply_job_thread and self._apply_job_thread.isRunning():
            self._apply_job_worker.cancel()
            NotificationHelper.info(self, "已请求停止", "应用翻译任务将尽快暂停")
            return
        NotificationHelper.warning(self, "无法停止", "当前页面没有正在运行的任务")

    def _resolve_selection_paths(self, selection: dict, limit: Optional[int] = None) -> list[str]:
        """按 selection 规则解析为路径列表（避免直接 resolve 全量）。"""
        if selection.get("mode") == "files":
            files = selection.get("files") or []
            return list(files)
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile
        from transcriptionist_v3.application.ai_jobs.selection import apply_selection_filters

        with session_scope() as session:
            query = session.query(AudioFile.file_path)
            query = apply_selection_filters(query, selection)
            if limit:
                query = query.limit(limit)
            rows = query.all()
            return [row.file_path for row in rows]
    
    def _on_clear_list(self):
        """清空待翻译列表"""
        # 1. Clear Data
        self._selected_files = []
        self._translation_results.clear()
        
        # 2. Clear UI
        self.file_count_label.setText("已选择 0 个文件")
        self.result_tree.clear()
        
        # 3. Reset Button states (if needed)
        self.translate_btn.setText("开始翻译")
        self.translate_btn.setEnabled(True)
        self.apply_all_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.progress_widget.hide()
        
        NotificationHelper.success(
            self,
            "列表已清空",
            "已移除所有待翻译文件及结果"
        )
    

    def on_library_cleared(self):
        """Handle library clear event"""
        self._on_clear_list()
        logger.info("AI Translate page cleared due to library reset")

    def _on_translate(self):
        """开始翻译"""
        selection = self._get_active_selection()
        count = int(selection.get("count", 0) or 0)
        if selection.get("mode") == "none" or count == 0:
            NotificationHelper.warning(
                self,
                "提示",
                "请先选择要翻译的文件"
            )
            return

        from transcriptionist_v3.core.config import AppConfig
        api_key, model_config, _, error_msg = self._resolve_translation_model_config()
        if error_msg:
            NotificationHelper.error(self, "配置缺失", error_msg)
            return

        # 清空结果树
        self.result_tree.clear()
        self._translation_results.clear()
        self._all_translation_items = []
        self._displayed_count = 0

        # 显示进度展示区域
        self.progress_widget.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在连接AI引擎...")
        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("正在翻译...")
        self.apply_all_btn.setEnabled(False)

        # 获取源语言和目标语言
        source_lang = self.source_combo.currentText()
        target_lang = self.target_combo.currentText()

        # 超大选择：走任务化翻译，避免全量路径展开
        preview_threshold = AppConfig.get("performance.translate_preview_threshold", self.DISPLAY_CAP)
        try:
            preview_threshold = int(preview_threshold)
        except (TypeError, ValueError):
            preview_threshold = self.DISPLAY_CAP
        if preview_threshold < 1:
            preview_threshold = self.DISPLAY_CAP

        if count > preview_threshold:
            self._start_translate_job(
                selection=selection,
                api_key=api_key,
                model_config=model_config,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            return

        # 小规模：解析为路径列表再走分层翻译
        files = self._resolve_selection_paths(selection, limit=count)
        self._selected_files = files

        if not self._selected_files:
            self.progress_widget.hide()
            self.translate_btn.setEnabled(True)
            self.translate_btn.setText("开始翻译")
            NotificationHelper.warning(
                self,
                "提示",
                "请先选择要翻译的文件"
            )
            return

        # 使用 QThread + Worker（层级化翻译）
        self._translate_thread = QThread()

        logger.info("Using HierarchicalTranslateWorker")
        self._translate_worker = HierarchicalTranslateWorker(
            files=list(self._selected_files),
            api_key=api_key,
            model_config=model_config,
            glossary=self._glossary_manager.get_all(),
            template_id=self._template_manager.active_template_id,
            source_lang=source_lang,
            target_lang=target_lang
        )

        self._translate_worker.moveToThread(self._translate_thread)

        # 连接信号
        self._translate_thread.started.connect(self._translate_worker.run)
        self._translate_worker.finished.connect(self._on_translate_finished)
        self._translate_worker.error.connect(self._on_translate_error)
        self._translate_worker.progress.connect(self._on_translate_progress)

        # 启动线程
        self._translate_thread.start()

    def _start_translate_job(
        self,
        selection: dict,
        api_key: str,
        model_config: dict,
        source_lang: str,
        target_lang: str,
        job_id: int | None = None,
        template_id: str | None = None,
    ):
        """启动任务化翻译（不展开全量路径）。"""
        from transcriptionist_v3.core.config import AppConfig

        try:
            cleanup_thread(self._translate_job_thread, self._translate_job_worker)
        except Exception:
            pass

        self.progress_widget.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在启动翻译任务...")
        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("正在翻译...")
        self.apply_all_btn.setEnabled(False)

        batch_size = AppConfig.get("performance.translate_batch_size", 200)
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError):
            batch_size = 200

        self._translate_job_thread = QThread()
        self._translate_job_worker = TranslateJobWorker(
            selection=selection,
            api_key=api_key,
            model_config=model_config,
            template_id=template_id or self._template_manager.active_template_id,
            source_lang=source_lang,
            target_lang=target_lang,
            batch_size=batch_size,
            job_id=job_id,
        )
        self._translate_job_worker.moveToThread(self._translate_job_thread)

        self._translate_job_thread.started.connect(self._translate_job_worker.run)
        self._translate_job_worker.progress.connect(self._on_translate_progress)
        self._translate_job_worker.finished.connect(self._on_translate_job_finished)
        self._translate_job_worker.error.connect(self._on_translate_job_error)

        self._translate_job_thread.start()

    def _cleanup_translate_job_thread(self):
        cleanup_thread(self._translate_job_thread, self._translate_job_worker)
        self._translate_job_thread = None
        self._translate_job_worker = None

    def _on_translate_job_finished(self, result: dict):
        self._cleanup_translate_job_thread()
        processed = int(result.get("processed", 0) or 0)
        failed = int(result.get("failed", 0) or 0)

        self.progress_bar.setValue(100)
        self.progress_label.setText("翻译完成")
        self.progress_widget.hide()
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")

        NotificationHelper.success(
            self,
            "翻译完成",
            f"已翻译 {processed} 个文件，失败 {failed} 个。结果已写入库，可在列表中查看"
        )
        self._refresh_job_list()

    def _on_translate_job_error(self, error_msg: str):
        self._cleanup_translate_job_thread()
        self.progress_widget.hide()
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")
        NotificationHelper.error(
            self,
            "翻译失败",
            error_msg
        )
        self._refresh_job_list()

    def _cleanup_translate_thread(self):
        """清理翻译线程"""
        cleanup_thread(self._translate_thread, self._translate_worker)
        self._translate_thread = None
        self._translate_worker = None
    
    def _on_translate_progress(self, current: int, total: int, msg: str):
        """翻译进度回调"""
        progress = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(progress)
        self.progress_label.setText(msg)
    
    def _on_translate_finished(self, results: list):
        """翻译完成回调"""
        self._cleanup_translate_thread()
        
        # Now passing all items (files and folders) directly to building tree
        self._update_results(results)

        # 进度条视觉上补齐到 100%，避免用户误以为还没完成
        try:
            # 只统计文件数量用于显示；文件夹只是层级容器
            file_count = sum(
                1 for r in results
                if getattr(r, "item_type", "file") == "file"
            )
        except Exception:
            file_count = 0
        else:
            if self.progress_widget.isVisible():
                self.progress_bar.setValue(100)
                if file_count > 0:
                    self.progress_label.setText(f"完成批次: {file_count}/{file_count}")
                else:
                    self.progress_label.setText("翻译完成")
        
        self.progress_widget.hide()
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")
        self.apply_all_btn.setEnabled(True)

        NotificationHelper.success(
            self,
            "翻译完成",
            f"已收集并显示 {len(results)} 个项目 (含 {file_count} 个文件)"
        )
    
    def _on_translate_error(self, error_msg: str):
        """翻译错误"""
        self._cleanup_translate_thread()
        self.progress_widget.hide() # Hide progress widget on error
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")
        self.apply_all_btn.setEnabled(False) # Disable apply all button on error
        NotificationHelper.error(
            self,
            "翻译失败",
            error_msg
        )
        logger.error(f"Translation error: {error_msg}")
    

    def _update_results(self, items: list):
        """更新翻译结果UI（主线程）- 使用分批更新避免卡顿，支持显示上限"""
        self.result_tree.clear()
        self._translation_results.clear()
        
        # 保存所有翻译结果（用于"应用全部"，即使 UI 只显示部分）
        self._all_translation_items = items
        self._displayed_count = 0
        
        total_count = len(items)
        logger.info(f"UI updating with {total_count} hierarchical results (DISPLAY_CAP={self.DISPLAY_CAP})")
        
        # 计算实际要显示的数量（受 DISPLAY_CAP 限制）
        display_count = min(total_count, self.DISPLAY_CAP)
        
        # 如果项目数量较少，直接更新（避免不必要的复杂性）
        if display_count <= 100:
            self._update_results_sync(items[:display_count])
            self._displayed_count = display_count
            self._show_load_more_hint(total_count, display_count)
            return
        
        # 大量项目时使用分批更新
        from PySide6.QtCore import QTimer
        
        # 准备数据
        from transcriptionist_v3.ui.utils.translation_items import TranslationItem
        from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
        from collections import defaultdict
        
        pattern = self._template_manager.get_active_pattern()
        template = NamingTemplate("preview", "Preview", pattern)
        
        # 按层级排序，确保父目录先添加
        sorted_items = sorted(items, key=lambda x: x.level)
        
        # 存储状态（文件夹也走命名模板，需单独计数同级文件夹序号）
        self._update_state = {
            'items': sorted_items[:display_count],  # 只处理要显示的部分
            'all_items': sorted_items,  # 保留完整列表用于"加载更多"
            'template': template,
            'nodes': {},  # path -> QTreeWidgetItem
            'folder_file_index': defaultdict(int),
            'folder_folder_index': defaultdict(int),
            'current_index': 0,
            'batch_size': 50,  # 每批处理50个项目
            'total_count': total_count,
            'display_count': display_count,
        }
        
        # 禁用更新以提高性能
        self.result_tree.setUpdatesEnabled(False)
        
        # 使用 QTimer 分批更新
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_results_batch)
        self._update_timer.setSingleShot(False)
        self._update_timer.start(10)  # 每10ms处理一批
        
        # 显示进度提示
        self.progress_widget.show()
        self.progress_label.setText(f"正在更新UI: 0/{display_count}")
    
    def _update_results_batch(self):
        """分批更新UI（每批处理一定数量的项目）"""
        state = self._update_state
        items = state['items']
        template = state['template']
        nodes = state['nodes']
        folder_file_index = state['folder_file_index']
        folder_folder_index = state['folder_folder_index']
        current_index = state['current_index']
        batch_size = state['batch_size']
        total_count = state.get('total_count', len(items))
        display_count = state.get('display_count', len(items))
        
        # 计算本批要处理的项目
        end_index = min(current_index + batch_size, len(items))
        batch_items = items[current_index:end_index]
        
        # 处理本批项目
        for item in batch_items:
            self._add_single_item(item, template, nodes, folder_file_index, folder_folder_index)
        
        # 更新进度
        state['current_index'] = end_index
        self.progress_label.setText(f"正在更新UI: {end_index}/{display_count}")
        
        # 如果处理完成
        if end_index >= len(items):
            self._update_timer.stop()
            self._displayed_count = end_index
            
            # 保留 nodes 引用以便"加载更多"时使用
            self._update_nodes = nodes
            self._update_folder_file_index = folder_file_index
            self._update_folder_folder_index = folder_folder_index
            self._update_template = template
            
            delattr(self, '_update_timer')
            delattr(self, '_update_state')
            
            # 重新启用更新
            self.result_tree.setUpdatesEnabled(True)
            
            # 隐藏进度提示
            self.progress_widget.hide()
            
            # 显示"加载更多"提示（如果有更多数据）
            self._show_load_more_hint(total_count, display_count)
            
            logger.info(f"Batch UI update completed: {display_count}/{total_count} items displayed")
        else:
            # 让事件循环处理，避免阻塞
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
    
    def _add_single_item(self, item, template, nodes, folder_file_index, folder_folder_index=None):
        """添加单个项目到树（辅助方法）；文件与文件夹均走命名模板。"""
        from transcriptionist_v3.ui.utils.translation_items import TranslationItem
        from pathlib import Path
        from collections import defaultdict
        
        if folder_folder_index is None:
            folder_folder_index = defaultdict(int)

        # 获取译名（移除后缀用于预览生成）
        translated_text = item.translated
        item_path = Path(item.path)
        
        if item.item_type == 'file' and translated_text.lower().endswith(item_path.suffix.lower()):
            pure_translated = translated_text[:-len(item_path.suffix)]
        else:
            pure_translated = translated_text

        # 生成预览名（文件与文件夹均使用规则中的命名模板）
        if item.item_type == 'file':
            # 按父文件夹独立编号（每个文件夹从1开始）
            folder_file_index[item.parent_path] += 1
            local_index = folder_file_index[item.parent_path]
            
            context = self._template_manager.create_context(
                item.name,
                ucs_components={
                    "category": item.category,
                    "subcategory": item.subcategory,
                    "descriptor": item.descriptor,
                    "variation": item.variation,
                },
                index=local_index,
                translated=pure_translated
            )
            preview_name = template.format(context)
            if not preview_name.endswith(item_path.suffix):
                preview_name += item_path.suffix
            icon = FluentIcon.MUSIC
        else:
            # 文件夹预览：走命名模板（与文件一致，可用 {translated}、{original}、{index} 等）
            folder_folder_index[item.parent_path] += 1
            local_index = folder_folder_index[item.parent_path]
            context = self._template_manager.create_context(
                item.name,
                ucs_components=None,
                index=local_index,
                translated=pure_translated
            )
            preview_name = template.format(context)
            if not preview_name or not preview_name.strip():
                preview_name = pure_translated if (pure_translated and pure_translated != item.name) else item.name
            icon = FluentIcon.FOLDER
        
        # 创建树节点
        tree_item = QTreeWidgetItem()
        tree_item.setText(0, item.name)
        tree_item.setIcon(0, icon.icon())
        tree_item.setText(1, preview_name)
        tree_item.setToolTip(1, f"原名: {item.name}\n译名: {item.translated}")
        tree_item.setText(2, "待应用")
        
        # 存储原始数据以便操作
        tree_item.setData(0, Qt.ItemDataRole.UserRole, item)
        self._translation_results[item.path] = item
        
        # 查找父节点
        parent_node = nodes.get(item.parent_path)
        if parent_node:
            parent_node.addChild(tree_item)
            parent_node.setExpanded(True)
        else:
            self.result_tree.addTopLevelItem(tree_item)
        
        nodes[item.path] = tree_item
        
        # 添加操作按钮
        self._add_tree_item_widgets(tree_item, item)
    
    def _update_results_sync(self, items: list):
        """同步更新UI（用于少量项目）"""
        # 为了避免一次性更新大量节点导致界面明显卡顿，这里临时关闭重绘
        self.result_tree.setUpdatesEnabled(False)
        try:
            logger.info(f"UI updating with {len(items)} hierarchical results (sync mode)")
            
            from transcriptionist_v3.ui.utils.translation_items import TranslationItem
            from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
            from collections import defaultdict
            
            pattern = self._template_manager.get_active_pattern()
            template = NamingTemplate("preview", "Preview", pattern)
            
            # 建立分类映射
            nodes = {}  # path -> QTreeWidgetItem
            
            # 按层级排序，确保父目录先添加
            sorted_items = sorted(items, key=lambda x: x.level)
            
            # 按父文件夹分组计算索引（文件与文件夹分别计数，均用于命名模板）
            folder_file_index = defaultdict(int)
            folder_folder_index = defaultdict(int)
            
            for item in sorted_items:
                self._add_single_item(item, template, nodes, folder_file_index, folder_folder_index)
            
            # 保存状态以便"加载更多"时使用
            self._update_nodes = nodes
            self._update_folder_file_index = folder_file_index
            self._update_folder_folder_index = folder_folder_index
            self._update_template = template
        finally:
            # 批量更新完成后再打开重绘
            self.result_tree.setUpdatesEnabled(True)
    
    def _show_load_more_hint(self, total_count: int, displayed_count: int):
        """显示"加载更多"提示（如果有更多数据未显示）"""
        # 移除旧的提示（如果有）
        if hasattr(self, '_load_more_item') and self._load_more_item:
            index = self.result_tree.indexOfTopLevelItem(self._load_more_item)
            if index >= 0:
                self.result_tree.takeTopLevelItem(index)
            self._load_more_item = None
        
        if total_count <= displayed_count:
            # 所有数据都已显示，无需提示
            return
        
        remaining = total_count - displayed_count
        
        # 创建"加载更多"提示节点
        hint_item = QTreeWidgetItem()
        hint_item.setText(0, f"已显示 {displayed_count} / {total_count} 条，还有 {remaining} 条未显示")
        hint_item.setIcon(0, FluentIcon.INFO.icon())
        hint_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "load_more_hint"})
        hint_item.setFlags(hint_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)  # 不可选中
        
        self.result_tree.addTopLevelItem(hint_item)
        self._load_more_item = hint_item
        
        # 为该节点添加"加载更多"按钮
        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)
        
        load_more_btn = PushButton("加载更多")
        load_more_btn.setFixedSize(80, 26)
        load_more_btn.clicked.connect(self._on_load_more)
        btn_layout.addWidget(load_more_btn)
        
        # 提示：大数据量时建议直接"应用全部"
        if remaining > 5000:
            hint_label = CaptionLabel("(数据量较大，建议直接点击「应用全部」)")
            hint_label.setStyleSheet("background: transparent; color: #888;")
            btn_layout.addWidget(hint_label)
        
        self.result_tree.setItemWidget(hint_item, 3, btn_container)
        
        logger.info(f"Showing load more hint: {displayed_count}/{total_count} displayed, {remaining} remaining")
    
    def _on_load_more(self):
        """加载更多翻译结果到 UI"""
        if not self._all_translation_items:
            return
        
        total_count = len(self._all_translation_items)
        current_displayed = self._displayed_count
        
        if current_displayed >= total_count:
            return
        
        # 每次加载 DISPLAY_CAP 个
        next_batch_end = min(current_displayed + self.DISPLAY_CAP, total_count)
        batch_items = self._all_translation_items[current_displayed:next_batch_end]
        
        # 移除旧的"加载更多"提示
        if hasattr(self, '_load_more_item') and self._load_more_item:
            index = self.result_tree.indexOfTopLevelItem(self._load_more_item)
            if index >= 0:
                self.result_tree.takeTopLevelItem(index)
            self._load_more_item = None
        
        # 获取之前保存的状态
        nodes = getattr(self, '_update_nodes', {})
        folder_file_index = getattr(self, '_update_folder_file_index', None)
        folder_folder_index = getattr(self, '_update_folder_folder_index', None)
        template = getattr(self, '_update_template', None)
        
        if template is None:
            from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
            pattern = self._template_manager.get_active_pattern()
            template = NamingTemplate("preview", "Preview", pattern)
        
        if folder_file_index is None:
            from collections import defaultdict
            folder_file_index = defaultdict(int)
        if folder_folder_index is None:
            from collections import defaultdict
            folder_folder_index = defaultdict(int)
        
        # 禁用更新以提高性能
        self.result_tree.setUpdatesEnabled(False)
        try:
            sorted_batch = sorted(batch_items, key=lambda x: x.level)
            for item in sorted_batch:
                self._add_single_item(item, template, nodes, folder_file_index, folder_folder_index)
        finally:
            self.result_tree.setUpdatesEnabled(True)
        
        self._displayed_count = next_batch_end
        
        # 更新状态
        self._update_nodes = nodes
        self._update_folder_file_index = folder_file_index
        self._update_folder_folder_index = folder_folder_index
        
        # 如果还有更多，继续显示提示
        self._show_load_more_hint(total_count, next_batch_end)
        
        logger.info(f"Loaded more items: now {next_batch_end}/{total_count} displayed")

    def _add_tree_item_widgets(self, tree_item, item):
        """为树节点添加操作按钮"""
        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        # 替换按钮 (纯文字)
        apply_btn = PushButton("应用")
        apply_btn.setFixedSize(50, 26)
        apply_btn.clicked.connect(lambda: self._on_apply_single(tree_item))
        btn_layout.addWidget(apply_btn)
        
        # 删除按钮 (纯文字)
        del_btn = PushButton("删除")
        del_btn.setFixedSize(50, 26)
        del_btn.clicked.connect(lambda: self._on_remove_tree_item(tree_item))
        btn_layout.addWidget(del_btn)
        
        self.result_tree.setItemWidget(tree_item, 3, btn_container)

    def _on_remove_tree_item(self, item: QTreeWidgetItem):
        """移除树节点"""
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            index = self.result_tree.indexOfTopLevelItem(item)
            self.result_tree.takeTopLevelItem(index)

    def _on_result_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击播放音效"""
        trans_item = item.data(0, Qt.ItemDataRole.UserRole)
        if not trans_item or trans_item.item_type != 'file':
            return
            
        file_path = trans_item.path
        logger.info(f"Double-clicked file_path: {file_path}")
        
        if Path(file_path).exists():
            self.request_play.emit(str(file_path))
        else:
            logger.warning(f"File not found: {file_path}")
    
    def _on_apply_single(self, tree_item: QTreeWidgetItem):
        """应用单个翻译结果（带重试机制）"""
        self.request_stop_player.emit()
        
        item = tree_item.data(0, Qt.ItemDataRole.UserRole)
        if not item: return
        
        old_path = Path(item.path)
        if not old_path.exists():
            NotificationHelper.error(self, "错误", f"文件不存在: {old_path}")
            return

        # 确定新名称：文件与文件夹均使用预览列（命名模板生成，所见即所得）
        new_name = tree_item.text(1)
        if not new_name or not new_name.strip():
            # 预览列为空时回退：文件用原名，文件夹用译名或原名
            if item.item_type == 'file':
                logger.warning(f"Preview name is empty for {old_path}, fallback to original name")
                new_name = item.name
            else:
                new_name = (item.translated if (item.translated and item.translated != item.name) else item.name)

        if new_name == old_path.name:
            tree_item.setText(2, "未变更")
            return

        # 重试机制（处理Windows文件锁）
        import time
        max_retries = 3
        retry_delay = 0.3
        
        for attempt in range(max_retries):
            try:
                # 如果是文件夹，给系统时间释放句柄
                if old_path.is_dir() and attempt > 0:
                    time.sleep(retry_delay * attempt)
                
                success, msg, new_path_str = RenamingService.rename_sync(str(old_path), new_name)
                if not success: 
                    raise Exception(msg)
                    
                new_path = Path(new_path_str)
                
                # 更新状态
                tree_item.setText(2, "已应用")
                container = self.result_tree.itemWidget(tree_item, 3)
                if container:
                    from qfluentwidgets import PushButton
                    apply_btn = container.findChild(PushButton)
                    if apply_btn:
                        apply_btn.setEnabled(False)
                        apply_btn.setText("已应用")
                
                # 记录到撤销栈并更新内存缓存
                self._undo_stack.append((str(old_path), str(new_path)))
                self.undo_btn.setEnabled(True)
                
                # CRITICAL: 如果是文件夹重命名，需要更新所有子节点的路径！
                if item.item_type == 'folder':
                    self._update_child_paths(tree_item, str(old_path), str(new_path))

                # 更新 item 对象本身的路径
                item.path = str(new_path)
                
                self.translation_applied.emit(str(old_path), str(new_path))
                logger.info(f"Renamed: {old_path.name} -> {new_name}")
                break  # 成功，退出重试循环
                
            except PermissionError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Rename attempt {attempt + 1} failed for {old_path.name}: {e}, retrying...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Rename failed after {max_retries} attempts: {e}")
                    NotificationHelper.error(
                        self, 
                        "重命名失败", 
                        f"{old_path.name}\n\n错误: 文件被占用或权限不足\n请关闭占用该文件的程序后重试"
                    )
                    tree_item.setText(2, "失败")
                    
            except Exception as e:
                logger.error(f"Rename failed: {e}")
                NotificationHelper.error(self, "重命名失败", f"{old_path.name}\n\n{str(e)}")
                tree_item.setText(2, "失败")
                break  # 其他错误不重试

    def _apply_single_item(self, item) -> bool:
        """应用单个翻译项（不依赖树节点，用于批量应用）
        
        Args:
            item: TranslationItem 对象
            
        Returns:
            bool: 是否成功
        """
        import time
        
        old_path = Path(item.path)
        if not old_path.exists():
            logger.warning(f"File not found, skipping: {old_path}")
            item.status = "跳过"
            return False
        
        # 生成新名称（使用命名模板）
        new_name = self._generate_preview_name(item)
        if not new_name or not new_name.strip():
            new_name = item.translated if (item.translated and item.translated != item.name) else item.name
        
        if new_name == old_path.name:
            item.status = "未变更"
            return True  # 无需变更也算成功
        
        # 重试机制（处理Windows文件锁）
        max_retries = 3
        retry_delay = 0.3
        
        for attempt in range(max_retries):
            try:
                if old_path.is_dir() and attempt > 0:
                    time.sleep(retry_delay * attempt)
                
                success, msg, new_path_str = RenamingService.rename_sync(str(old_path), new_name)
                if not success:
                    raise Exception(msg)
                
                new_path = Path(new_path_str)
                
                # 记录到撤销栈
                self._undo_stack.append((str(old_path), str(new_path)))
                
                # 如果是文件夹，更新所有子项的路径
                if item.item_type == 'folder':
                    self._update_all_child_paths(str(old_path), str(new_path))
                
                # 更新 item 本身
                item.path = str(new_path)
                item.status = "已应用"
                
                self.translation_applied.emit(str(old_path), str(new_path))
                return True
                
            except PermissionError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Rename attempt {attempt + 1} failed for {old_path.name}: {e}, retrying...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Rename failed after {max_retries} attempts: {e}")
                    item.status = "失败"
                    return False
                    
            except Exception as e:
                logger.error(f"Rename failed for {old_path.name}: {e}")
                item.status = "失败"
                return False
        
        return False
    
    def _generate_preview_name(self, item) -> str:
        """为单个项目生成预览名称（使用命名模板）"""
        from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
        
        pattern = self._template_manager.get_active_pattern()
        template = NamingTemplate("preview", "Preview", pattern)
        
        translated_text = item.translated
        item_path = Path(item.path)
        
        # 移除后缀用于预览生成
        if item.item_type == 'file' and translated_text.lower().endswith(item_path.suffix.lower()):
            pure_translated = translated_text[:-len(item_path.suffix)]
        else:
            pure_translated = translated_text
        
        if item.item_type == 'file':
            context = self._template_manager.create_context(
                item.name,
                ucs_components={
                    "category": getattr(item, 'category', ''),
                    "subcategory": getattr(item, 'subcategory', ''),
                    "descriptor": getattr(item, 'descriptor', ''),
                    "variation": getattr(item, 'variation', ''),
                },
                index=1,  # 批量应用时不使用序号
                translated=pure_translated
            )
            preview_name = template.format(context)
            if not preview_name.endswith(item_path.suffix):
                preview_name += item_path.suffix
        else:
            context = self._template_manager.create_context(
                item.name,
                ucs_components=None,
                index=1,
                translated=pure_translated
            )
            preview_name = template.format(context)
            if not preview_name or not preview_name.strip():
                preview_name = pure_translated if (pure_translated and pure_translated != item.name) else item.name
        
        return preview_name
    
    def _update_all_child_paths(self, old_parent_path: str, new_parent_path: str):
        """更新所有子项的路径（在 _all_translation_items 中）"""
        if not self._all_translation_items:
            return
        
        for item in self._all_translation_items:
            if item.path.startswith(old_parent_path + os.sep):
                item.path = item.path.replace(old_parent_path, new_parent_path, 1)
            if hasattr(item, 'parent_path') and item.parent_path.startswith(old_parent_path):
                item.parent_path = item.parent_path.replace(old_parent_path, new_parent_path, 1)
    
    def _update_child_paths(self, parent_item: QTreeWidgetItem, old_parent_path: str, new_parent_path: str):
        """递归更新所有子节点的路径（树节点版本）"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            item = child.data(0, Qt.ItemDataRole.UserRole)
            if item:
                # 替换路径前缀
                if item.path.startswith(old_parent_path):
                    item.path = item.path.replace(old_parent_path, new_parent_path, 1)
                if item.parent_path.startswith(old_parent_path):
                    item.parent_path = item.parent_path.replace(old_parent_path, new_parent_path, 1)
                # 继续递归
                self._update_child_paths(child, old_parent_path, new_parent_path)
        
        # 同时更新 _all_translation_items 中的路径
        self._update_all_child_paths(old_parent_path, new_parent_path)

    def _get_all_tree_items(self) -> list:
        """获取树中所有的 QTreeWidgetItem"""
        all_items = []
        def traverse(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                all_items.append(child)
                traverse(child)
        
        for i in range(self.result_tree.topLevelItemCount()):
            top_item = self.result_tree.topLevelItem(i)
            all_items.append(top_item)
            traverse(top_item)
        return all_items

    def _on_apply_all(self):
        """应用所有翻译结果 (自底向上策略，先文件后文件夹) - 优化版本，支持大数据量"""
        self.request_stop_player.emit()

        selection = self._get_active_selection()
        count = int(selection.get("count", 0) or 0)
        if selection.get("mode") == "none" and self._all_translation_items:
            selection = self._build_selection_from_items(self._all_translation_items)
            count = int(selection.get("count", 0) or 0)

        # 优先使用完整的翻译结果列表（即使 UI 只显示了部分）
        if self._all_translation_items:
            all_items = self._all_translation_items
        else:
            # 回退到树节点（兼容旧逻辑）
            all_tree_items = self._get_all_tree_items()
            if not all_tree_items:
                return
            all_items = [item.data(0, Qt.ItemDataRole.UserRole) for item in all_tree_items 
                        if item.data(0, Qt.ItemDataRole.UserRole)]
        
        if not all_items:
            return

        # 超大批量：走任务化应用（避免 UI 卡死）
        from transcriptionist_v3.core.config import AppConfig
        threshold = AppConfig.get("performance.apply_translation_job_threshold", 2000)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 2000
        if count >= threshold:
            self._start_apply_translation_job(selection=selection, job_id=None)
            return
        
        # 按照路径深度倒序排序 (确保自底向上: 最深的文件先处理，最外层的目录最后处理)
        import os
        sorted_items = sorted(
            all_items,
            key=lambda x: x.path.count(os.sep) if hasattr(x, 'path') else 0,
            reverse=True
        )
        
        # 筛选出待应用的项目（status == '待应用'）
        pending_items = [item for item in sorted_items if getattr(item, 'status', '待应用') == '待应用']
        if not pending_items:
            NotificationHelper.info(self, "无需操作", "没有待应用的翻译结果")
            return
        
        total_count = len(pending_items)
        logger.info(f"Apply all: {total_count} pending items (total: {len(all_items)})")
        
        success_count = 0
        failed_items = []
        
        # 显示进度
        self.progress_widget.show()
        self.progress_label.setText(f"正在应用: 0/{total_count}")
        
        # 批量处理：使用 QTimer 分批处理，避免UI卡死
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        
        batch_size = 50  # 每批处理50个（不涉及 UI 节点创建，可以更大）
        batch_index = 0
        
        def process_batch():
            nonlocal success_count, batch_index
            
            start_idx = batch_index * batch_size
            end_idx = min(start_idx + batch_size, total_count)
            
            if start_idx >= total_count:
                finish_batch_apply()
                return
            
            # 处理当前批次
            for i in range(start_idx, end_idx):
                item = pending_items[i]
                
                try:
                    success = self._apply_single_item(item)
                    if success:
                        success_count += 1
                    else:
                        failed_items.append(getattr(item, 'name', 'unknown'))
                except Exception as e:
                    logger.error(f"Failed to apply translation for {getattr(item, 'name', 'unknown')}: {e}")
                    failed_items.append(getattr(item, 'name', 'unknown'))
            
            # 更新进度
            self.progress_label.setText(f"正在应用: {end_idx}/{total_count}")
            
            batch_index += 1
            
            # 每批结束后让 UI 响应
            QApplication.processEvents()
            
            # 继续处理下一批（使用较短的延迟，保持流畅性）
            QTimer.singleShot(5, process_batch)
        
        def finish_batch_apply():
            """批量操作完成后的清理工作"""
            # 隐藏进度
            self.progress_widget.hide()
            
            # 显示结果通知
            if success_count > 0:
                if failed_items:
                    NotificationHelper.warning(
                        self,
                        "批量应用部分成功",
                        f"成功处理 {success_count}/{total_count} 个项目\n失败 {len(failed_items)} 个: {', '.join(failed_items[:3])}{'...' if len(failed_items) > 3 else ''}"
                    )
                else:
                    NotificationHelper.success(
                        self,
                        "批量应用完成",
                        f"成功处理 {success_count}/{total_count} 个待应用项目"
                    )
            elif total_count > 0:
                NotificationHelper.error(
                    self,
                    "批量应用失败",
                    f"所有 {total_count} 个项目应用失败"
                )
            
            # 如果有成功应用的项目，启用撤销按钮
            if self._undo_stack:
                self.undo_btn.setEnabled(True)
        
        # 开始批量处理
        process_batch()

    def _start_apply_translation_job(self, selection: dict, job_id: int | None):
        """启动任务化应用翻译结果。"""
        from transcriptionist_v3.core.config import AppConfig

        try:
            cleanup_thread(self._apply_job_thread, self._apply_job_worker)
        except Exception:
            pass

        batch_size = AppConfig.get("performance.apply_translation_batch_size", 200)
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError):
            batch_size = 200

        self.progress_widget.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在应用翻译结果...")
        self.apply_all_btn.setEnabled(False)

        self._apply_job_thread = QThread()
        self._apply_job_worker = ApplyTranslationJobWorker(
            selection=selection,
            batch_size=batch_size,
            job_id=job_id,
        )
        self._apply_job_worker.moveToThread(self._apply_job_thread)

        self._apply_job_thread.started.connect(self._apply_job_worker.run)
        self._apply_job_worker.progress.connect(self._on_apply_job_progress)
        self._apply_job_worker.finished.connect(self._on_apply_job_finished)
        self._apply_job_worker.error.connect(self._on_apply_job_error)

        self._apply_job_thread.start()

    def _cleanup_apply_job_thread(self):
        cleanup_thread(self._apply_job_thread, self._apply_job_worker)
        self._apply_job_thread = None
        self._apply_job_worker = None

    def _on_apply_job_progress(self, current: int, total: int, message: str):
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.progress_label.setText(f"{message} ({percent}%)")
        else:
            self.progress_label.setText(message)

    def _on_apply_job_finished(self, result: dict):
        self._cleanup_apply_job_thread()
        processed = int(result.get("processed", 0) or 0)
        failed = int(result.get("failed", 0) or 0)

        self.progress_widget.hide()
        self.apply_all_btn.setEnabled(True)
        self._refresh_job_list()

        if failed:
            NotificationHelper.warning(
                self,
                "应用完成",
                f"已应用 {processed} 个，失败 {failed} 个"
            )
        else:
            NotificationHelper.success(
                self,
                "应用完成",
                f"已应用 {processed} 个翻译结果"
            )

    def _on_apply_job_error(self, error_msg: str):
        self._cleanup_apply_job_thread()
        self.progress_widget.hide()
        self.apply_all_btn.setEnabled(True)
        self._refresh_job_list()
        NotificationHelper.error(self, "应用失败", error_msg)

    def _on_undo_all(self):
        """撤销所有已应用的重命名（自顶向下策略，带重试机制）- 优化版本，支持大数据量"""
        if not self._undo_stack:
            logger.info("Undo stack is empty")
            return
        
        # 停止播放器以释放文件锁
        self.request_stop_player.emit()
        
        import time
        import os
        
        total_operations = len(self._undo_stack)
        logger.info(f"Starting undo for {total_operations} operations")
        
        # 按路径深度排序（浅到深，确保父文件夹先撤销）
        undo_operations = list(self._undo_stack)
        sorted_operations = sorted(
            undo_operations,
            key=lambda x: x[0].count(os.sep)  # 使用原路径的深度
        )
        
        success_count = 0
        failed_operations = []
        
        # 显示进度
        self.progress_widget.show()
        self.progress_label.setText(f"正在撤销: 0/{total_operations}")
        
        # 批量处理：使用 QTimer 分批处理，避免UI卡死
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        
        batch_size = 50  # 每批处理50个文件（撤销操作相对简单，可以更大）
        batch_index = 0
        
        def process_undo_batch():
            nonlocal success_count, batch_index
            
            start_idx = batch_index * batch_size
            end_idx = min(start_idx + batch_size, len(sorted_operations))
            
            if start_idx >= len(sorted_operations):
                # 所有批次处理完成
                finish_undo_batch()
                return
            
            # 处理当前批次
            for i in range(start_idx, end_idx):
                old_path_str, new_path_str = sorted_operations[i]
                old_path = Path(old_path_str)
                new_path = Path(new_path_str)
                
                if not new_path.exists():
                    logger.warning(f"Undo skipped: {new_path.name} does not exist at {new_path}")
                    continue
                
                # 尝试重命名，带重试机制（处理Windows文件锁）
                max_retries = 3
                retry_delay = 0.5  # 秒
                success = False
                
                for attempt in range(max_retries):
                    try:
                        # 如果是文件夹，先检查是否有进程占用
                        if new_path.is_dir():
                            # 给系统一点时间释放文件句柄
                            if attempt > 0:
                                time.sleep(retry_delay * attempt)
                        
                        new_path.rename(old_path)
                        self.translation_applied.emit(str(new_path), str(old_path))
                        success_count += 1
                        success = True
                        break
                        
                    except PermissionError as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Undo attempt {attempt + 1} failed for {new_path.name}: {e}, retrying...")
                            time.sleep(retry_delay)
                        else:
                            logger.error(f"Undo failed for {new_path.name} after {max_retries} attempts: {e}")
                            failed_operations.append((old_path_str, new_path_str, str(e)))
                            
                    except Exception as e:
                        logger.error(f"Undo failed for {new_path.name}: {e}")
                        failed_operations.append((old_path_str, new_path_str, str(e)))
                        break
            
            # 更新进度
            self.progress_label.setText(f"正在撤销: {end_idx}/{total_operations}")
            
            batch_index += 1
            
            # 每批结束后让 UI 响应
            QApplication.processEvents()
            
            # 继续处理下一批（使用较短的延迟，保持流畅性）
            QTimer.singleShot(5, process_undo_batch)
        
        def finish_undo_batch():
            """批量撤销完成后的清理工作"""
            # 隐藏进度
            self.progress_widget.hide()
            
            # 清空撤销栈（只保留失败的操作）
            self._undo_stack.clear()
            if failed_operations:
                # 将失败的操作放回栈中，以便用户稍后重试
                self._undo_stack.extend([(old, new) for old, new, _ in failed_operations])
                self.undo_btn.setEnabled(True)
            else:
                self.undo_btn.setEnabled(False)
            
            # 刷新 UI 状态（只刷新已显示的节点，不遍历所有数据）
            self._refresh_table_status_after_undo()
            
            # 同步更新 _all_translation_items 中的状态
            if self._all_translation_items:
                for item in self._all_translation_items:
                    item.status = "待应用"
            
            # 显示结果
            if success_count > 0:
                if failed_operations:
                    failed_names = [Path(new).name for _, new, _ in failed_operations]
                    NotificationHelper.warning(
                        self,
                        "部分撤销成功",
                        f"成功还原 {success_count} 个项目\n失败 {len(failed_operations)} 个: {', '.join(failed_names[:3])}{'...' if len(failed_names) > 3 else ''}\n\n请关闭占用文件的程序后重试"
                    )
                else:
                    NotificationHelper.success(
                        self,
                        "已撤销",
                        f"已成功还原 {success_count} 个项目的原名"
                    )
            else:
                if failed_operations:
                    NotificationHelper.error(
                        self,
                        "撤销失败",
                        f"所有 {len(failed_operations)} 个项目撤销失败\n可能原因：文件被占用或权限不足\n\n请关闭占用文件的程序（如资源管理器、播放器）后重试"
                    )
                else:
                    logger.warning("No files were restored during undo")
        
        # 开始批量处理
        process_undo_batch()

    def _refresh_table_status_after_undo(self):
        """同步 UI 状态 (清空所有应用状态，变回待应用)"""
        all_items = self._get_all_tree_items()
        for item in all_items:
            item.setText(2, "待应用")
            container = self.result_tree.itemWidget(item, 3)
            if container:
                apply_btn = container.findChild(PushButton)
                if apply_btn:
                    apply_btn.setEnabled(True)
                    apply_btn.setText("应用")
    
    def _on_open_rules(self):
        """打开命名规则对话框"""
        from transcriptionist_v3.ui.pages.naming_rules_page_qt import NamingRulesPage
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        
        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("命名规则")
        dialog.resize(900, 700)
        
        # 创建布局
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        
        # 嵌入命名规则页面
        naming_rules_page = NamingRulesPage(dialog)
        dialog_layout.addWidget(naming_rules_page)
        
        # 监听术语库更新信号
        def on_glossary_updated(glossary: dict):
            # 同步更新本地的GlossaryManager（已经是单例，无需手动同步）
            logger.info(f"Glossary updated from rules dialog: {len(glossary)} terms")
        
        naming_rules_page.glossary_updated.connect(on_glossary_updated)
        
        # 显示对话框
        dialog.exec()
