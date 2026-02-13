
import logging
import hashlib
import sys
import subprocess
import numpy as np
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QApplication
)
from PySide6.QtWidgets import QSizePolicy

from qfluentwidgets import (
    SearchLineEdit, PrimaryPushButton, SubtitleLabel, 
    BodyLabel, CaptionLabel, ScrollArea, ElevatedCardWidget,
    FluentIcon, StateToolTip, InfoBar, InfoBarPosition, ProgressBar,
    Pivot, CardWidget, StrongBodyLabel, TextEdit, TransparentPushButton,
    ComboBox, DoubleSpinBox
)

from transcriptionist_v3.application.ai.clap_service import CLAPInferenceService
from transcriptionist_v3.ui.utils.workers import (
    IndexingJobWorker,
    TaggingJobWorker,
    ClearTagsJobWorker,
    ChunkedSearchWorker,
    IndexLoadWorker,
    IndexSaveWorker,
    SearchWorker,
    _remove_chunked_index_files,
    cleanup_thread,
)
from transcriptionist_v3.core.config import AppConfig

# AI Imports for translation
from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
import asyncio

logger = logging.getLogger(__name__)

class AISearchPage(QWidget):
    """
    AI 语义检索页面
    基于 CLAP 模型实现：
    1. 文本 -> 音频 (语义搜索)
    2. 音频 -> 音频 (相似度搜索)
    """
    tagging_finished = Signal() # 信号：打标任务完成
    tags_batch_updated = Signal(list)  # 信号：批量标签更新 [{'file_path': str, 'tags': list}, ...]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiSearchPage")
        
        # PRESET TAGS for classification
        # 使用为影视音效库精简过的标签子集，减少不相关/抽象标签
        from transcriptionist_v3.ui.utils.audioset_labels import SFX_FOCUSED_LABELS
        self.AUDIO_CATEGORIES = SFX_FOCUSED_LABELS

        
        # Engine & Data
        self.engine = None
        self.audio_embeddings = {}  # {str(file_path): np.array} 或分片时为空
        self._chunked_index = None  # 分片索引时: {"_chunked": True, "chunk_files": [...], "index_dir": str, "total_count": N}
        self.tag_embeddings = {}   # {tag_name: np.array} - Precomputed
        self.tag_translations = {} # {english_tag: chinese_tag} - Cached
        self.selected_files = []   # From Library
        # v2 selection (folders/all) from LibraryPage.selection_changed
        self._library_provider = None  # type: ignore
        self._library_selection = None

        
        # Workers
        self._indexing_thread = None
        self._indexing_worker = None
        self._tagging_thread = None
        self._tagging_worker = None
        self._clear_tags_thread = None
        self._clear_tags_worker = None
        self._load_index_thread = None
        self._load_index_worker = None
        self._save_index_thread = None
        self._save_index_worker = None
        self._search_thread = None
        self._search_worker = None
        self._index_loading = False  # 索引是否正在后台加载
        self._job_cache = {}
        self._job_list_expanded = False
        self._job_list_has_items = False
        
        self._init_ui()
        self._init_engine()
        
    def _init_engine(self):
        """Initialize Inference Engine"""
        try:
            # 使用 runtime_config 获取模型目录
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            data_dir = get_data_dir()
            model_dir = data_dir / "models" / "larger-clap-general"
            self.engine = CLAPInferenceService(model_dir)
            logger.info(f"CLAP service created with model_dir: {model_dir}")
            self._model_version = model_dir.name
            
            # Setup persistence path (FIX: use data_dir instead of undefined base_dir)
            self._index_dir = data_dir / "index"
            self._index_dir.mkdir(parents=True, exist_ok=True)
            self._index_path = self._index_dir / "clap_embeddings.npy"
            logger.info(f"Index path configured: {self._index_path}")
            
            # 后台加载索引，避免启动时阻塞（支持万级/十万级条目）
            self._start_index_load_background()
            
            # NOTE: Engine will be lazily initialized on first search via _ensure_engine_ready()
            # This avoids blocking UI startup while still ensuring engine is ready when needed
            
        except Exception as e:
            logger.error(f"Failed to create inference service: {e}")

    def _on_pivot_changed(self, route_key: str):
        """
        顶部 Pivot 切换回调。

        - 语义检索：展示“未选择文件 + 任务状态”两张卡片
        - 智能打标：隐藏这两张与索引/任务历史相关的卡片，只保留下方打标相关区域，界面更简洁
        """
        is_search = (route_key == "search")
        # 切换主内容
        self.stack.setCurrentIndex(0 if is_search else 1)
        # 根据当前标签显示/隐藏顶部卡片
        if hasattr(self, "selection_status_card"):
            self.selection_status_card.setVisible(is_search)
        if hasattr(self, "job_status_card"):
            self.job_status_card.setVisible(is_search)

    def _start_index_load_background(self):
        """后台加载索引，避免启动阻塞；万级/十万级条目时仍可快速启动。"""
        if self._index_loading or not getattr(self, "_index_path", None):
            return
        self._index_loading = True
        self._load_index_thread = QThread()
        self._load_index_worker = IndexLoadWorker(self._index_path)
        self._load_index_worker.moveToThread(self._load_index_thread)
        self._load_index_thread.started.connect(self._load_index_worker.run)
        self._load_index_worker.finished.connect(self._on_index_load_finished)
        self._load_index_worker.error.connect(self._on_index_load_error)
        self._load_index_thread.start()
        logger.info("Index load started in background")

    def _on_index_load_finished(self, embeddings):
        cleanup_thread(self._load_index_thread, self._load_index_worker)
        self._load_index_thread = None
        self._load_index_worker = None
        self._index_loading = False
        if isinstance(embeddings, dict) and embeddings.get("_chunked") is True:
            self._chunked_index = embeddings
            self.audio_embeddings = {}
            total = int(embeddings.get("total_count", 0))
            logger.info(f"Loaded chunked index manifest: {total} items (search on demand)")
            self.build_index_btn.setText("索引已就绪")
            self.build_index_btn.setEnabled(True)
            # 分片索引也支持打标，需要时按需加载分片
            self.start_tag_btn.setEnabled(True)
            self.start_tag_btn.setToolTip("开始 AI 智能打标（分片索引将按需加载）")
            self.results_list.clear()
            self.list_header.setText("索引已就绪")
            item = QListWidgetItem(f"✅ 已加载分片索引，共 {total} 条，检索时按需加载")
            self.results_list.addItem(item)
            return
        self._chunked_index = None
        self.audio_embeddings = embeddings if isinstance(embeddings, dict) else {}
        if self.audio_embeddings:
            logger.info(f"Loaded {len(self.audio_embeddings)} items from index (background)")
            self.build_index_btn.setText("索引已就绪")
            self.build_index_btn.setEnabled(True)
            self.start_tag_btn.setEnabled(True)
            self.results_list.clear()
            self.list_header.setText("索引已就绪")
            item = QListWidgetItem(f"✅ 已加载 {len(self.audio_embeddings)} 个文件的索引，可以开始搜索")
            self.results_list.addItem(item)
        else:
            logger.info("No existing index or empty index (background load)")

    def _on_index_load_error(self, msg: str):
        cleanup_thread(self._load_index_thread, self._load_index_worker)
        self._load_index_thread = None
        self._load_index_worker = None
        self._index_loading = False
        logger.error(f"Index load failed: {msg}")
        self.audio_embeddings = {}

    def _start_index_save_background(self, append: bool = False):
        """后台保存索引。分片索引下增量更新时传 append=True 追加为新分片。"""
        if not self.audio_embeddings or not getattr(self, "_index_path", None):
            return
        try:
            cleanup_thread(self._save_index_thread, self._save_index_worker)
        except Exception:
            pass
        self._save_index_thread = QThread()
        self._save_index_worker = IndexSaveWorker(
            self._index_path, self.audio_embeddings, append=append
        )
        self._save_index_worker.moveToThread(self._save_index_thread)
        self._save_index_thread.started.connect(self._save_index_worker.run)
        self._save_index_worker.finished.connect(self._on_index_save_finished)
        self._save_index_worker.error.connect(self._on_index_save_error)
        self._save_index_thread.start()
        logger.info("Index save started in background")

    def _on_index_save_finished(self, _):
        cleanup_thread(self._save_index_thread, self._save_index_worker)
        self._save_index_thread = None
        self._save_index_worker = None
        logger.info("Index saved successfully (background)")
        # 分片索引增量保存后刷新 manifest（total_count / chunk_files）
        if self._chunked_index:
            self._start_index_load_background()

    def _on_index_save_error(self, msg: str):
        cleanup_thread(self._save_index_thread, self._save_index_worker)
        self._save_index_thread = None
        self._save_index_worker = None
        logger.error(f"Index save failed: {msg}")
        InfoBar.warning(title="保存索引失败", content=msg, parent=self, duration=3000)

    def _ensure_engine_ready(self) -> bool:
        """确保引擎已初始化 - 懒加载模式"""
        if not self.engine:
            InfoBar.error(title="引擎未创建", content="AI 模型服务未正确创建", parent=self, duration=3000)
            return False
        
        # 如果引擎已经就绪，直接返回
        if self.engine._is_ready:
            return True
        
        # 首次初始化 - 显示提示
        InfoBar.info(title="正在加载模型", content="首次使用需要加载 AI 模型，请稍候...", parent=self, duration=2000)
        QApplication.processEvents()
        
        # 同步初始化（首次使用时执行）
        success = self.engine.initialize()
        
        if success:
            logger.info("CLAP engine initialized successfully (lazy init)")
            return True
        else:
            InfoBar.error(title="模型加载失败", content="无法加载 CLAP 模型，请检查模型文件是否完整", parent=self, duration=5000)
            return False

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 1. Header with Pivot
        header_container = QWidget()
        header_container.setObjectName("aiSearchHeaderContainer")
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(24, 24, 24, 10)
        header_layout.setSpacing(10)
        
        title = SubtitleLabel("AI 智能检索与打标")
        desc = CaptionLabel("基于 CLAP 模型 (DirectML 加速)")
        desc.setObjectName("aiSearchHeaderDesc")
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        
        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="search", text="语义检索")
        self.pivot.addItem(routeKey="tagging", text="智能打标")
        self.pivot.setCurrentItem("search")
        # 使用独立方法处理切换，便于控制顶部卡片在不同标签下的可见性
        self.pivot.currentItemChanged.connect(self._on_pivot_changed)
        header_layout.addWidget(self.pivot)
        
        # 1.1 Global Selection Status Card（仅在“语义检索”标签下展示，智能打标隐藏）
        self.selection_status_card = CardWidget(self)
        self.selection_status_card.setObjectName("aiSearchSelectionCard")
        self.selection_status_card.setMinimumHeight(78)
        self.selection_status_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status_layout = QHBoxLayout(self.selection_status_card)
        status_layout.setContentsMargins(20, 10, 20, 10)
        status_layout.setSpacing(10)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.tag_status_title = StrongBodyLabel("未选择文件")
        self.tag_status_desc = CaptionLabel("请在音效库中勾选需要处理的文件")
        self.tag_status_desc.setObjectName("aiSearchSelectionDesc")
        info_layout.addWidget(self.tag_status_title)
        info_layout.addWidget(self.tag_status_desc)
        
        status_layout.addLayout(info_layout)
        status_layout.addStretch()
        
        # Explicit Indexing Button
        self.clear_index_btn = TransparentPushButton(FluentIcon.DELETE, "清除索引", self)
        self.clear_index_btn.setMinimumWidth(104)
        self.clear_index_btn.clicked.connect(self._on_clear_index)
        status_layout.addWidget(self.clear_index_btn)
        
        self.build_index_btn = PrimaryPushButton(FluentIcon.FINGERPRINT, "建立 AI 检索索引")
        self.build_index_btn.setMinimumWidth(148)
        self.build_index_btn.setEnabled(False)
        self.build_index_btn.clicked.connect(self._on_start_indexing_manual)
        status_layout.addWidget(self.build_index_btn)
        
        header_layout.addWidget(self.selection_status_card)

        # 1.2 任务状态卡片（仅在“语义检索”标签下展示，智能打标隐藏）
        self.job_status_card = CardWidget(self)
        self.job_status_card.setObjectName("aiSearchJobCard")
        self.job_status_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.job_status_card.setMinimumHeight(132)
        job_layout = QVBoxLayout(self.job_status_card)
        job_layout.setContentsMargins(20, 12, 20, 12)
        job_layout.setSpacing(10)

        # 标题 + 按钮 (同一行：标题左，按钮右)
        job_header_row = QHBoxLayout()
        job_header_row.setSpacing(12)
        
        job_title_label = StrongBodyLabel("任务状态")
        job_header_row.addWidget(job_title_label)
        self.job_expand_btn = TransparentPushButton(FluentIcon.DOWN, "展开")
        self.job_expand_btn.setObjectName("aiSearchJobExpandBtn")
        self.job_expand_btn.clicked.connect(self._toggle_job_list_expanded)
        job_header_row.addWidget(self.job_expand_btn)
        
        job_header_row.addStretch()  # 将按钮推到右侧
        
        self.job_refresh_btn = TransparentPushButton(FluentIcon.SYNC, "刷新")
        # 宽度交给布局和文本自然决定，避免在窄窗口时文字被裁剪
        self.job_refresh_btn.clicked.connect(self._refresh_job_list)

        self.job_clear_btn = TransparentPushButton(FluentIcon.DELETE, "清空")
        self.job_clear_btn.setObjectName("aiSearchJobClearBtn")
        self.job_clear_btn.clicked.connect(self._on_clear_jobs_clicked)
        job_header_row.addWidget(self.job_clear_btn)

        job_header_row.addWidget(self.job_refresh_btn)
        
        self.job_resume_btn = TransparentPushButton(FluentIcon.PLAY, "继续/重试")
        self.job_resume_btn.clicked.connect(self._on_resume_job_clicked)
        job_header_row.addWidget(self.job_resume_btn)
        
        self.job_stop_btn = TransparentPushButton(FluentIcon.CLOSE, "停止")
        self.job_stop_btn.clicked.connect(self._on_stop_job_clicked)
        job_header_row.addWidget(self.job_stop_btn)
        
        job_layout.addLayout(job_header_row)

        # 任务列表（有任务时显示列表，无任务时显示一行提示，保证与标题左对齐）
        self.job_list = QListWidget()
        self.job_list.setObjectName("aiSearchJobList")
        self.job_list.setMinimumHeight(64)
        self.job_list.setMaximumHeight(72)
        self.job_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.job_list.setFrameShape(QFrame.Shape.NoFrame)
        self.job_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.job_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.job_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        job_layout.addWidget(self.job_list)

        # 空状态标签，与“任务状态”在同一布局中左对齐
        self.job_empty_label = CaptionLabel("暂无任务记录")
        self.job_empty_label.setObjectName("aiSearchJobEmptyLabel")
        self.job_empty_label.setVisible(False)
        job_layout.addWidget(self.job_empty_label)

        header_layout.addWidget(self.job_status_card)
        
        layout.addWidget(header_container)
        
        # 2. Stacked Content
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        
        # Page 1: Search
        self.search_page = self._create_search_page()
        self.stack.addWidget(self.search_page)
        
        # Page 2: Tagging
        self.tagging_page = self._create_tagging_page()
        self.stack.addWidget(self.tagging_page)

        # 初始化任务列表
        self._refresh_job_list()
        self._apply_job_expand_state()
        
    def _create_search_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("aiSearchSearchPage")
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = ScrollArea(page)
        scroll.setObjectName("aiSearchSearchScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll)

        content = QWidget()
        content.setObjectName("aiSearchSearchContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 14, 24, 22)
        layout.setSpacing(16)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        # Search Bar Area
        search_card = ElevatedCardWidget()
        search_card.setObjectName("aiSearchQueryCard")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(18, 16, 18, 14)
        search_layout.setSpacing(10)

        query_title = BodyLabel("语义搜索")
        query_hint = CaptionLabel("输入场景描述，按回车或点击搜索图标开始检索")
        query_hint.setObjectName("aiSearchQueryHint")
        query_hint.setWordWrap(True)
        search_layout.addWidget(query_title)
        search_layout.addWidget(query_hint)

        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("描述你想要的声音，例如：'雨中的雷声' 或 '赛车引擎'...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(42)
        f = self.search_input.font()
        f.setPointSize(11)
        self.search_input.setFont(f)

        self.search_input.searchSignal.connect(self._on_search)
        self.search_input.returnPressed.connect(lambda: self._on_search(self.search_input.text()))

        search_layout.addWidget(self.search_input)

        self.indexing_bar = ProgressBar()
        self.indexing_bar.setObjectName("aiSearchIndexingBar")
        self.indexing_bar.setVisible(False)
        self.indexing_label = CaptionLabel("")
        self.indexing_label.setObjectName("aiSearchIndexingLabel")
        self.indexing_label.setWordWrap(True)
        self.indexing_label.setVisible(False)
        search_layout.addWidget(self.indexing_bar)
        search_layout.addWidget(self.indexing_label)

        layout.addWidget(search_card)

        # Results
        result_header = QWidget()
        result_header.setObjectName("aiSearchResultHeader")
        result_header_layout = QHBoxLayout(result_header)
        result_header_layout.setContentsMargins(2, 0, 2, 0)
        result_header_layout.setSpacing(8)
        self.list_header = BodyLabel("待索引文件 / 搜索结果")
        result_hint = CaptionLabel("双击结果可定位到音效库")
        result_hint.setObjectName("aiSearchResultHint")
        result_hint.setWordWrap(True)
        result_header_layout.addWidget(self.list_header)
        result_header_layout.addStretch()
        result_header_layout.addWidget(result_hint)
        layout.addWidget(result_header)

        self.results_list = QListWidget()
        self.results_list.setObjectName("aiSearchResultsList")
        self.results_list.setFrameShape(QFrame.Shape.NoFrame)
        self.results_list.setAlternatingRowColors(True)
        self.results_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.results_list.setMinimumHeight(220)
        self.results_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.results_list, 1)

        scroll.setWidget(content)
        return page

    def _toggle_job_list_expanded(self):
        self._job_list_expanded = not self._job_list_expanded
        self._apply_job_expand_state()

    def _apply_job_expand_state(self):
        """根据展开状态应用任务区显示策略。"""
        if self._job_list_expanded:
            self.job_expand_btn.setIcon(FluentIcon.UP)
            self.job_expand_btn.setText("收起")
            self.job_list.setVisible(self._job_list_has_items)
            self.job_empty_label.setVisible(not self._job_list_has_items)
            self.job_list.setMinimumHeight(64)
            self.job_list.setMaximumHeight(220)
            self.job_status_card.setMinimumHeight(160)
        else:
            self.job_expand_btn.setIcon(FluentIcon.DOWN)
            self.job_expand_btn.setText("展开")
            self.job_list.setVisible(False)
            self.job_empty_label.setVisible(False)
            self.job_list.setMinimumHeight(0)
            self.job_list.setMaximumHeight(0)
            self.job_status_card.setMinimumHeight(80)

    def _create_tagging_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 10, 24, 24)
        layout.setSpacing(20)
        
        # 标签设置卡片
        options_card = CardWidget(self)
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(20, 16, 20, 16)
        options_layout.setSpacing(20)
        
        # === 标签集选择行 ===
        tag_set_row = QHBoxLayout()
        tag_set_row.setSpacing(16)
        
        tag_set_text = QVBoxLayout()
        tag_set_text.setSpacing(2)
        tag_set_title = BodyLabel("标签集")
        tag_set_desc = CaptionLabel("选择用于分类的标签集合")
        tag_set_text.addWidget(tag_set_title)
        tag_set_text.addWidget(tag_set_desc)
        tag_set_row.addLayout(tag_set_text)
        
        tag_set_row.addStretch()
        
        self.tag_label_set_combo = ComboBox(self)
        self.tag_label_set_combo.addItems([
            "音效精简 (70+)",
            "全量 AudioSet (527)",
            "自定义",
        ])
        self.tag_label_set_combo.setCurrentIndex(1)
        self.tag_label_set_combo.setFixedWidth(200)
        self.tag_label_set_combo.currentIndexChanged.connect(self._on_tag_label_set_changed)
        tag_set_row.addWidget(self.tag_label_set_combo)
        
        options_layout.addLayout(tag_set_row)
        
        # 自定义标签输入框 (默认隐藏)
        self.tag_custom_container = QWidget()
        custom_layout = QVBoxLayout(self.tag_custom_container)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_custom_edit = TextEdit(self)
        self.tag_custom_edit.setPlaceholderText("每行一个英文标签，例如：\nFootsteps\nRain")
        self.tag_custom_edit.setFixedHeight(80)
        custom_layout.addWidget(self.tag_custom_edit)
        self.tag_custom_container.setVisible(False)
        options_layout.addWidget(self.tag_custom_container)
        
        # === 置信度阈值行 ===
        confidence_row = QHBoxLayout()
        confidence_row.setSpacing(16)
        
        confidence_text = QVBoxLayout()
        confidence_text.setSpacing(2)
        confidence_title = BodyLabel("置信度阈值")
        confidence_desc = CaptionLabel("仅相似度 ≥ 此值的标签才会写入 (推荐 0.20-0.30)")
        confidence_text.addWidget(confidence_title)
        confidence_text.addWidget(confidence_desc)
        confidence_row.addLayout(confidence_text)
        
        confidence_row.addStretch()
        
        self.tag_confidence_spin = DoubleSpinBox(self)
        self.tag_confidence_spin.setRange(0.10, 0.80)
        self.tag_confidence_spin.setValue(0.25)
        self.tag_confidence_spin.setSingleStep(0.05)
        self.tag_confidence_spin.setFixedWidth(120)
        confidence_row.addWidget(self.tag_confidence_spin)
        
        options_layout.addLayout(confidence_row)
        
        layout.addWidget(options_card)
        
        # Execution Card
        exec_card = CardWidget(self)
        exec_layout = QHBoxLayout(exec_card)
        exec_layout.setContentsMargins(20, 20, 20, 20)
        
        exec_info = QVBoxLayout()
        exec_info.addWidget(StrongBodyLabel("批量分析工站"))
        exec_info.addWidget(CaptionLabel("使用 AI 模型对选中的文件进行自动化标签分类"))
        exec_layout.addLayout(exec_info)
        exec_layout.addStretch()
        
        self.clear_tags_btn = TransparentPushButton(FluentIcon.DELETE, "清除标签")
        self.clear_tags_btn.setFixedWidth(100)
        self.clear_tags_btn.setToolTip("清除当前选中文件的 AI 标签")
        self.clear_tags_btn.setEnabled(False)
        self.clear_tags_btn.clicked.connect(self._on_clear_tags)
        exec_layout.addWidget(self.clear_tags_btn)
        
        self.start_tag_btn = PrimaryPushButton(FluentIcon.TAG, "开始 AI 智能打标")
        self.start_tag_btn.setFixedWidth(180)
        self.start_tag_btn.setEnabled(False)
        self.start_tag_btn.clicked.connect(self._on_start_tagging)
        exec_layout.addWidget(self.start_tag_btn)
        
        layout.addWidget(exec_card)
        
        # Log Area
        log_label = BodyLabel("实时分析日志")
        layout.addWidget(log_label)
        
        self.tag_log = TextEdit()
        self.tag_log.setReadOnly(True)
        self.tag_log.setPlaceholderText("等待开始...")
        layout.addWidget(self.tag_log)
        
        return page
    
    def _on_tag_label_set_changed(self, index: int):
        """标签集切换：自定义时显示文本框（index==2）。"""
        self.tag_custom_container.setVisible(index == 2)  # 2 = 自定义
        if index != 2:
            self.tag_embeddings = {}  # 切换预设时下次打标会按新预设重建
        self.tag_confidence_spin.setToolTip(
            "仅相似度 ≥ 此值的标签才会写入；不达标则不打标。\n推荐值：短标签 0.25–0.35"
        )

    def set_library_provider(self, provider):
        """注入库页面实例，用于按需解析超大选择。"""
        self._library_provider = provider

    def set_selection(self, selection: dict):
        """
        v2：接收轻量选择描述，不在这里构建完整路径列表（避免大库卡顿）。
        真正需要 paths 时（建立索引/开始打标）再解析。
        """
        self._library_selection = selection
        # 避免旧的 update_selection 残留旧列表
        self.selected_files = []
        count = int(selection.get("count", 0) or 0)
        logger.info(f"AI Search: selection_changed mode={selection.get('mode')} count={count}")
        
        # Update UI
        if count > 0:
            self.tag_status_title.setText(f"已就绪: {count} 个音效文件")
            self.tag_status_desc.setText("点击右侧按钮建立 AI 索引以解锁搜索与打标")
            self.build_index_btn.setEnabled(True)
            self.build_index_btn.setText("建立 AI 检索索引") # Reset text
            # 如果索引已加载则启用打标按钮
            has_index = bool(self.audio_embeddings) or bool(self._chunked_index)
            self.start_tag_btn.setEnabled(has_index)
            self.clear_tags_btn.setEnabled(True)
        else:
            self.tag_status_title.setText("未选择文件")
            self.tag_status_desc.setText("请在音效库中勾选需要处理的文件")
            self.build_index_btn.setEnabled(False)
            self.start_tag_btn.setEnabled(False)
            self.clear_tags_btn.setEnabled(False)

    def update_selection(self, file_paths: list[str]):
        """兼容旧信号：接收从音效库选中的文件（路径列表）"""
        self.selected_files = file_paths
        count = len(file_paths)
        logger.info(f"AI Search: update_selection received {count} files")
        
        # Update UI
        if count > 0:
            self.tag_status_title.setText(f"已就绪: {count} 个音效文件")
            self.tag_status_desc.setText("点击右侧按钮建立 AI 索引以解锁搜索与打标")
            self.build_index_btn.setEnabled(True)
            self.build_index_btn.setText("建立 AI 检索索引") # Reset text
            # 如果索引已加载则启用打标按钮
            has_index = bool(self.audio_embeddings) or bool(self._chunked_index)
            self.start_tag_btn.setEnabled(has_index)
            self.clear_tags_btn.setEnabled(True)
        else:
            self.tag_status_title.setText("未选择文件")
            self.tag_status_desc.setText("请在音效库中勾选需要处理的文件")
            self.build_index_btn.setEnabled(False)
            self.start_tag_btn.setEnabled(False)
            self.clear_tags_btn.setEnabled(False)

    def _get_active_selection(self) -> dict:
        """优先使用库页的轻量 selection；否则退回到 files 列表。"""
        if self._library_selection and self._library_selection.get("mode") != "none":
            return self._library_selection
        if self.selected_files:
            return {"mode": "files", "count": len(self.selected_files), "files": list(self.selected_files)}
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

    def _load_recent_jobs(self) -> list:
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import Job
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_INDEX,
            JOB_TYPE_TAG,
            JOB_TYPE_CLEAR_TAGS,
        )

        with session_scope() as session:
            return (
                session.query(Job)
                .filter(Job.job_type.in_([JOB_TYPE_INDEX, JOB_TYPE_TAG, JOB_TYPE_CLEAR_TAGS]))
                .order_by(Job.updated_at.desc())
                .limit(20)
                .all()
            )

    def _format_job_item_text(self, job) -> str:
        type_map = {
            "index": "索引",
            "tag": "打标",
            "clear_tags": "清除标签",
        }
        status_map = {
            "pending": "待处理",
            "running": "进行中",
            "paused": "已暂停",
            "failed": "失败",
            "done": "完成",
        }
        job_type = type_map.get(job.job_type, job.job_type)
        status = status_map.get(job.status, job.status)
        total = int(job.total or 0)
        processed = int(job.processed or 0)
        progress = f"{processed}/{total}" if total > 0 else f"{processed}"
        stamp = job.updated_at or job.created_at
        stamp_text = stamp.strftime("%m-%d %H:%M") if stamp else "-"
        return f"[{job_type}] {status}  {progress}  (ID:{job.id})  {stamp_text}"

    def _refresh_job_list(self):
        """刷新任务列表（索引/打标/清除标签）。"""
        try:
            jobs = self._load_recent_jobs()
        except Exception as e:
            logger.error(f"Failed to load jobs: {e}")
            self.job_list.clear()
            self.job_list.addItem("加载任务失败")
            return

        self.job_list.clear()
        self._job_cache = {j.id: j for j in jobs}
        self._job_list_has_items = bool(jobs)
        if not jobs:
            self.job_expand_btn.setEnabled(False)
            self._job_list_expanded = False
            self._apply_job_expand_state()
            return

        self.job_expand_btn.setEnabled(True)
        self._apply_job_expand_state()

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

    def _on_resume_job_clicked(self):
        """继续/重试选中的任务。"""
        job_id = self._get_selected_job_id()
        if not job_id:
            InfoBar.warning(title="未选择任务", content="请先在任务列表中选择一条任务", parent=self)
            return

        job = self._job_cache.get(job_id)
        if not job:
            InfoBar.warning(title="任务不存在", content="未找到任务记录，请刷新后重试", parent=self)
            return

        if job.status == "running":
            InfoBar.info(title="任务进行中", content="该任务正在运行中", parent=self)
            return

        selection = self._normalize_job_selection(job, job.selection or {})
        if selection.get("mode") == "none":
            InfoBar.warning(title="无法恢复", content="该任务缺少选择范围信息", parent=self)
            return

        if job.job_type == "index":
            model_version = ""
            if isinstance(job.params, dict):
                model_version = job.params.get("model_version") or ""
            self._start_index_job(selection, job_id=job_id, model_version=model_version or getattr(self, "_model_version", ""))
            return

        if job.job_type == "clear_tags":
            self._start_clear_tags_job(selection, job_id=job_id, confirm=False)
            return

        if job.job_type == "tag":
            # 继续打标：使用当前 UI 的标签集与阈值
            self._resume_tagging_job(selection, job_id=job_id, job_params=job.params or {})
            return

        InfoBar.warning(title="不支持的任务", content="当前任务类型暂不支持恢复", parent=self)

    def _on_stop_job_clicked(self):
        """停止当前运行中的任务（仅对本页正在跑的任务生效）。"""
        job_id = self._get_selected_job_id()
        if not job_id:
            InfoBar.warning(title="未选择任务", content="请先在任务列表中选择一条任务", parent=self)
            return

        # 仅能停止当前页面正在运行的线程任务
        if self._indexing_worker and self._indexing_thread and self._indexing_thread.isRunning():
            self._indexing_worker.cancel()
            InfoBar.info(title="已请求停止", content="索引任务将尽快暂停", parent=self)
            return
        if self._tagging_worker and self._tagging_thread and self._tagging_thread.isRunning():
            self._tagging_worker.cancel()
            InfoBar.info(title="已请求停止", content="打标任务将尽快暂停", parent=self)
            return
        if self._clear_tags_worker and self._clear_tags_thread and self._clear_tags_thread.isRunning():
            self._clear_tags_worker.cancel()
            InfoBar.info(title="已请求停止", content="清除标签任务将尽快暂停", parent=self)
            return

        InfoBar.warning(title="无法停止", content="当前页面没有正在运行的任务", parent=self)

    def _on_clear_jobs_clicked(self):
        """清空任务状态列表中的任务记录（索引/打标/清除标签）。"""
        from qfluentwidgets import MessageBox
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import Job
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_INDEX,
            JOB_TYPE_TAG,
            JOB_TYPE_CLEAR_TAGS,
        )

        # 运行中的任务不允许直接清空，避免任务线程和 DB 记录状态不同步
        has_running_task = (
            (self._indexing_thread and self._indexing_thread.isRunning())
            or (self._tagging_thread and self._tagging_thread.isRunning())
            or (self._clear_tags_thread and self._clear_tags_thread.isRunning())
        )
        if has_running_task:
            InfoBar.warning(
                title="请先停止任务",
                content="检测到仍有任务在运行，请先点击“停止”后再清空任务记录",
                parent=self,
                duration=3200,
            )
            return

        w = MessageBox(
            "确认清空任务",
            "确定要清空任务状态中的所有历史记录吗？该操作不会删除音效文件与索引数据。",
            self,
        )
        if not w.exec():
            return

        try:
            with session_scope() as session:
                session.query(Job).filter(
                    Job.job_type.in_([JOB_TYPE_INDEX, JOB_TYPE_TAG, JOB_TYPE_CLEAR_TAGS])
                ).delete(synchronize_session=False)
                session.commit()
        except Exception as e:
            logger.error(f"Failed to clear job records: {e}", exc_info=True)
            InfoBar.error(
                title="清空失败",
                content="任务记录清空失败，请重试",
                parent=self,
                duration=3200,
            )
            return

        self.job_list.clear()
        self._job_cache = {}
        self._job_list_has_items = False
        self._job_list_expanded = False
        self._apply_job_expand_state()
        self._refresh_job_list()

        InfoBar.success(
            title="清空成功",
            content="任务状态已清空",
            parent=self,
            duration=2200,
        )

    def _compute_tag_version(self, tag_list: list) -> str:
        payload = "\n".join(tag_list).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()[:12]

    def _on_start_indexing_manual(self):
        """手动触发索引建立"""
        selection = self._get_active_selection()
        if selection.get("mode") == "none" or int(selection.get("count", 0) or 0) == 0:
            logger.warning("AI Search: No files selected for indexing")
            InfoBar.warning(
                title="未选择文件",
                content="请先在音效库中选择需要索引的文件或文件夹",
                parent=self,
                duration=2000
            )
            return
        self._start_index_job(selection)

    def _get_tag_list_from_ui(self):
        """根据当前 UI（标签集 + 自定义）解析出待用标签列表。影视音效(753)已注释。"""
        from transcriptionist_v3.ui.utils.audioset_labels import SFX_FOCUSED_LABELS, AUDIOSET_LABELS
        idx = self.tag_label_set_combo.currentIndex()
        if idx == 0:
            return list(SFX_FOCUSED_LABELS)
        if idx == 1:
            return list(AUDIOSET_LABELS)
        # 自定义：每行一个英文标签（idx == 2）
        raw = self.tag_custom_edit.toPlainText().strip()
        if not raw:
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]
    
    def _on_clear_tags(self):
        """清除当前选中文件的 AI 标签。"""
        selection = self._get_active_selection()
        count = int(selection.get("count", 0) or 0)
        if selection.get("mode") == "none" or count == 0:
            InfoBar.warning(title="未选择文件", content="请先在音效库中勾选要清除标签的文件", parent=self)
            return
        from qfluentwidgets import MessageBox
        w = MessageBox(
            "确认清除标签",
            f"将清除已选 {count} 个文件的 AI 标签，是否继续？",
            self
        )
        if not w.exec():
            return
        self._start_clear_tags_job(selection, job_id=None, confirm=False)

    def _start_clear_tags_job(self, selection: dict, job_id: int | None, confirm: bool = False):
        """启动清除标签任务（可用于恢复）。"""
        if confirm:
            from qfluentwidgets import MessageBox
            count = int(selection.get("count", 0) or 0)
            w = MessageBox(
                "确认清除标签",
                f"将清除已选 {count} 个文件的 AI 标签，是否继续？",
                self
            )
            if not w.exec():
                return

        try:
            cleanup_thread(self._clear_tags_thread, self._clear_tags_worker)
        except Exception:
            pass

        self.start_tag_btn.setEnabled(False)
        self.clear_tags_btn.setEnabled(False)
        self.tag_log.append("正在清除 AI 标签...")

        self._clear_tags_thread = QThread()
        self._clear_tags_worker = ClearTagsJobWorker(selection=selection, job_id=job_id)
        self._clear_tags_worker.moveToThread(self._clear_tags_thread)

        self._clear_tags_thread.started.connect(self._clear_tags_worker.run)
        self._clear_tags_worker.finished.connect(self._on_clear_tags_finished)
        self._clear_tags_worker.error.connect(self._on_clear_tags_error)

        self._clear_tags_thread.start()
        logger.info("Clear tags worker started in background thread")

    def _on_clear_tags_finished(self, result: dict):
        """清除标签任务完成"""
        cleanup_thread(self._clear_tags_thread, self._clear_tags_worker)
        self._clear_tags_thread = None
        self._clear_tags_worker = None

        processed = int(result.get("processed", 0) or 0)
        InfoBar.success(
            title="已清除",
            content=f"已清除 {processed} 个文件的 AI 标签",
            parent=self
        )
        self.tagging_finished.emit()
        self.start_tag_btn.setEnabled(True)
        self.clear_tags_btn.setEnabled(True)
        self._refresh_job_list()

    def _on_clear_tags_error(self, error_msg: str):
        """清除标签任务出错"""
        cleanup_thread(self._clear_tags_thread, self._clear_tags_worker)
        self._clear_tags_thread = None
        self._clear_tags_worker = None

        InfoBar.error(title="清除失败", content=error_msg, parent=self)
        self.start_tag_btn.setEnabled(True)
        self.clear_tags_btn.setEnabled(True)
        self._refresh_job_list()

    def _on_start_tagging(self):
        """执行批量打标 (后台线程 + 实时更新)"""
        selection = self._get_active_selection()
        if selection.get("mode") == "none" or int(selection.get("count", 0) or 0) == 0:
            InfoBar.warning(
                title="未选择文件",
                content="请先在音效库中选择需要打标的文件或文件夹",
                parent=self
            )
            return

        if not self.engine:
            InfoBar.error(title="引擎未就绪", content="AI 模型尚未加载完成", parent=self)
            return

        # 确保引擎已初始化
        if not self._ensure_engine_ready():
            return

        # 从 UI 取标签集；自定义为空则提示
        tag_list_from_ui = self._get_tag_list_from_ui()
        if not tag_list_from_ui:
            InfoBar.warning(
                title="标签集为空",
                content="请选择预设标签集，或在“自定义”下填写每行一个英文标签",
                parent=self
            )
            return

        if not self._ensure_tag_embeddings(tag_list_from_ui):
            return

        # Prepare Matrix for Vectorized Search
        tag_list = list(self.tag_embeddings.keys())
        tag_matrix = np.array([self.tag_embeddings[t] for t in tag_list])
        min_confidence = float(self.tag_confidence_spin.value())
        tag_version = self._compute_tag_version(tag_list)

        self._start_tagging_job(
            selection=selection,
            tag_list=tag_list,
            tag_matrix=tag_matrix,
            min_confidence=min_confidence,
            tag_version=tag_version,
            job_id=None,
        )

    def _ensure_tag_embeddings(self, tag_list_from_ui: list) -> bool:
        """确保标签 embedding 已准备好。"""
        # 标签集变更则清空缓存
        if set(tag_list_from_ui) != set(self.tag_embeddings.keys()):
            self.tag_embeddings = {}

        self.tag_log.append("▶ 开始 AI 智能打标任务...")
        self.start_tag_btn.setEnabled(False)
        self.clear_tags_btn.setEnabled(False)

        # 预计算标签 embedding
        if not self.tag_embeddings:
            self.tag_log.append(f"正在初始化标签库特征（共 {len(tag_list_from_ui)} 个标签，首次需 10-60 秒）...")
            QApplication.processEvents()

            try:
                for idx, tag in enumerate(tag_list_from_ui):
                    if idx % 20 == 0 or idx == len(tag_list_from_ui) - 1:
                        self.tag_log.append(f"构建索引 [{idx + 1}/{len(tag_list_from_ui)}]...")
                        QApplication.processEvents()

                    embed = self.engine.get_text_embedding(tag)
                    if embed is not None:
                        norm = np.linalg.norm(embed)
                        if norm > 0:
                            embed = embed / norm
                        self.tag_embeddings[tag] = embed

                self.tag_log.append("✅ 标签库初始化完成")
            except Exception as e:
                InfoBar.error(title="初始化失败", content=str(e), parent=self)
                self.start_tag_btn.setEnabled(True)
                self.clear_tags_btn.setEnabled(True)
                return False
        return True

    def _start_tagging_job(
        self,
        selection: dict,
        tag_list: list,
        tag_matrix,
        min_confidence: float,
        tag_version: str,
        job_id: int | None,
    ):
        """启动打标任务（可用于恢复）。"""
        try:
            cleanup_thread(self._tagging_thread, self._tagging_worker)
        except Exception:
            pass

        # 启动后台线程
        self._tagging_thread = QThread()
        self._tagging_worker = TaggingJobWorker(
            engine=self.engine,
            selection=selection,
            chunked_index=self._chunked_index,
            audio_embeddings=self.audio_embeddings,
            tag_list=tag_list,
            tag_matrix=tag_matrix,
            tag_translations=self.tag_translations,
            min_confidence=min_confidence,
            tag_version=tag_version,
            job_id=job_id,
        )
        self._tagging_worker.moveToThread(self._tagging_thread)

        # 连接信号
        self._tagging_thread.started.connect(self._tagging_worker.run)
        self._tagging_worker.log_message.connect(self._on_tagging_log)
        self._tagging_worker.progress.connect(self._on_tagging_progress)
        self._tagging_worker.batch_completed.connect(self._on_tagging_batch_completed)
        self._tagging_worker.finished.connect(self._on_tagging_finished)
        self._tagging_worker.error.connect(self._on_tagging_error)

        # 启动线程
        self._tagging_thread.start()
        logger.info("Tagging worker started in background thread")

    def _resume_tagging_job(self, selection: dict, job_id: int, job_params: dict):
        """恢复打标任务（使用当前 UI 标签集）。"""
        tag_list_from_ui = self._get_tag_list_from_ui()
        if not tag_list_from_ui:
            InfoBar.warning(
                title="标签集为空",
                content="请选择预设标签集，或在“自定义”下填写每行一个英文标签",
                parent=self
            )
            return
        if not self._ensure_tag_embeddings(tag_list_from_ui):
            return

        tag_list = list(self.tag_embeddings.keys())
        tag_matrix = np.array([self.tag_embeddings[t] for t in tag_list])
        min_confidence = float(self.tag_confidence_spin.value())
        tag_version = self._compute_tag_version(tag_list)

        # 若历史任务的 tag_version 与当前不一致，提示但仍可继续
        prev_version = ""
        if isinstance(job_params, dict):
            prev_version = str(job_params.get("tag_version") or "")
        if prev_version and prev_version != tag_version:
            InfoBar.info(
                title="标签集已变化",
                content="将使用当前标签集继续任务，可能与历史任务配置不同",
                parent=self
            )

        self._start_tagging_job(
            selection=selection,
            tag_list=tag_list,
            tag_matrix=tag_matrix,
            min_confidence=min_confidence,
            tag_version=tag_version,
            job_id=job_id,
        )

    def _on_tagging_log(self, message: str):
        """接收日志消息"""
        self.tag_log.append(message)
    
    def _on_tagging_progress(self, current: int, total: int, msg: str):
        """接收进度更新，写入实时分析日志，避免用户觉得板块卡住"""
        if total > 0 and (current % 200 == 0 or current == total):
            self.tag_log.append(f"进度: {current}/{total} — {msg.strip()}")
    
    def _on_tagging_batch_completed(self, batch_updates: list):
        """接收批次完成信号，刷新标签 UI"""
        self.tags_batch_updated.emit(batch_updates)
    
    def _on_tagging_finished(self, result: dict):
        """打标任务完成"""
        from transcriptionist_v3.ui.utils.workers import cleanup_thread
        
        cleanup_thread(self._tagging_thread, self._tagging_worker)
        
        processed = result.get('processed', 0)
        total = result.get('total', 0)
        
        InfoBar.success(
            title="打标完成",
            content=f"已更新 {processed} 个文件的标签信息",
            parent=self
        )
        
        self.tagging_finished.emit()
        self.start_tag_btn.setEnabled(True)
        self.clear_tags_btn.setEnabled(True)  # 允许清除标签
        self._refresh_job_list()
    
    def _on_tagging_error(self, error_msg: str):
        """打标任务出错"""
        from transcriptionist_v3.ui.utils.workers import cleanup_thread
        
        cleanup_thread(self._tagging_thread, self._tagging_worker)
        
        self.tag_log.append(f"\n❌ 发生错误: {error_msg}")
        InfoBar.error(title="打标出错", content=error_msg, parent=self)
        self.start_tag_btn.setEnabled(True)
        self.clear_tags_btn.setEnabled(True)  # 允许清除标签
        self._refresh_job_list()

    def on_library_cleared(self):
        """Handle library clear event"""
        self.selected_files = []
        self.audio_embeddings.clear()
        self.results_list.clear()
        self.list_header.setText("搜索结果")
        
        # Optionally clear the disk index if that's desired behavior
        # But usually we just clear memory state
        self._update_header_stats()
        
        InfoBar.success(title="已重置", content="AI 索引数据已清空", parent=self)
        logger.info("AI Search page reset due to library clear")

    def _update_header_stats(self):
        """Update the header stats (extracted for reuse)"""
        # Finds the BodyLabel in header that shows count
        # This is a bit hacky if we didn't save reference, let's just trigger update_selection([]) logic
        # Actually update_selection handles UI updates
        pass
        
    def _on_search(self, text: str):
        """Handle search execution；万级/十万级时在后台计算相似度，避免卡 UI。"""
        if not text.strip():
            return
        # CRITICAL FIX: 确保引擎已初始化（懒加载）
        if not self._ensure_engine_ready():
            return
        has_index = bool(self.audio_embeddings) or bool(self._chunked_index)
        if not has_index:
            InfoBar.warning(title="无数据", content="请勾选文件并进入 AI 检索页面以建立索引", parent=self)
            return

        # 0. Translation Augmentation (ZH -> EN)
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        search_query = text
        if has_chinese:
            logger.info(f"detected chinese in search: {text}, attempting translation...")
            translated = self._translate_text_sync(text, target_lang="en")
            if translated:
                search_query = translated
                InfoBar.info(
                    title="智能翻译",
                    content=f"已自动翻译检索词: '{text}' -> '{translated}'",
                    parent=self,
                    duration=3000
                )

        # 1. Text Embedding（text_model.onnx，与索引时的 audio_model.onnx 同一嵌入空间）
        text_embed = self.engine.get_text_embedding(search_query)
        if text_embed is None:
            InfoBar.error(title="特征提取失败", content="无法提取搜索词的特征向量（text_model 未就绪？）", parent=self, duration=2000)
            return
        logger.info("CLAP 检索: text_model 编码 query='%s' -> 嵌入维=%d", search_query[:50], text_embed.shape[0])

        only_selected = False
        selection = None
        selected_set = set()
        total_count = self._chunked_index["total_count"] if self._chunked_index else len(self.audio_embeddings)

        try:
            cleanup_thread(self._search_thread, self._search_worker)
        except Exception:
            pass
        self._last_search_text = text
        self.search_input.setEnabled(False)
        self.results_list.clear()
        self.list_header.setText(f"正在检索（共 {total_count} 条）...")
        self._search_thread = QThread()
        if self._chunked_index:
            top_per_chunk = AppConfig.get("ai.search_top_per_chunk", 300)
            max_results = AppConfig.get("ai.search_max_results", 500)
            try:
                top_per_chunk = int(top_per_chunk)
            except (TypeError, ValueError):
                top_per_chunk = 300
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                max_results = 500
            self._search_worker = ChunkedSearchWorker(
                self._chunked_index["index_dir"],
                self._chunked_index["chunk_files"],
                text_embed,
                only_selected,
                selected_set,
                selection=selection,
                top_per_chunk=top_per_chunk,
                max_results=max_results,
            )
        else:
            self._search_worker = SearchWorker(
                text_embed,
                dict(self.audio_embeddings),
                only_selected,
                selected_set,
                selection=selection,
            )
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error.connect(self._on_search_error)
        self._search_thread.start()
        logger.info("Search worker started in background")

    def _on_search_finished(self, results: list):
        cleanup_thread(self._search_thread, self._search_worker)
        self._search_thread = None
        self._search_worker = None
        self.search_input.setEnabled(True)
        text = getattr(self, "_last_search_text", "")
        self.results_list.clear()
        # P1：低分阈值过滤，避免误导性 Top-1
        # Xenova/larger_clap_general 分数普遍在 20-30%，阈值设为 22%
        MIN_SCORE_THRESHOLD = 0.22
        filtered = [(p, s) for p, s in results if s >= MIN_SCORE_THRESHOLD]
        if not results:
            self.list_header.setText(f"搜索结果: '{text}' (共 0 条)")
            self.results_list.addItem("未找到匹配结果")
            return
        top5 = results[:5]
        top5_log = ", ".join(f"{Path(p).name}={s:.2%}" for p, s in top5)
        logger.info("CLAP 检索 top5 相似度: %s", top5_log)
        if not filtered:
            self.list_header.setText(f"搜索结果: '{text}' (无高置信度匹配)")
            self.results_list.addItem("未找到高置信度匹配，建议尝试更具体的关键词或描述")
            InfoBar.warning(
                title="无高置信度结果",
                content="所有结果匹配度均低于 25%，建议换更具体的关键词或检查素材",
                parent=self,
                duration=4000
            )
            return
        self.list_header.setText(f"搜索结果: '{text}' (共 {len(filtered)} 条，≥{MIN_SCORE_THRESHOLD:.0%})")
        best_sim = filtered[0][1]
        if best_sim < 0.35:
            InfoBar.info(
                title="匹配度较低",
                content="最佳匹配度不足 35%：可尝试换关键词、用英文短词或检查素材是否包含该音效",
                parent=self,
                duration=4000
            )
        display = filtered[:20]
        for path_str, sim in display:
            name = Path(path_str).name
            score_text = f"{sim:.2%}"
            item = QListWidgetItem(f"{name}  (匹配度: {score_text})")
            item.setToolTip(path_str)
            item.setIcon(FluentIcon.MUSIC.icon())
            item.setSizeHint(QSize(0, 40))
            # 0.35 起标绿：CLAP 零样本相似度普遍不高，略降阈值让更多结果显示为高匹配
            if sim > 0.35:
                item.setForeground(Qt.GlobalColor.green)
            self.results_list.addItem(item)
        logger.info(f"AI Search: displayed top {len(display)} results for query '{text}' (threshold={MIN_SCORE_THRESHOLD:.0%})")

    def _on_search_error(self, msg: str):
        cleanup_thread(self._search_thread, self._search_worker)
        self._search_thread = None
        self._search_worker = None
        self.search_input.setEnabled(True)
        self.results_list.clear()
        self.list_header.setText("检索失败")
        self.results_list.addItem("检索出错，请重试")
        InfoBar.error(title="检索失败", content=msg, parent=self, duration=3000)

    def _start_index_job(self, selection: dict, job_id: int | None = None, model_version: str = ""):
        """任务化索引：基于 selection 规则分批处理。"""
        if not self._ensure_engine_ready():
            return

        count = int(selection.get("count", 0) or 0)
        self.build_index_btn.setEnabled(False)
        self.build_index_btn.setText("正在建立索引...")
        self.results_list.clear()
        self.list_header.setText("正在建立索引...")
        self.results_list.addItem(QListWidgetItem(f"正在为 {count} 个文件建立索引，请稍候…"))

        if self._indexing_thread and self._indexing_thread.isRunning():
            InfoBar.warning(
                title="正在忙",
                content="请等待当前索引任务完成",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return

        self.indexing_bar.setVisible(True)
        self.indexing_label.setVisible(True)
        self.indexing_bar.setValue(0)
        self.indexing_label.setText("正在加载模型...")
        self.search_input.setEnabled(False)

        batch_size = AppConfig.get("performance.index_batch_size", 2000)
        self._indexing_thread = QThread()
        self._indexing_worker = IndexingJobWorker(
            engine=self.engine,
            selection=selection,
            index_dir=self._index_dir,
            model_version=model_version or getattr(self, "_model_version", ""),
            batch_size=batch_size,
            chunk_size=batch_size,
            job_id=job_id,
        )
        self._indexing_worker.moveToThread(self._indexing_thread)

        self._indexing_thread.started.connect(self._indexing_worker.run)
        self._indexing_worker.progress.connect(self._on_indexing_progress)
        self._indexing_worker.finished.connect(self._on_index_job_finished)
        self._indexing_worker.error.connect(self._on_index_job_error)

        self._indexing_thread.start()

    def add_files(self, file_paths: list[str]):
        """兼容旧入口：将 files 列表转换为 selection 规则后执行。"""
        selection = {"mode": "files", "count": len(file_paths), "files": list(file_paths)}
        if selection["count"] == 0:
            InfoBar.warning(
                title="未选择文件",
                content="请先在音效库中选择要索引的文件",
                parent=self,
                duration=2000
            )
            return
        self._start_index_job(selection)

    def _on_indexing_progress(self, current, total, msg):
        """更新索引建立进度"""
        if total > 0:
            percent = int(current / total * 100)
            self.indexing_bar.setValue(percent)
            # 显示详细进度信息
            self.indexing_label.setText(f"{msg} ({percent}%)")

    def _on_index_job_finished(self, result: dict):
        cleanup_thread(self._indexing_thread, self._indexing_worker)
        self.indexing_bar.setVisible(False)
        self.indexing_label.setVisible(False)
        self.search_input.setEnabled(True)
        self.build_index_btn.setEnabled(True)
        self.build_index_btn.setText("索引已更新")
        self.start_tag_btn.setEnabled(True)

        # 重新加载 manifest 以获取最新分片列表
        self._start_index_load_background()

        processed = int(result.get("processed", 0) or 0)
        self.results_list.clear()
        self.list_header.setText("索引已就绪")
        self.results_list.addItem(QListWidgetItem("✅ 索引更新成功，功能已解锁。"))

        InfoBar.success(
            title="索引完成",
            content=f"已完成索引：{processed} 条",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000
        )
        self._refresh_job_list()

    def _on_index_job_error(self, msg):
        cleanup_thread(self._indexing_thread, self._indexing_worker)
        self.indexing_bar.setVisible(False)
        self.indexing_label.setVisible(False)
        self.search_input.setEnabled(True)

        InfoBar.error(
            title="索引失败",
            content=msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )
        self._refresh_job_list()

    def _show_context_menu(self, pos):
        item = self.results_list.itemAt(pos)
        if not item:
            return
            
        path_str = item.toolTip()
        if not path_str or not Path(path_str).exists():
            return
            
        from qfluentwidgets import RoundMenu, Action
        
        menu = RoundMenu(parent=self)
        
        play_action = Action(FluentIcon.PLAY, "播放", self)
        play_action.triggered.connect(lambda: self._play_file(path_str))
        menu.addAction(play_action)
        
        locate_action = Action(FluentIcon.FOLDER, "在文件夹中显示", self)
        locate_action.triggered.connect(lambda: self._locate_file(path_str))
        menu.addAction(locate_action)
        
        menu.exec(self.results_list.mapToGlobal(pos))
        
    def _on_item_double_clicked(self, item):
        path_str = item.toolTip()
        if path_str:
            self._play_file(path_str)
            
    def _play_file(self, path_str: str):
        """播放音频文件"""
        if not Path(path_str).exists():
            InfoBar.error(title="文件不存在", content=f"无法找到文件: {Path(path_str).name}", parent=self, duration=2000)
            return
            
        try:
            # 尝试通过主窗口播放
            main_window = self.window()
            # FIX: MainWindow 使用 _audio_player 属性，不是 player
            if hasattr(main_window, "_audio_player"):
                player = main_window._audio_player
                # 确保播放器对象存在且有效
                if player is not None:
                    # 使用 MainWindow 的 _on_play_file 方法，它会同步更新播放器栏
                    if hasattr(main_window, "_on_play_file"):
                        main_window._on_play_file(path_str)
                        logger.info(f"Playing file via MainWindow._on_play_file: {path_str}")
                        return
            
            # 如果找不到播放器，使用系统默认播放器
            logger.warning("Internal player not available, falling back to system player")
            import subprocess
            import sys
            if sys.platform == "win32":
                subprocess.run(["start", "", path_str], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", path_str])
            else:
                subprocess.run(["xdg-open", path_str])
            InfoBar.info(title="已打开", content=f"使用系统默认播放器打开 {Path(path_str).name}", parent=self, duration=2000)
            logger.info(f"Opened file with system player: {path_str}")
        except Exception as e:
            logger.error(f"Play failed: {e}", exc_info=True)
            InfoBar.error(title="播放失败", content=str(e), parent=self, duration=3000)
                
    def _locate_file(self, path_str: str):
        """在文件夹中显示文件"""
        import subprocess
        import sys
        
        path = Path(path_str)
        if not path.exists():
            InfoBar.error(title="文件不存在", content=f"无法找到文件: {path.name}", parent=self, duration=2000)
            return
            
        try:
            if sys.platform == "win32":
                # Windows: 使用 explorer /select
                subprocess.run(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                # macOS: 使用 open -R
                subprocess.run(["open", "-R", str(path)])
            else:
                # Linux: 打开父文件夹
                subprocess.run(["xdg-open", str(path.parent)])
            logger.info(f"Located file: {path_str}")
        except Exception as e:
            logger.error(f"Locate file failed: {e}")
            InfoBar.error(title="打开失败", content=str(e), parent=self, duration=3000)

    def _on_clear_index(self):
        """清除所有 AI 索引数据"""
        from qfluentwidgets import MessageBox
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import Job
        from transcriptionist_v3.application.ai_jobs.job_constants import JOB_TYPE_INDEX
        
        w = MessageBox(
            "确认清除",
            "确定要删除所有已建立的 AI 检索索引吗？这将导致无法使用语义搜索功能，直到您重新建立索引。",
            self
        )
        if w.exec():
            self.audio_embeddings.clear()
            self._chunked_index = None
            try:
                if self._index_path.exists():
                    self._index_path.unlink()
                    logger.info("Index file deleted")
                _remove_chunked_index_files(self._index_path.parent, self._index_path.stem)
            except Exception as e:
                logger.error(f"Failed to delete index file: {e}")
            
            # 同步清理所有索引类任务记录，避免任务列表中长期显示“进行中”的僵尸任务
            try:
                with session_scope() as session:
                    from transcriptionist_v3.infrastructure.database.models import AudioFile
                    from transcriptionist_v3.application.ai_jobs.job_constants import FILE_STATUS_PENDING
                    
                    # 删除索引任务记录
                    session.query(Job).filter(Job.job_type == JOB_TYPE_INDEX).delete(synchronize_session=False)
                    
                    # 重置所有文件的索引状态和版本，让它们在下一次索引时被重新处理
                    session.query(AudioFile).update({
                        AudioFile.index_status: FILE_STATUS_PENDING,
                        AudioFile.index_version: ""
                    }, synchronize_session=False)
                    
                    session.commit()
                    logger.info("Cleared all index jobs and reset all file index status due to index reset")
            except Exception as e:
                logger.error(f"Failed to clear index jobs and reset file status: {e}")
                
            # Reset UI
            self.results_list.clear()
            self.list_header.setText("索引已清除")
            self.results_list.addItem("暂无索引数据")
            
            # Enable build button since we are empty (if files are selected)
            if self.selected_files:
                self.build_index_btn.setEnabled(True)
                self.build_index_btn.setText("建立 AI 检索索引")
            
            # 刷新任务列表，让已清理的任务从 UI 中消失
            try:
                self._refresh_job_list()
            except Exception as e:
                logger.error(f"Failed to refresh job list after clearing index: {e}")
            
            InfoBar.success(title="清除成功", content="AI 索引已重置", parent=self)

    def _save_index(self):
        """Persist embeddings to disk"""
        try:
            if not self.audio_embeddings:
                return
            
            # 确保所有键都是字符串格式
            embeddings_to_save = {}
            for key, value in self.audio_embeddings.items():
                embeddings_to_save[str(key)] = value
            
            logger.info(f"Saving {len(embeddings_to_save)} embeddings to {self._index_path}")
            np.save(self._index_path, embeddings_to_save)
            logger.info("Index saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save index: {e}")

    def _load_index(self):
        """从磁盘加载索引；若存在分片 manifest 则只加载 manifest（按需检索）。"""
        try:
            index_dir = self._index_path.parent
            base_name = self._index_path.stem
            meta_path = index_dir / f"{base_name}_meta.npy"
            if meta_path.exists():
                data = np.load(str(meta_path), allow_pickle=True)
                meta = data.item() if data.ndim == 0 else {}
                if isinstance(meta, dict) and "chunk_files" in meta:
                    self._chunked_index = {
                        "_chunked": True,
                        "chunk_files": meta["chunk_files"],
                        "index_dir": str(index_dir),
                        "total_count": int(meta.get("total_count", 0)),
                    }
                    self.audio_embeddings = {}
                    total = self._chunked_index["total_count"]
                    self.build_index_btn.setText("索引已就绪")
                    self.build_index_btn.setEnabled(True)
                    self.start_tag_btn.setEnabled(True)
                    self.results_list.clear()
                    self.list_header.setText("索引已就绪")
                    item = QListWidgetItem(f"✅ 已加载分片索引，共 {total} 条，检索时按需加载")
                    self.results_list.addItem(item)
                    logger.info(f"Loaded chunked index manifest: {total} items")
                    return
            if self._index_path.exists():
                logger.info(f"Loading index from {self._index_path}")
                data = np.load(self._index_path, allow_pickle=True)
                if data.ndim == 0:
                    self.audio_embeddings = data.item()
                    self._chunked_index = None
                else:
                    logger.warning("Invalid index format")
                    self.audio_embeddings = {}
                logger.info(f"Loaded {len(self.audio_embeddings)} items from index")
                if self.audio_embeddings:
                    self.build_index_btn.setText("索引已就绪")
                    self.build_index_btn.setEnabled(True)
                    self.start_tag_btn.setEnabled(True)
                    self.results_list.clear()
                    self.list_header.setText("索引已就绪")
                    item = QListWidgetItem(f"✅ 已加载 {len(self.audio_embeddings)} 个文件的索引，可以开始搜索")
                    self.results_list.addItem(item)
                    logger.info("Index loaded successfully, UI updated")
            else:
                logger.info("No existing index found")
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            self.audio_embeddings = {}
            self._chunked_index = None

    def _translate_text_sync(self, text: str, target_lang: str = "en") -> str:
        """Synchronously translate text (blocking but fast enough for short text)"""
        # 优先使用 HY-MT1.5 ONNX（如果用户开启且模型已下载）- 已注释（模型加载慢且翻译质量不稳定）
        # try:
        #     translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        #     if translation_model_type == "hy_mt15_onnx":
        #         from transcriptionist_v3.runtime.runtime_config import get_data_dir
        #         model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        #         required = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
        #         has_model = all((model_dir / f).exists() for f in required) and (
        #             (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
        #         )
        #         if has_model:
        #             from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService
        #             from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        #             import asyncio
        #             cfg = AIServiceConfig(provider_id="hy_mt15_onnx", model_name="hy-mt1.5-onnx")
        #             svc = HyMT15OnnxService(cfg)
        #             loop = asyncio.new_event_loop()
        #             asyncio.set_event_loop(loop)
        #             try:
        #                 loop.run_until_complete(svc.initialize())
        #                 r = loop.run_until_complete(svc.translate(text, source_lang="zh" if target_lang == "en" else "en", target_lang=target_lang))
        #                 if r and r.success and r.data:
        #                     return r.data.translated.strip()
        #             finally:
        #                 try:
        #                     loop.run_until_complete(svc.cleanup())
        #                 except Exception:
        #                     pass
        #                 loop.close()
        # except Exception as e:
        #     logger.debug(f"HY-MT1.5 ONNX translate failed, fallback to general: {e}")

        api_key = AppConfig.get("ai.api_key", "").strip()
        if not api_key:
            return None
            
        model_idx = AppConfig.get("ai.model_index", 0)
        # Model mapping
        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        }
        config = model_configs.get(model_idx, model_configs[0])
        
        # 中文→英文：沿用上一版仓库的简洁 prompt（lid664951-crypto/transcriptionist-v3）
        if target_lang == "en":
            sys_prompt = "You are a translator. Translate the following Chinese audio description to English. Output ONLY the English translation."
        else:
            sys_prompt = """你是一位专业的影视音效标签翻译专家。

### 任务
将以下英文音效标签翻译为简洁、符合中文阅读习惯的中文表述。

### 说明
这些标签可能来自影视音效行业的专业术语与命名规范（如 UCS 等），请按行业惯例译为更符合中文阅读与使用习惯的表述，避免生硬直译或过于书面化。

### 翻译原则
1. **口语化优先**：使用影视后期制作人员日常使用的说法，避免生硬的直译
2. **简洁明了**：优先使用 2~4 个字的简短词汇，让用户一眼就能看懂
3. **行业习惯**：遵循中文影视音效行业的常用术语与命名习惯

### 常见翻译示例
- "footstep" → "脚步声"（不要翻译成"足音"）
- "whoosh" → "嗖声"（不要翻译成"呼啸声"）
- "impact" → "撞击"（不要翻译成"冲击"）
- "ambience" → "环境音"（不要翻译成"氛围"）
- "foley" → "拟音"（不要翻译成"物之声"）
- "UI sound" → "界面音"（不要翻译成"用户界面声音"）
- "bell" → "铃声"（不要翻译成"牛铃"或"钟声"，除非明确指定）
- "theremin" → "特雷门琴"（专业乐器名称保持原样）

### 输出要求
仅输出翻译后的中文标签，不要包含任何标点符号、解释或额外说明。"""
            
        try:
            service_config = AIServiceConfig(
                provider_id=config["provider"],
                api_key=api_key,
                base_url=config["base_url"],
                model_name=config["model"],
                system_prompt=sys_prompt,
                timeout=10,
                max_tokens=64,
                temperature=0.3
            )
            service = OpenAICompatibleService(service_config)
            
            # Run sync
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(service.translate_single(text))
                if result.success:
                    translated_text = result.data.strip()
                    logger.info(f"Translation success: '{text}' -> '{translated_text}'")
                    return translated_text
                else:
                    logger.error(f"Translation error: {result.error}")
            finally:
                loop.close()
                asyncio.run(service.cleanup()) # Ensure session is closed
                
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            
        return None
