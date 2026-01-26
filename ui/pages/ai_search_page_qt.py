
import logging
import numpy as np
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QApplication
)

from qfluentwidgets import (
    SearchLineEdit, PrimaryPushButton, SubtitleLabel, 
    BodyLabel, CaptionLabel, ScrollArea, ElevatedCardWidget,
    FluentIcon, StateToolTip, InfoBar, InfoBarPosition, ProgressBar,
    Pivot, CardWidget, StrongBodyLabel, TextEdit, SwitchButton, TransparentPushButton
)

from transcriptionist_v3.application.ai.clap_service import CLAPInferenceService
from transcriptionist_v3.ui.utils.workers import CLAPIndexingWorker, cleanup_thread
from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag
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
        # Custom Comprehensive Tag List (Standard Google AudioSet 527)
        from transcriptionist_v3.ui.utils.audioset_labels import AUDIOSET_LABELS
        self.AUDIO_CATEGORIES = AUDIOSET_LABELS

        
        # Engine & Data
        self.engine = None
        self.audio_embeddings = {} # {str(file_path): np.array}
        self.tag_embeddings = {}   # {tag_name: np.array} - Precomputed
        self.tag_translations = {} # {english_tag: chinese_tag} - Cached
        self.selected_files = []   # From Library

        
        # Workers
        self._indexing_thread = None
        self._indexing_worker = None
        self._tagging_thread = None
        self._tagging_worker = None
        
        self._init_ui()
        self._init_engine()
        
    def _init_engine(self):
        """Initialize Inference Engine"""
        try:
            # 使用 runtime_config 获取模型目录
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            data_dir = get_data_dir()
            model_dir = data_dir / "models" / "clap-htsat-unfused"
            self.engine = CLAPInferenceService(model_dir)
            logger.info(f"CLAP service created with model_dir: {model_dir}")
            
            # Setup persistence path (FIX: use data_dir instead of undefined base_dir)
            self._index_dir = data_dir / "index"
            self._index_dir.mkdir(parents=True, exist_ok=True)
            self._index_path = self._index_dir / "clap_embeddings.npy"
            logger.info(f"Index path configured: {self._index_path}")
            
            # Try to load existing index
            self._load_index()
            
            # NOTE: Engine will be lazily initialized on first search via _ensure_engine_ready()
            # This avoids blocking UI startup while still ensuring engine is ready when needed
            
        except Exception as e:
            logger.error(f"Failed to create inference service: {e}")

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
        header_container.setStyleSheet("background-color: transparent;")
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(24, 24, 24, 10)
        
        title = SubtitleLabel("AI 智能检索与打标")
        desc = CaptionLabel("基于 CLAP 模型 (DirectML 加速)")
        desc.setTextColor(Qt.GlobalColor.gray)
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        
        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="search", text="语义检索")
        self.pivot.addItem(routeKey="tagging", text="智能打标")
        self.pivot.setCurrentItem("search")
        self.pivot.currentItemChanged.connect(lambda k: self.stack.setCurrentIndex(0 if k == "search" else 1))
        header_layout.addWidget(self.pivot)
        
        # 1.1 Global Selection Status Card (Visible for both tabs)
        self.selection_status_card = CardWidget(self)
        self.selection_status_card.setFixedHeight(70)
        status_layout = QHBoxLayout(self.selection_status_card)
        status_layout.setContentsMargins(20, 10, 20, 10)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.tag_status_title = StrongBodyLabel("未选择文件")
        self.tag_status_desc = CaptionLabel("请在音效库中勾选需要处理的文件")
        self.tag_status_desc.setTextColor(Qt.GlobalColor.gray)
        info_layout.addWidget(self.tag_status_title)
        info_layout.addWidget(self.tag_status_desc)
        
        status_layout.addLayout(info_layout)
        status_layout.addStretch()
        
        # Explicit Indexing Button
        self.clear_index_btn = TransparentPushButton(FluentIcon.DELETE, "清除索引", self)
        self.clear_index_btn.setFixedWidth(120)
        self.clear_index_btn.clicked.connect(self._on_clear_index)
        status_layout.addWidget(self.clear_index_btn)
        
        self.build_index_btn = PrimaryPushButton(FluentIcon.FINGERPRINT, "建立 AI 检索索引")
        self.build_index_btn.setFixedWidth(180)
        self.build_index_btn.setEnabled(False)
        self.build_index_btn.clicked.connect(self._on_start_indexing_manual)
        status_layout.addWidget(self.build_index_btn)
        
        header_layout.addWidget(self.selection_status_card)
        
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
        
    def _create_search_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 10, 24, 24)
        layout.setSpacing(20)
        
        # Search Bar Area
        search_card = ElevatedCardWidget()
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(20, 20, 20, 20)
        
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("描述你想要的声音，例如：'雨中的雷声' 或 '赛车引擎'...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(45)
        f = self.search_input.font()
        f.setPointSize(11)
        self.search_input.setFont(f)
        
        # 连接搜索信号：点击搜索按钮（searchSignal 会传递文本参数）
        self.search_input.searchSignal.connect(self._on_search)
        # 连接回车键：按下回车也触发搜索（returnPressed 不传递参数，需要手动获取文本）
        self.search_input.returnPressed.connect(lambda: self._on_search(self.search_input.text()))
        
        search_layout.addWidget(self.search_input)
        
        # Indexing Status
        self.indexing_bar = ProgressBar()
        self.indexing_bar.setVisible(False)
        self.indexing_label = CaptionLabel("")
        self.indexing_label.setVisible(False)
        search_layout.addWidget(self.indexing_bar)
        search_layout.addWidget(self.indexing_label)
        
        layout.addWidget(search_card)
        
        # Search Options
        options_layout = QHBoxLayout()
        options_layout.addStretch()
        self.search_in_selection_switch = SwitchButton(self)
        self.search_in_selection_switch.setOnText("仅在选中范围中搜索")
        self.search_in_selection_switch.setOffText("搜索整个库")
        options_layout.addWidget(self.search_in_selection_switch)
        layout.addLayout(options_layout)
        
        # Results
        self.list_header = BodyLabel("待索引文件 / 搜索结果")
        layout.addWidget(self.list_header)
        
        self.results_list = QListWidget()
        self.results_list.setFrameShape(QFrame.Shape.NoFrame)
        self.results_list.setStyleSheet("background: transparent;")
        self.results_list.setAlternatingRowColors(True)
        self.results_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.results_list)
        
        return page

    def _create_tagging_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 10, 24, 24)
        layout.setSpacing(20)
        
        # Execution Card
        exec_card = CardWidget(self)
        exec_layout = QHBoxLayout(exec_card)
        exec_layout.setContentsMargins(20, 20, 20, 20)
        
        exec_info = QVBoxLayout()
        exec_info.addWidget(StrongBodyLabel("批量分析工站"))
        exec_info.addWidget(CaptionLabel("使用 AI 模型对选中的文件进行自动化标签分类"))
        exec_layout.addLayout(exec_info)
        exec_layout.addStretch()
        
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

    def update_selection(self, file_paths: list[str]):
        """槽函数：接收从音效库选中的文件"""
        self.selected_files = file_paths
        count = len(file_paths)
        
        logger.info(f"AI Search: update_selection received {count} files")
        
        # Update UI
        if count > 0:
            self.tag_status_title.setText(f"已就绪: {count} 个音效文件")
            self.tag_status_desc.setText("点击右侧按钮建立 AI 索引以解锁搜索与打标")
            self.build_index_btn.setEnabled(True)
            self.build_index_btn.setText("建立 AI 检索索引") # Reset text
            self.start_tag_btn.setEnabled(False) 
        else:
            self.tag_status_title.setText("未选择文件")
            self.tag_status_desc.setText("请在音效库中勾选需要处理的文件")
            self.build_index_btn.setEnabled(False)
            self.start_tag_btn.setEnabled(False)

    def _on_start_indexing_manual(self):
        """手动触发索引建立"""
        logger.info(f"AI Search: _on_start_indexing_manual called, selected_files count: {len(self.selected_files)}")
        if not self.selected_files:
            logger.warning("AI Search: No files selected for indexing")
            return
        self.add_files(self.selected_files)

    def _on_start_tagging(self):
        """执行批量打标 (后台线程 + 实时更新)"""
        if not self.engine:
            InfoBar.error(title="引擎未就绪", content="AI 模型尚未加载完成", parent=self)
            return
        
        # 确保引擎已初始化
        if not self._ensure_engine_ready():
            return
        
        self.tag_log.append("▶ 开始 AI 智能打标任务...")
        self.start_tag_btn.setEnabled(False)
        
        # 0. Precompute Tag Embeddings (One-time cost)
        if not self.tag_embeddings:
            self.tag_log.append("正在初始化标签库特征 (首次运行需耗时 10-20秒)...")
            QApplication.processEvents()
            
            try:
                for idx, tag in enumerate(self.AUDIO_CATEGORIES):
                    # Show progress every 10 tags
                    if idx % 5 == 0:
                        self.tag_log.append(f"构建索引 [{idx}/{len(self.AUDIO_CATEGORIES)}]...")
                        QApplication.processEvents()
                    
                    embed = self.engine.get_text_embedding(tag)
                    if embed is not None:
                        # Normalize immediately for fast cosine sim
                        norm = np.linalg.norm(embed)
                        if norm > 0:
                            embed = embed / norm
                        self.tag_embeddings[tag] = embed
                
                self.tag_log.append("✅ 标签库初始化完成")
            except Exception as e:
                InfoBar.error(title="初始化失败", content=str(e), parent=self)
                self.start_tag_btn.setEnabled(True)
                return
        
        # Prepare Matrix for Vectorized Search
        tag_list = list(self.tag_embeddings.keys())
        tag_matrix = np.array([self.tag_embeddings[t] for t in tag_list])
        
        # 启动后台线程
        from transcriptionist_v3.ui.utils.workers import TaggingWorker, cleanup_thread
        
        self._tagging_thread = QThread()
        self._tagging_worker = TaggingWorker(
            engine=self.engine,
            selected_files=self.selected_files,
            audio_embeddings=self.audio_embeddings,
            tag_embeddings=self.tag_embeddings,
            tag_list=tag_list,
            tag_matrix=tag_matrix,
            tag_translations=self.tag_translations
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
    
    def _on_tagging_log(self, message: str):
        """接收日志消息"""
        self.tag_log.append(message)
    
    def _on_tagging_progress(self, current: int, total: int, msg: str):
        """接收进度更新"""
        # 可以在这里更新进度条（如果有的话）
        pass
    
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
    
    def _on_tagging_error(self, error_msg: str):
        """打标任务出错"""
        from transcriptionist_v3.ui.utils.workers import cleanup_thread
        
        cleanup_thread(self._tagging_thread, self._tagging_worker)
        
        self.tag_log.append(f"\n❌ 发生错误: {error_msg}")
        InfoBar.error(title="打标出错", content=error_msg, parent=self)
        self.start_tag_btn.setEnabled(True)

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
        """Handle search execution refined"""
        if not text.strip():
            return
            
        # CRITICAL FIX: 确保引擎已初始化（懒加载）
        if not self._ensure_engine_ready():
            return
            
        if not self.audio_embeddings:
            InfoBar.warning(title="无数据", content="请勾选文件并进入 AI 检索页面以建立索引", parent=self)
            return

        # 0. Translation Augmentation (ZH -> EN)
        # Check if text contains Chinese (simple heuristic)
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
            
        # 1. Compute Text Embedding (using potentially translated text)
        text_embed = self.engine.get_text_embedding(search_query)
        if text_embed is None:
            InfoBar.error(title="特征提取失败", content="无法提取搜索词的特征向量", parent=self, duration=2000)
            return
            
        # 2. Filtering & Similarity Calculation
        only_selected = self.search_in_selection_switch.isChecked()
        selected_set = set(str(p) for p in self.selected_files)
        
        results = []
        # 确保键统一为字符串格式
        for path_key, audio_embed in self.audio_embeddings.items():
            # 统一转换为字符串路径
            path_str = str(path_key)
            
            if only_selected and path_str not in selected_set:
                continue
                
            norm_text = np.linalg.norm(text_embed)
            norm_audio = np.linalg.norm(audio_embed)
            
            if norm_audio == 0 or norm_text == 0:
                sim = 0
            else:
                sim = np.dot(text_embed, audio_embed) / (norm_text * norm_audio)
                
            results.append((path_str, sim))
        
        logger.info(f"AI Search: found {len(results)} results for query '{search_query}'")
            
        # 3. Sort
        results.sort(key=lambda x: x[1], reverse=True)
        
        # 4. Update UI
        self.results_list.clear()
        self.list_header.setText(f"搜索结果: '{text}' (共 {len(results)} 条)")
        
        if not results:
            self.results_list.addItem("未找到匹配结果" + (" (当前仅搜索已选文件)" if only_selected else ""))
            return
            
        # Top 20 results
        results = results[:20]
        
        for path_str, sim in results:
            name = Path(path_str).name
            score_text = f"{sim:.2%}"
            item = QListWidgetItem(f"{name}  (匹配度: {score_text})")
            item.setToolTip(path_str)
            item.setIcon(FluentIcon.MUSIC.icon())
            item.setSizeHint(QSize(0, 40))  # Increase height
            
            # 高匹配度变色
            if sim > 0.4:
                item.setForeground(Qt.GlobalColor.green)
            
            self.results_list.addItem(item)

    def add_files(self, file_paths: list[str]):
        """Receive files from Library and start indexing"""
        
        logger.info(f"AI Search: add_files called with {len(file_paths)} files")
        
        if not file_paths:
            InfoBar.warning(
                title="未选择文件",
                content="请先在音效库中选择要索引的文件",
                parent=self,
                duration=2000
            )
            return
        
        # Filter already indexed
        new_files = [p for p in file_paths if str(p) not in self.audio_embeddings]
        
        logger.info(f"AI Search: {len(new_files)} new files to index (total: {len(file_paths)}, already indexed: {len(file_paths) - len(new_files)})")
        
        if not new_files:
            self.start_tag_btn.setEnabled(True)
            self.build_index_btn.setText("索引已就绪")
            InfoBar.info(
                title="全部就绪",
                content="所选文件此前已完成索引，可直接使用",
                parent=self,
                duration=2000
            )
            return

        # Start Indexing Worker
        self.build_index_btn.setEnabled(False)
        self.build_index_btn.setText("正在建立索引...")
        
        self.results_list.clear()
        for path in new_files:
            item = QListWidgetItem(f"{Path(path).name} (等待索引...)")
            self.results_list.addItem(item)
        
        # Start Indexing Worker
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
        
        self._indexing_thread = QThread()
        self._indexing_worker = CLAPIndexingWorker(self.engine, new_files)
        self._indexing_worker.moveToThread(self._indexing_thread)
        
        self._indexing_thread.started.connect(self._indexing_worker.run)
        self._indexing_worker.progress.connect(self._on_indexing_progress)
        self._indexing_worker.finished.connect(self._on_indexing_finished)
        self._indexing_worker.error.connect(self._on_indexing_error)
        
        self._indexing_thread.start()

    def _on_indexing_progress(self, current, total, msg):
        self.indexing_bar.setValue(int(current / total * 100))
        self.indexing_label.setText(f"正在建立索引: {msg}")

    def _on_indexing_finished(self, results: dict):
        cleanup_thread(self._indexing_thread, self._indexing_worker)
        
        # Merge results
        self.audio_embeddings.update(results)
        
        # Persist immediately
        self._save_index()
        
        self.indexing_bar.setVisible(False)
        self.indexing_label.setVisible(False)
        self.search_input.setEnabled(True)
        self.build_index_btn.setEnabled(True)
        self.build_index_btn.setText("索引已更新")
        self.start_tag_btn.setEnabled(True) # Unlock tagging
        
        # Clean current list and invite search
        self.results_list.clear()
        self.list_header.setText("索引已就绪")
        item = QListWidgetItem("✅ 索引更新成功，功能已解锁。")
        self.results_list.addItem(item)
            
        InfoBar.success(
            title="索引完成",
            content=f"已成功为 {len(results)} 个文件建立索引",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000
        )

    def _on_indexing_error(self, msg):
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
        
        w = MessageBox(
            "确认清除",
            "确定要删除所有已建立的 AI 检索索引吗？这将导致无法使用语义搜索功能，直到您重新建立索引。",
            self
        )
        if w.exec():
            # 1. Clear Memory
            self.audio_embeddings.clear()
            
            # 2. Clear Disk
            try:
                if self._index_path.exists():
                    self._index_path.unlink()
                    logger.info("Index file deleted")
            except Exception as e:
                logger.error(f"Failed to delete index file: {e}")
                
            # 3. Reset UI
            self.results_list.clear()
            self.list_header.setText("索引已清除")
            self.results_list.addItem("暂无索引数据")
            
            # Enable build button since we are empty (if files are selected)
            if self.selected_files:
                self.build_index_btn.setEnabled(True)
                self.build_index_btn.setText("建立 AI 检索索引")
            
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
        """Load embeddings from disk"""
        try:
            if self._index_path.exists():
                logger.info(f"Loading index from {self._index_path}")
                # allow_pickle=True is required for dictionary
                data = np.load(self._index_path, allow_pickle=True)
                # Handle 0-d array if saved as such
                if data.ndim == 0:
                    self.audio_embeddings = data.item()
                else:
                    logger.warning("Invalid index format")
                    
                logger.info(f"Loaded {len(self.audio_embeddings)} items from index")
                
                # 更新 UI 状态：索引已就绪
                if self.audio_embeddings:
                    self.build_index_btn.setText("索引已就绪")
                    self.build_index_btn.setEnabled(True)
                    self.start_tag_btn.setEnabled(True)
                    
                    # 更新结果列表提示
                    self.results_list.clear()
                    self.list_header.setText("索引已就绪")
                    item = QListWidgetItem(f"✅ 已加载 {len(self.audio_embeddings)} 个文件的索引，可以开始搜索")
                    self.results_list.addItem(item)
                    
                    logger.info("Index loaded successfully, UI updated")
            else:
                logger.info("No existing index found")
                
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            # Reset on error to stay safe
            self.audio_embeddings = {}

    def _translate_text_sync(self, text: str, target_lang: str = "en") -> str:
        """Synchronously translate text (blocking but fast enough for short text)"""
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
        
        # Simple prompt construction based on target
        if target_lang == "en":
            sys_prompt = "You are a translator. Translate the following Chinese audio description to English. Output ONLY the English translation."
        else:
            sys_prompt = """你是一位专业的影视音效标签翻译专家。

### 任务
将以下英文音效标签翻译为简洁、通俗易懂的中文。

### 翻译原则
1. **口语化优先**：使用影视后期制作人员日常使用的说法，避免生硬的直译
2. **简洁明了**：优先使用2-4个字的简短词汇，让用户一眼就能看懂
3. **行业习惯**：遵循中文影视音效行业的常用术语

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
