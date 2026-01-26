"""
音效库页面 - 完整功能版本
支持：文件夹导入、树形结构、元数据提取、高级搜索、播放、批量操作
集成后端：LibraryScanner, MetadataExtractor
"""

import csv
import json
import logging
import os
import asyncio
from pathlib import Path
from collections import defaultdict
from typing import Optional, Dict, List
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidgetItem,
    QFileDialog, QHeaderView, QAbstractItemView, QStackedWidget, QApplication
)
from PySide6.QtGui import QFont, QColor

from qfluentwidgets import (
    PushButton, PrimaryPushButton, SearchLineEdit,
    FluentIcon, TreeWidget,
    TitleLabel, CaptionLabel, CardWidget, IconWidget,
    SubtitleLabel, BodyLabel, TransparentToolButton,
    CheckBox, ProgressBar, ComboBox
)

# Architecture refactoring: use centralized utilities
from transcriptionist_v3.core.utils import format_file_size, format_duration, format_sample_rate
from transcriptionist_v3.ui.utils.notifications import NotificationHelper
from transcriptionist_v3.ui.utils.workers import DatabaseLoadWorker, cleanup_thread
from transcriptionist_v3.application.search_engine.search_engine import SearchEngine
from transcriptionist_v3.infrastructure.database.connection import session_scope

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a", ".mp4"}


class ScanWorker(QObject):
    """后台扫描工作线程"""
    progress = Signal(int, int, str)  # scanned, total, current_file
    finished = Signal(list)  # List of (path, metadata) tuples
    error = Signal(str)
    
    def __init__(self, folder_path: str, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """执行扫描"""
        try:
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            
            extractor = MetadataExtractor()
            folder = Path(self.folder_path)
            
            # 第一遍：收集所有音频文件
            audio_files = []
            for root, dirs, files in os.walk(folder):
                if self._cancelled:
                    return
                for filename in files:
                    file_path = Path(root) / filename
                    if file_path.suffix.lower() in SUPPORTED_FORMATS:
                        audio_files.append(file_path)
            
            total = len(audio_files)
            results = []
            
            # 第二遍：提取元数据
            for i, file_path in enumerate(audio_files):
                if self._cancelled:
                    return
                
                self.progress.emit(i + 1, total, str(file_path))
                
                try:
                    metadata = extractor.extract(file_path)
                    results.append((file_path, metadata))
                except Exception as e:
                    logger.warning(f"Failed to extract metadata from {file_path}: {e}")
                    results.append((file_path, None))
            
            self.finished.emit(results)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            self.error.emit(str(e))


class EmptyStateWidget(QWidget):
    """空状态组件"""
    
    import_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        icon = IconWidget(FluentIcon.MUSIC_FOLDER)
        icon.setFixedSize(80, 80)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        
        title = SubtitleLabel("开始管理您的音效")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        desc = CaptionLabel("导入文件夹以开始浏览和管理音效文件")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        # 用户要求移除此处按钮，仅保留顶部工具栏按钮
        # import_btn = PrimaryPushButton(FluentIcon.FOLDER_ADD, "导入文件夹")
        # import_btn.setFixedWidth(160)
        # import_btn.clicked.connect(self.import_clicked.emit)
        # layout.addWidget(import_btn, alignment=Qt.AlignmentFlag.AlignCenter)


class LoadingStateWidget(QWidget):
    """加载状态组件 - 显示数据库加载进度"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        icon = IconWidget(FluentIcon.SYNC)
        icon.setFixedSize(64, 64)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.title_label = SubtitleLabel("正在加载音效库...")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedWidth(300)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.status_label = CaptionLabel("正在从数据库读取文件信息...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
    
    def update_progress(self, current: int, total: int, message: str):
        """更新加载进度"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"加载中 {current}/{total} ({percent}%)")
        else:
            self.progress_bar.setValue(0)
            self.status_label.setText(message)


class ScanProgressWidget(QWidget):
    """扫描进度组件"""
    
    cancel_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        icon = IconWidget(FluentIcon.SYNC)
        icon.setFixedSize(64, 64)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.title_label = SubtitleLabel("正在扫描文件夹...")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedWidth(300)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.status_label = CaptionLabel("准备中...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        cancel_btn = PushButton(FluentIcon.CLOSE, "取消")
        cancel_btn.clicked.connect(self.cancel_clicked.emit)
        layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def update_progress(self, scanned: int, total: int, current_file: str):
        if total > 0:
            self.progress_bar.setValue(int(scanned / total * 100))
        self.status_label.setText(f"已扫描 {scanned}/{total} - {Path(current_file).name}")


class FileInfoCard(CardWidget):
    """文件信息卡片 - 显示选中文件的详细信息"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 标题
        title = SubtitleLabel("文件信息")
        layout.addWidget(title)
        
        # 文件名
        self.name_label = BodyLabel("未选择文件")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        
        # 分隔线
        layout.addSpacing(8)
        
        # 元数据信息
        self.info_layout = QVBoxLayout()
        self.info_layout.setSpacing(6)
        layout.addLayout(self.info_layout)
        
        # 创建信息行
        self._info_labels = {}
        info_items = [
            ("original_name", "原文件名", FluentIcon.INFO), # Changed to INFO
            ("duration", "时长", FluentIcon.HISTORY),
            ("format", "格式", FluentIcon.DOCUMENT),
            ("sample_rate", "采样率", FluentIcon.SETTING),
            ("channels", "声道", FluentIcon.SPEAKERS),
            ("bit_depth", "位深", FluentIcon.ALBUM),
            ("size", "大小", FluentIcon.FOLDER),
        ]
        
        for key, label, icon in info_items:
            row = QHBoxLayout()
            row.setSpacing(8)
            
            icon_widget = IconWidget(icon)
            icon_widget.setFixedSize(16, 16)
            row.addWidget(icon_widget)
            
            name_lbl = CaptionLabel(f"{label}:")
            name_lbl.setFixedWidth(60) # Increased width for "原文件名"
            row.addWidget(name_lbl)
            
            value_lbl = BodyLabel("-")
            value_lbl.setWordWrap(True) # Allow wrapping for long filenames
            self._info_labels[key] = value_lbl
            row.addWidget(value_lbl, 1)
            
            self.info_layout.addLayout(row)
        
        layout.addStretch()

    def update_info(self, file_path: str, metadata):
        """更新文件信息"""
        path = Path(file_path)
        self.name_label.setText(path.name)
        
        if metadata:
            # 原文件名
            orig_name = "-"
            if hasattr(metadata, 'raw') and metadata.raw:
                # Try common keys
                keys_to_check = [
                    'ORIGINAL_FILENAME', 
                    'original_filename',
                    'TXXX:ORIGINAL_FILENAME',
                    '----:com.apple.iTunes:ORIGINAL_FILENAME'
                ]
                for k in keys_to_check:
                    if k in metadata.raw:
                        val = metadata.raw[k]
                        # Mutagen often returns lists
                        if isinstance(val, list) and val:
                            orig_name = str(val[0])
                        else:
                            orig_name = str(val)
                        break
            self._info_labels["original_name"].setText(orig_name)

            # 时长
            duration = metadata.duration if hasattr(metadata, 'duration') else 0
            if duration > 0:
                mins = int(duration // 60)
                secs = int(duration % 60)
                self._info_labels["duration"].setText(f"{mins:02d}:{secs:02d}")
            else:
                self._info_labels["duration"].setText("-")
            
            # 格式
            fmt = metadata.format if hasattr(metadata, 'format') else path.suffix[1:].upper()
            self._info_labels["format"].setText(fmt.upper())
            
            # 采样率
            sr = metadata.sample_rate if hasattr(metadata, 'sample_rate') else 0
            if sr > 0:
                self._info_labels["sample_rate"].setText(f"{sr / 1000:.1f} kHz")
            else:
                self._info_labels["sample_rate"].setText("-")
            
            # 声道
            ch = metadata.channels if hasattr(metadata, 'channels') else 0
            if ch == 1:
                self._info_labels["channels"].setText("单声道")
            elif ch == 2:
                self._info_labels["channels"].setText("立体声")
            elif ch > 0:
                self._info_labels["channels"].setText(f"{ch} 声道")
            else:
                self._info_labels["channels"].setText("-")
            
            # 位深
            bd = metadata.bit_depth if hasattr(metadata, 'bit_depth') else 0
            if bd > 0:
                self._info_labels["bit_depth"].setText(f"{bd} bit")
            else:
                self._info_labels["bit_depth"].setText("-")
        else:
            for key in self._info_labels:
                if key != "size":
                    self._info_labels[key].setText("-")
        
        # 文件大小
        try:
            size = path.stat().st_size
            self._info_labels["size"].setText(self._format_size(size))
        except:
            self._info_labels["size"].setText("-")

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    
    def clear_info(self):
        """清空信息"""
        self.name_label.setText("未选择文件")
        for key in self._info_labels:
            self._info_labels[key].setText("-")


class LibraryPage(QWidget):
    """音效库页面 - 完整功能"""
    
    file_selected = Signal(str)
    files_checked = Signal(list)  # [file_path]
    files_deleted = Signal(list)  # [file_path]
    play_file = Signal(str)       # file_path
    request_ai_translate = Signal(list) # [file_path]
    request_ai_search = Signal(list) # [file_path]   
    
    library_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("libraryPage")
        
        self._audio_files: List[Path] = []
        self._library_roots: List[Path] = []  # Changed: Support multiple roots
        self._file_metadata: Dict[str, object] = {}  # path -> metadata
        self._folder_structure = defaultdict(list)
        # self._root_folder removed/deprecated logic, but keeping for scan context if needed?
        # Better to just use local var in scan, or temporary property.
        # But actually _root_folder was used to determine "current" view context.
        # We will keep it for compatibility if other methods use it, but initialized to None.
        self._root_folder: Optional[Path] = None 
        
        self._selected_files = set()
        self._file_items: Dict[str, QTreeWidgetItem] = {}
        
        # 文件路径到数据库 ID 的映射（用于搜索）
        self._file_path_to_id: Dict[str, int] = {}
        
        # 懒加载相关
        self._all_file_data = []  # 所有文件数据 [(path, metadata), ...]
        self._loaded_count = 0    # 已加载数量
        self._batch_size = 100    # 每批加载数量
        self._is_loading = False  # 是否正在加载
        self._lazy_load_enabled = True  # 懒加载开关（搜索时禁用）
        self._folder_items = {}   # 文件夹节点缓存 {folder_path_str: QTreeWidgetItem}
        self._is_all_selected = False  # 全选状态标记
        
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[ScanWorker] = None
        
        # Database loading thread (async to avoid blocking UI)
        self._db_load_thread: Optional[QThread] = None
        self._db_load_worker: Optional[DatabaseLoadWorker] = None
        
        # Initialize backend search engine
        self._search_engine = SearchEngine(lambda: session_scope())
        
        self._init_ui()
        self._load_from_database_async()  # 异步从数据库加载已有数据

    def _on_db_load_finished(self, data: tuple):
        """数据库加载完成"""
        self._cleanup_db_load_thread()
        
        results, root_paths = data
        
        if not results and not root_paths:
            logger.info("No audio files loaded from database")
            self.stack.setCurrentWidget(self.empty_state)
            return
        
        # 保存所有文件数据（不立即显示）
        self._all_file_data = results
        self._audio_files = [path for path, _ in results]
        self._file_metadata = {str(path): metadata for path, metadata in results}
        
        # 构建文件路径到数据库 ID 的映射（用于搜索）
        self._file_path_to_id = {}
        try:
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            with session_scope() as session:
                for path, _ in results:
                    audio_file = session.query(AudioFile).filter_by(file_path=str(path)).first()
                    if audio_file:
                        self._file_path_to_id[str(path)] = audio_file.id
        except Exception as e:
            logger.error(f"Failed to build file path to ID mapping: {e}")
        
        self._library_roots = root_paths
        
        logger.info(f"Loaded {len(results)} audio files from database, roots: {len(root_paths)}")
        
        # 切换到文件列表视图
        self.stack.setCurrentWidget(self.file_list_widget)
        
        # 懒加载：只加载初始批次
        self._loaded_count = 0
        self._lazy_load_enabled = True
        self._update_tree_lazy()
        
        # 连接滚动信号
        scrollbar = self.tree.verticalScrollBar()
        try:
            scrollbar.valueChanged.disconnect(self._on_scroll)
        except:
            pass
        scrollbar.valueChanged.connect(self._on_scroll)
        
        # 更新统计
        self._update_stats()

    def _update_tree(self):
        """更新文件树 - 支持多根目录"""
        self.tree.clear()
        self._file_items.clear()
        
        if not self._library_roots and not self._audio_files:
            self.stack.setCurrentWidget(self.empty_state)
            # Disable buttons logic here...
            return
        
        # 统计
        total_folders = sum(len(subdict) for subdict in self._folder_structure.values())
        self.stats_label.setText(f"共 {len(self._audio_files)} 个音效，{total_folders} 个子文件夹")
        
        # 阻止信号
        self.tree.blockSignals(True)
        
        for root_path in self._library_roots:
            # Create Root Item
            root_name = root_path.name
            root_item = QTreeWidgetItem([root_name, "", "", "", "", ""])
            root_item.setIcon(0, FluentIcon.FOLDER.icon())
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
            root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
            root_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(root_item)
            
            # Populate children for this root
            root_structure = self._folder_structure.get(root_path, {})
            folder_items = {".": root_item}
            
            sorted_folders = sorted(root_structure.keys(), key=lambda p: (p.count('/'), p.lower()))
            
            for folder_rel_path in sorted_folders:
                files = root_structure[folder_rel_path]
                
                if folder_rel_path == ".":
                    parent_item = root_item
                else:
                    parts = folder_rel_path.split('/')
                    current_path = ""
                    parent_item = root_item
                    
                    for part in parts:
                        current_path = f"{current_path}/{part}" if current_path else part
                        
                        if current_path not in folder_items:
                            folder_item = QTreeWidgetItem([part, "", "", "", "", ""])
                            folder_item.setIcon(0, FluentIcon.FOLDER.icon())
                            # Full path reconstruction
                            full_folder_path = root_path / current_path
                            folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(full_folder_path)})
                            folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                            parent_item.addChild(folder_item)
                            folder_items[current_path] = folder_item
                        
                        parent_item = folder_items[current_path]
                
                for file_path in sorted(files, key=lambda f: f.name.lower()):
                    self._create_file_item(parent_item, file_path)
            
            root_item.setExpanded(True)
            
        self.tree.blockSignals(False)
        self._update_selected_count()

    def _create_file_item(self, parent_item, file_path):
        """Helper to create file item node - optimized for large libraries"""
        file_path_str = str(file_path)
        metadata = self._file_metadata.get(file_path_str)
        
        # 时长
        duration_str = "-"
        if metadata and hasattr(metadata, 'duration') and metadata.duration > 0:
            mins = int(metadata.duration // 60)
            secs = int(metadata.duration % 60)
            duration_str = f"{mins:02d}:{secs:02d}"
        
        # 格式
        ext = file_path.suffix.upper()[1:]
        
        # 创建文件项（只有3列：名称、时长、格式）
        file_item = QTreeWidgetItem([file_path.name, duration_str, ext])
        file_item.setIcon(0, FluentIcon.MUSIC.icon())
        file_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "file", "path": file_path_str})
        file_item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # 完整的 tooltip 信息
        orig_name = getattr(metadata, 'original_filename', file_path.name) if metadata else file_path.name
        tags = getattr(metadata, 'tags', []) if metadata else []
        tags_str = ", ".join(tags[:3]) + ("..." if len(tags) > 3 else "") if tags else "未打标"
        
        # 获取详细信息
        if metadata:
            duration_str = format_duration(metadata.duration) if metadata.duration else "未知"
            sample_rate_str = format_sample_rate(metadata.sample_rate) if metadata.sample_rate else "未知"
            format_str = metadata.format.upper() if metadata.format else file_path.suffix.lstrip('.').upper()
        else:
            duration_str = "未知"
            sample_rate_str = "未知"
            format_str = file_path.suffix.lstrip('.').upper()
        
        tooltip = f"{file_path.name}\n源文件: {orig_name}\n标签: {tags_str}\n时长: {duration_str} | 采样率: {sample_rate_str} | 格式: {format_str}"
        file_item.setToolTip(0, tooltip)
        
        parent_item.addChild(file_item)
        
        # Use normalized path for robust lookup
        self._file_items[os.path.normpath(file_path_str)] = file_item
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部工具栏
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # 内容区域 - 使用 QStackedWidget 切换状态
        self.stack = QStackedWidget()
        
        # 状态0: 加载状态（新增）
        self.loading_state = LoadingStateWidget()
        self.stack.addWidget(self.loading_state)
        
        # 状态1: 空状态
        self.empty_state = EmptyStateWidget()
        self.empty_state.import_clicked.connect(self._on_import_folder)
        self.stack.addWidget(self.empty_state)
        
        # 状态2: 扫描进度
        self.scan_progress = ScanProgressWidget()
        self.scan_progress.cancel_clicked.connect(self._on_cancel_scan)
        self.stack.addWidget(self.scan_progress)
        
        # 状态3: 文件列表
        self.file_list_widget = self._create_file_list()
        self.stack.addWidget(self.file_list_widget)
        
        layout.addWidget(self.stack, 1)
        
        # 初始显示加载状态
        self.stack.setCurrentWidget(self.loading_state)
    
    def _create_toolbar(self) -> QWidget:
        """创建紧凑型工具栏 - 统一单行布局"""
        toolbar_container = QWidget()
        main_layout = QVBoxLayout(toolbar_container)
        main_layout.setContentsMargins(10, 8, 10, 4)
        main_layout.setSpacing(4)
        
        # 第一行：主工具栏
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 1. 导入按钮 (Primary Action)
        self.import_btn = PrimaryPushButton(FluentIcon.FOLDER_ADD, "导入音效库")
        self.import_btn.clicked.connect(self._on_import_folder)
        self.import_btn.setMinimumWidth(115) # 确保文字不被截断
        layout.addWidget(self.import_btn)
        
        # 清空库按钮
        self.clear_lib_btn = TransparentToolButton(FluentIcon.DELETE)
        self.clear_lib_btn.setToolTip("清空音效库")
        self.clear_lib_btn.setFixedSize(32, 32) # 固定大小防止错乱
        self.clear_lib_btn.clicked.connect(self._on_clear_library)
        layout.addWidget(self.clear_lib_btn)
        
        # 2. 搜索框 (Expanding)
        from PySide6.QtWidgets import QSizePolicy
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索... (支持: exp* 或 tags:脚步声)")
        self.search_edit.setMinimumWidth(80) # 设置最小宽度防止完全消失
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # 连接搜索信号：点击搜索按钮（searchSignal 会传递文本参数）
        self.search_edit.searchSignal.connect(lambda text: self._on_search())
        # 连接文本变化：实时搜索（textChanged 会传递文本参数）
        self.search_edit.textChanged.connect(lambda text: self._on_search())
        # 连接回车键：按下回车也触发搜索（returnPressed 不传递参数）
        self.search_edit.returnPressed.connect(self._on_search)
        
        layout.addWidget(self.search_edit)
        
        # 3. 筛选下拉 (Fixed)
        self.search_field = ComboBox()
        self.search_field.addItems(["全部", "文件名", "格式", "时长"])
        self.search_field.setFixedWidth(75)
        self.search_field.currentIndexChanged.connect(self._on_search)
        layout.addWidget(self.search_field)
        
        main_layout.addWidget(toolbar)
        
        # 第二行：搜索提示（可折叠）
        self.search_hint = CaptionLabel("💡 高级搜索: exp* (通配符) | tags:脚步声 (标签) | duration:>10 (时长>10秒)")
        self.search_hint.setTextColor(QColor(150, 150, 150), QColor(150, 150, 150))
        self.search_hint.setVisible(False)  # 默认隐藏
        main_layout.addWidget(self.search_hint)
        
        # 搜索框获得焦点时显示提示 - 使用 installEventFilter 代替直接覆盖
        self.search_edit.installEventFilter(self)

        return toolbar_container

    def _create_file_list(self) -> QWidget:
        """创建简化的文件列表 - 适用于侧边栏"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 选择操作栏
        select_bar = QHBoxLayout()
        select_bar.setSpacing(8)
        
        self.select_all_cb = CheckBox("全选")
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        select_bar.addWidget(self.select_all_cb)
        
        self.stats_label = CaptionLabel("")
        select_bar.addWidget(self.stats_label)
        
        select_bar.addStretch()
        
        self.selected_label = CaptionLabel("已选 0")
        select_bar.addWidget(self.selected_label)
        
        layout.addLayout(select_bar)
        
        # 文件树 - 简化列显示（只显示3列）
        self.tree = TreeWidget()
        self.tree.setHeaderLabels(["名称", "时长", "格式"])  # 只显示关键列
        self.tree.setColumnCount(3)  # 明确设置列数
        
        # 列宽设置
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 50)
        self.tree.setColumnWidth(2, 45)
        
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        
        layout.addWidget(self.tree, 1)
        
        # 创建一个隐藏的 FileInfoCard 以保持 API 兼容性
        self.info_card = FileInfoCard()
        self.info_card.hide()
        
        return container

    def on_file_renamed(self, old_path: str, new_path: str):
        """文件重命名后的回调，同步更新库中的路径"""
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            
            # 1. 更新数据库
            with session_scope() as session:
                audio_file = session.query(AudioFile).filter(AudioFile.file_path == old_path).first()
                if audio_file:
                    audio_file.file_path = new_path
                    audio_file.filename = Path(new_path).name
                    logger.info(f"Database synchronized: {old_path} -> {new_path}")
            
            # 2. 更新内存数据结构 (Audio Files List)
            # Note: _audio_files is List[Path], not List[Tuple[Path, metadata]]
            new_path_obj = Path(new_path)
            for i, path in enumerate(self._audio_files):
                if str(path) == old_path:
                    self._audio_files[i] = new_path_obj
                    break
            
            # Update metadata mapping key AND re-extract metadata to capture ORIGINAL_FILENAME
            if old_path in self._file_metadata:
                self._file_metadata.pop(old_path)
            
            # Re-extract metadata to get the newly written ORIGINAL_FILENAME tag
            try:
                extractor = MetadataExtractor()
                new_metadata = extractor.extract(str(new_path_obj))
                self._file_metadata[new_path] = new_metadata
                logger.info(f"Re-extracted metadata for {new_path_obj.name}")
            except Exception as e:
                logger.warning(f"Failed to re-extract metadata: {e}")
            
            # 3. 更新 UI 树 (O(1) Access using _file_items map)
            norm_old_path = os.path.normpath(old_path)
            norm_new_path = os.path.normpath(new_path)
            
            if norm_old_path in self._file_items:
                item = self._file_items.pop(norm_old_path)
                # Update item appearance
                item.setText(0, new_path_obj.name)
                
                # Update item data
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    data["path"] = new_path
                    item.setData(0, Qt.ItemDataRole.UserRole, data)
                
                # Update map with new key
                self._file_items[norm_new_path] = item
                
                # Highlight the item to show feedback
                self.tree.scrollToItem(item)
                item.setSelected(True)
                
                # Refresh FileInfoCard if this file is currently selected
                if hasattr(self, 'info_card'):
                    new_metadata = self._file_metadata.get(new_path)
                    self.info_card.update_info(new_path, new_metadata)
                
                logger.info(f"UI Tree synchronized directly: {new_path_obj.name}")
            else:
                # 缓存未命中 - 尝试重建缓存
                logger.debug(f"Cache miss for {norm_old_path}, rebuilding cache...")
                self._rebuild_file_items_cache()
                
                # 重试一次
                if norm_old_path in self._file_items:
                    item = self._file_items.pop(norm_old_path)
                    item.setText(0, new_path_obj.name)
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        data["path"] = new_path
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                    self._file_items[norm_new_path] = item
                    logger.info(f"UI Tree synchronized after cache rebuild: {new_path_obj.name}")
                else:
                    # 最后的降级方案：递归查找
                    logger.warning(f"Could not find tree item for {norm_old_path} even after cache rebuild")
                    root = self.tree.invisibleRootItem()
                    self._update_node_path_recursive(root, old_path, new_path)
                
            # 4. 更新选中集合 (如果在选区中)
            if old_path in self._selected_files:
                self._selected_files.discard(old_path)
                self._selected_files.add(new_path)
                    
        except Exception as e:
            logger.error(f"Failed to update database for renamed file: {e}")

    def _update_node_path_recursive(self, parent_item: QTreeWidgetItem, old_path: str, new_path: str):
        """递归查找并更新节点路径"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("path") == old_path:
                data["path"] = new_path
                child.setData(0, Qt.ItemDataRole.UserRole, data)
                child.setText(0, Path(new_path).name)
                logger.info(f"UI Tree synchronized: {old_path} -> {new_path}")
                return True
            if self._update_node_path_recursive(child, old_path, new_path):
                return True
        return False
    
    def _rebuild_file_items_cache(self):
        """重建文件项缓存 - 遍历树并重新建立映射"""
        self._file_items.clear()
        root = self.tree.invisibleRootItem()
        self._rebuild_cache_recursive(root)
        logger.debug(f"Cache rebuilt with {len(self._file_items)} items")
    
    def _rebuild_cache_recursive(self, parent_item: QTreeWidgetItem):
        """递归重建缓存"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            
            # 如果是文件节点，添加到缓存
            if data and data.get("type") == "file":
                file_path = data.get("path")
                if file_path:
                    norm_path = os.path.normpath(file_path)
                    self._file_items[norm_path] = child
            
            # 递归处理子节点
            self._rebuild_cache_recursive(child)
        
    def _collect_files_recursive(self, item: QTreeWidgetItem) -> List[str]:
        """递归收集节点下的所有文件路径"""
        paths = []
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # 如果自己是文件
        if data and data.get("type") == "file":
             path = data.get("path")
             if path:
                 paths.append(path)
        
        # 递归不仅要查子节点，还要注意文件夹节点本身不包含路径信息（除了作为容器）
        # 遍历子节点
        for i in range(item.childCount()):
            child = item.child(i)
            paths.extend(self._collect_files_recursive(child))
            
        return paths

    def on_delete_selected(self):
        """删除库中选中的音效 (仅从数据库移除)"""
        selected_items = self.tree.selectedItems()
        
        if not selected_items:
            # Try to get the item under cursor if context menu invoked it
            # But context menu usually is modal, so we rely on selection.
            # If right click didn't select, we might have 0 items.
            # logger.warning("No items selected for deletion.")
            return
            
        # 收集所有涉及的文件路径（支持文件夹递归）
        paths_to_delete = set()
        
        for item in selected_items:
            found_paths = self._collect_files_recursive(item)
            paths_to_delete.update(found_paths)
        
        file_items_count = len(paths_to_delete)
        logger.info(f"Deletion request: {file_items_count} files found in selection")

        if file_items_count == 0:
            NotificationHelper.warning(self, "未选中文件", "所选项目中不包含任何音频文件")
            return
            
        from qfluentwidgets import MessageDialog
        dialog = MessageDialog("确认移除", f"确定从音效库中移除这 {file_items_count} 个音效吗？\n(注意：这仅会从软件中移除记录，不会删除您的物理文件)", self)
        if not dialog.exec():
            return
            
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            
            # Convert set to list for query
            target_paths = list(paths_to_delete)
            
            with session_scope() as session:
                session.query(AudioFile).filter(AudioFile.file_path.in_(target_paths)).delete(synchronize_session=False)
                
            logger.info(f"Deleted {len(target_paths)} files from database")
            
            # 立即更新 UI 和缓存 (Fix UI persistence issue)
            for item in selected_items:
                # 1. 递归收集需要清理的路径 Key
                paths_in_node = self._collect_files_recursive(item)
                for p in paths_in_node:
                    norm_p = os.path.normpath(p)
                    # 清理 _file_items 缓存
                    if norm_p in self._file_items:
                        del self._file_items[norm_p]
                    # 清理 _audio_files 列表
                    p_obj = Path(p)
                    if p_obj in self._audio_files:
                        self._audio_files.remove(p_obj)
                    # 清理 metadata
                    if str(p_obj) in self._file_metadata:
                        del self._file_metadata[str(p_obj)]
                
                # 2. 从树中移除节点
                parent = item.parent()
                if parent:
                    parent.removeChild(item)
                else:
                    index = self.tree.indexOfTopLevelItem(item)
                    self.tree.takeTopLevelItem(index)
            
            self._selected_files.clear()
            self._update_selected_count()
            
            NotificationHelper.success(self, "移除成功", f"已从库中移除 {len(target_paths)} 个文件")
            
            # Emit signal for deleted files
            self.files_deleted.emit(target_paths)

            # 不需要完全重新加载，因为 UI 已经同步
            # self._load_from_database_async()
            
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            NotificationHelper.error(self, "移除失败", str(e))

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        from qfluentwidgets import RoundMenu, Action
        
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        # 如果当前未选中该项，且没有多选其他项，则选中它
        # Ensures that right-click operations apply to the item under cursor
        if not item.isSelected():
            # If nothing else is selected, or if we want to switch selection to this item
            # Standard behavior: Right click selects the item if it's not part of current selection
            if len(self.tree.selectedItems()) <= 1:
                self.tree.setCurrentItem(item)
                item.setSelected(True)
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        is_file = data.get("type") == "file"
        
        menu = RoundMenu(parent=self)
        
        if is_file:
            # 播放
            play_action = Action(FluentIcon.PLAY, "播放", self)
            play_action.triggered.connect(lambda: self.play_file.emit(data.get("path")))
            menu.addAction(play_action)
            
            # 打开文件夹
            open_folder_action = Action(FluentIcon.FOLDER, "在文件夹中显示", self)
            open_folder_action.triggered.connect(lambda: self._open_file_folder(data.get("path")))
            menu.addAction(open_folder_action)
            
            menu.addSeparator()
            
        # 从库中移除
        delete_action = Action(FluentIcon.DELETE, "从库中移除", self)
        delete_action.triggered.connect(self.on_delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.tree.mapToGlobal(pos))

    def _open_file_folder(self, file_path: str):
        """打开文件所在文件夹"""
        import subprocess
        path = Path(file_path).parent
        if path.exists():
            subprocess.run(['explorer', str(path)])

    def _on_import_folder(self):
        """选择并导入文件夹（支持多选）"""
        # 使用 Qt 非原生对话框实现多选
        # 这是最稳定的方案，不依赖 pywin32 或 ctypes
        dialog = QFileDialog(self)
        dialog.setWindowTitle("选择音效文件夹（按住 Ctrl/Shift 可多选）")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        
        # 尝试设置初始目录
        if self._library_roots:
            dialog.setDirectory(str(self._library_roots[0]))
        else:
            import os
            desktop = os.path.expanduser("~/Desktop")
            if os.path.exists(desktop):
                dialog.setDirectory(desktop)

        # 核心 Hack: 找到内部视图并开启多选
        from PySide6.QtWidgets import QListView, QTreeView, QAbstractItemView
        
        views = []
        views.extend(dialog.findChildren(QListView))
        views.extend(dialog.findChildren(QTreeView))
        
        for view in views:
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        if dialog.exec():
            folders = dialog.selectedFiles()
            if folders:
                logger.info(f"Selected {len(folders)} folder(s): {folders}")
                self._import_folders_batch(folders)

    
    def _import_folders_batch(self, folders: list):
        """批量导入多个文件夹"""
        self._folders_to_import = folders.copy()
        self._current_import_index = 0
        self._start_next_folder_import()
    
    def _start_next_folder_import(self):
        """开始导入下一个文件夹"""
        if self._current_import_index < len(self._folders_to_import):
            folder = self._folders_to_import[self._current_import_index]
            logger.info(f"Importing folder {self._current_import_index + 1}/{len(self._folders_to_import)}: {folder}")
            self._start_scan(folder)
        else:
            # All folders imported
            logger.info("All folders imported successfully")
            NotificationHelper.success(
                self,
                "批量导入完成",
                f"已成功导入 {len(self._folders_to_import)} 个文件夹",
                duration=3000
            )
    
    def _start_scan(self, folder_path: str):
        """开始扫描"""
        # 切换到扫描进度状态
        self.stack.setCurrentWidget(self.scan_progress)
        self.scan_progress.progress_bar.setValue(0)
        self.scan_progress.status_label.setText("准备中...")
        
        # 禁用导入按钮
        self.import_btn.setEnabled(False)
        
        # 创建工作线程
        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(folder_path)
        self._scan_worker.moveToThread(self._scan_thread)
        
        # 连接信号
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        
        # 保存根目录
        self._root_folder = Path(folder_path)
        
        # 启动线程
        self._scan_thread.start()

    def _on_cancel_scan(self):
        """取消扫描"""
        if self._scan_worker:
            self._scan_worker.cancel()
        self._cleanup_scan_thread()
        self.stack.setCurrentWidget(self.empty_state)
        self.import_btn.setEnabled(True)
    
    def _on_scan_progress(self, scanned: int, total: int, current_file: str):
        """扫描进度更新"""
        self.scan_progress.update_progress(scanned, total, current_file)
    
    def _on_scan_finished(self, results: list):
        """扫描完成"""
        self._cleanup_scan_thread()
        self.import_btn.setEnabled(True)
        
        # 处理结果
        self._audio_files = []
        self._file_metadata = {}
        # Keep existing structure, will be rebuilt by DB load anyway but scan needs to save first
        self._folder_structure = defaultdict(list) 
        self._selected_files.clear()
        self._file_items.clear()
        
        # 保存到数据库
        saved_count = 0
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath
            import hashlib
            
            with session_scope() as session:
                # 记录扫描的路径
                lib_path = session.query(LibraryPath).filter_by(path=str(self._root_folder)).first()
                if not lib_path:
                    lib_path = LibraryPath(
                        path=str(self._root_folder),
                        enabled=True,
                        recursive=True
                    )
                    session.add(lib_path)
                
                lib_path.last_scan_at = datetime.now()
                lib_path.file_count = len(results)
                
                # 批量查询已存在的文件路径（优化性能）
                file_paths = [str(fp) for fp, _ in results]
                existing_paths = {row.file_path for row in session.query(AudioFile.file_path).filter(AudioFile.file_path.in_(file_paths)).all()}
                
                # 批量准备新文件
                new_files = []
                for file_path, metadata in results:
                    if metadata and str(file_path) not in existing_paths:
                        # 跳过SHA256哈希计算以加速导入（节省20-40秒）
                        # 使用空字符串代替，因为实际上没有用到这个字段做去重
                        
                        # 创建新记录
                        audio_file = AudioFile(
                            file_path=str(file_path),
                            filename=file_path.name,
                            file_size=file_path.stat().st_size,
                            content_hash="",
                            duration=metadata.duration,
                            sample_rate=metadata.sample_rate,
                            bit_depth=metadata.bit_depth or 16,
                            channels=metadata.channels,
                            format=file_path.suffix.lstrip('.').lower(),
                            description=getattr(metadata, 'description', None) or metadata.comment,
                            original_filename=file_path.name  # Save original filename
                        )
                        new_files.append(audio_file)
                
                # 批量插入（比逐个插入快3-8秒）
                if new_files:
                    session.bulk_save_objects(new_files)
                    saved_count = len(new_files)
                
                session.commit()
                logger.info(f"Saved {saved_count} new files to database")
                NotificationHelper.success(self, "扫描完成", f"已成功导入 {saved_count} 个新音效文件")
                
                # 重新加载UI显示
                self._load_from_database_async()
            
        except Exception as e:
            logger.error(f"Failed to save to database: {e}")
            NotificationHelper.error(self, "数据库错误", f"保存扫描结果失败: {e}")
        
        # 切换到文件列表
        self.stack.setCurrentWidget(self.file_list_widget)
        
        # Check if we're in batch import mode
        if hasattr(self, '_folders_to_import') and self._folders_to_import:
            # Batch import mode: move to next folder
            self._current_import_index += 1
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, self._start_next_folder_import)
        else:
            # Single folder mode: ask if user wants to continue
            from qfluentwidgets import MessageDialog
            dialog = MessageDialog(
                "继续导入？",
                "当前文件夹导入完成。您想要继续导入其他文件夹吗？",
                self
            )
            dialog.yesButton.setText("继续导入")
            dialog.cancelButton.setText("完成")
            
            if dialog.exec():
                # Trigger import again
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._on_import_folder)
            else:
                NotificationHelper.success(
                    self,
                    "导入完成",
                    f"本次共导入 {len(results)} 个文件",
                    duration=3000
                )
    
    def _on_scan_error(self, error_msg: str):
        """扫描错误"""
        self._cleanup_scan_thread()
        self.import_btn.setEnabled(True)
        self.stack.setCurrentWidget(self.empty_state)
        
        NotificationHelper.error(
            self,
            "扫描失败",
            error_msg,
            duration=5000
        )
    
    def _cleanup_scan_thread(self):
        """清理扫描线程"""
        cleanup_thread(self._scan_thread, self._scan_worker)
        self._scan_thread = None
        self._scan_worker = None
    
    def _cleanup_db_load_thread(self):
        """清理数据库加载线程"""
        cleanup_thread(self._db_load_thread, self._db_load_worker)
        self._db_load_thread = None
        self._db_load_worker = None
    
    def _load_from_database_async(self):
        """异步从数据库加载已有的音频文件 (不阻塞UI)"""
        # 创建工作线程
        self._db_load_thread = QThread()
        self._db_load_worker = DatabaseLoadWorker()
        self._db_load_worker.moveToThread(self._db_load_thread)
        
        # 连接信号
        self._db_load_thread.started.connect(self._db_load_worker.run)
        self._db_load_worker.finished.connect(self._on_db_load_finished)
        self._db_load_worker.error.connect(self._on_db_load_error)
        self._db_load_worker.progress.connect(self._on_db_load_progress)
        
        self._db_load_thread.start()
        logger.info("Started async database loading")

    def refresh(self):
        """Public refresh method to reload data from database"""
        self._load_from_database_async()
    
    def _on_db_load_progress(self, current: int, total: int, message: str):
        """数据库加载进度"""
        self.loading_state.update_progress(current, total, message)
    
    
    def _on_db_load_error(self, error_msg: str):
        """数据库加载错误"""
        self._cleanup_db_load_thread()
        logger.error(f"Failed to load from database: {error_msg}")

    def _deprecated_update_tree_removed(self):
        # 这个方法duplicate定义被移除以修复崩溃
        pass
    
    def on_translation_applied(self, old_path_str: str, new_path_str: str):
        """处理翻译应用（重命名）同步（从AI翻译页面触发）
        
        支持文件重命名和文件夹重命名。
        """
        import os
        logger.info(f"Translation applied: {old_path_str} -> {new_path_str}")
        
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            
            old_path = Path(old_path_str)
            new_path = Path(new_path_str)
            
            # 判断是文件还是文件夹（注意：磁盘上此时应该已经是新路径了）
            is_dir = new_path.is_dir()
            
            if is_dir:
                # ====== 文件夹重命名 ======
                logger.info(f"Folder rename detected: {old_path_str} -> {new_path_str}")
                
                # 1. 更新数据库中所有受影响的文件路径
                with session_scope() as session:
                    # 查找所有以旧路径开头的文件
                    audio_files = session.query(AudioFile).filter(
                        AudioFile.file_path.like(f"{old_path_str}{os.sep}%")
                    ).all()
                    
                    for audio_file in audio_files:
                        old_file_path = audio_file.file_path
                        new_file_path = old_file_path.replace(old_path_str, new_path_str, 1)
                        audio_file.file_path = new_file_path
                        audio_file.filename = Path(new_file_path).name
                        logger.debug(f"DB updated: {old_file_path} -> {new_file_path}")
                    
                    logger.info(f"Updated {len(audio_files)} file paths in database after folder rename")
                
                # 2. 更新内存数据结构
                # Update _audio_files list
                for i, path in enumerate(self._audio_files):
                    path_str = str(path)
                    if path_str.startswith(old_path_str + os.sep):
                        new_file_path_str = path_str.replace(old_path_str, new_path_str, 1)
                        self._audio_files[i] = Path(new_file_path_str)
                
                # Update _file_metadata keys
                old_metadata_keys = [k for k in self._file_metadata.keys() if k.startswith(old_path_str + os.sep)]
                for old_key in old_metadata_keys:
                    new_key = old_key.replace(old_path_str, new_path_str, 1)
                    self._file_metadata[new_key] = self._file_metadata.pop(old_key)
                
                # Update _file_items dictionary (normalized_path -> QTreeWidgetItem)
                old_item_keys = [k for k in self._file_items.keys() if k.startswith(os.path.normpath(old_path_str) + os.sep)]
                for old_key in old_item_keys:
                    new_key = old_key.replace(os.path.normpath(old_path_str), os.path.normpath(new_path_str), 1)
                    item = self._file_items.pop(old_key)
                    
                    # Update item data
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        old_item_path = data.get("path", "")
                        new_item_path = old_item_path.replace(old_path_str, new_path_str, 1)
                        data["path"] = new_item_path
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                        item.setText(0, Path(new_item_path).name)
                        
                        # Update tooltip with new path
                        new_metadata = self._file_metadata.get(new_item_path)
                        if new_metadata:
                            new_path_obj = Path(new_item_path)
                            orig_name = getattr(new_metadata, 'original_filename', new_path_obj.name)
                            tags = getattr(new_metadata, 'tags', [])
                            tags_str = ", ".join(tags) if tags else "未进行AI智能打标"
                            
                            duration = getattr(new_metadata, 'duration', 0)
                            duration_str = format_duration(duration) if duration else "未知"
                            
                            ext = new_path_obj.suffix.upper().lstrip('.')
                            file_size = getattr(new_metadata, 'file_size', 0)
                            size_str = format_file_size(file_size) if file_size else "未知"
                            
                            tooltip = f"""
                            <p><b>名称:</b> {new_path_obj.name}</p>
                            <p><b>源文件名:</b> {orig_name}</p>
                            <p><b>标签:</b> {tags_str}</p>
                            <p><b>时长:</b> {duration_str} | <b>格式:</b> {ext} | <b>大小:</b> {size_str}</p>
                            """
                            item.setToolTip(0, tooltip.strip())
                    
                    self._file_items[new_key] = item
                
                # Update _selected_files set
                old_selected = [f for f in self._selected_files if f.startswith(old_path_str + os.sep)]
                for old_sel in old_selected:
                    self._selected_files.discard(old_sel)
                    new_sel = old_sel.replace(old_path_str, new_path_str, 1)
                    self._selected_files.add(new_sel)
                
                # 3. 更新UI树中的文件夹节点
                norm_old_path = os.path.normpath(old_path_str)
                root = self.tree.invisibleRootItem()
                self._update_folder_node_recursive(root, norm_old_path, os.path.normpath(new_path_str))
                
                logger.info(f"Folder rename synchronized: {len(old_item_keys)} files updated")
                
            else:
                # ====== 文件重命名 ======
                logger.info(f"File rename detected: {old_path_str} -> {new_path_str}")
                
                # 1. 更新数据库
                with session_scope() as session:
                    audio_file = session.query(AudioFile).filter(AudioFile.file_path == old_path_str).first()
                    if audio_file:
                        audio_file.file_path = new_path_str
                        audio_file.filename = new_path.name
                        logger.info(f"Database synchronized: {old_path_str} -> {new_path_str}")
                
                # 2. 更新内存数据结构
                new_path_obj = Path(new_path_str)
                for i, path in enumerate(self._audio_files):
                    if str(path) == old_path_str:
                        self._audio_files[i] = new_path_obj
                        break
                
                # Update metadata mapping
                if old_path_str in self._file_metadata:
                    self._file_metadata[new_path_str] = self._file_metadata.pop(old_path_str)
                
                # Re-extract metadata to capture ORIGINAL_FILENAME tag
                try:
                    extractor = MetadataExtractor()
                    new_metadata = extractor.extract(str(new_path_obj))
                    self._file_metadata[new_path_str] = new_metadata
                    logger.debug(f"Re-extracted metadata for {new_path_obj.name}")
                except Exception as e:
                    logger.warning(f"Failed to re-extract metadata: {e}")
                
                # 3. 更新UI树 (O(1) Access using _file_items map)
                norm_old_path = os.path.normpath(old_path_str)
                norm_new_path = os.path.normpath(new_path_str)
                
                if norm_old_path in self._file_items:
                    item = self._file_items.pop(norm_old_path)
                    
                    # Update item appearance
                    item.setText(0, new_path_obj.name)
                    
                    # Update item data
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        data["path"] = new_path_str
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                    
                    # Update tooltip with new filename
                    new_metadata = self._file_metadata.get(new_path_str)
                    if new_metadata:
                        orig_name = getattr(new_metadata, 'original_filename', new_path_obj.name)
                        tags = getattr(new_metadata, 'tags', [])
                        tags_str = ", ".join(tags) if tags else "未进行AI智能打标"
                        
                        duration = getattr(new_metadata, 'duration', 0)
                        duration_str = format_duration(duration) if duration else "未知"
                        
                        ext = new_path_obj.suffix.upper().lstrip('.')
                        file_size = getattr(new_metadata, 'file_size', 0)
                        size_str = format_file_size(file_size) if file_size else "未知"
                        
                        tooltip = f"""
                        <p><b>名称:</b> {new_path_obj.name}</p>
                        <p><b>源文件名:</b> {orig_name}</p>
                        <p><b>标签:</b> {tags_str}</p>
                        <p><b>时长:</b> {duration_str} | <b>格式:</b> {ext} | <b>大小:</b> {size_str}</p>
                        """
                        item.setToolTip(0, tooltip.strip())
                        logger.debug(f"Tooltip updated for {new_path_obj.name}")
                    
                    # Update map with new key
                    self._file_items[norm_new_path] = item
                    
                    # Highlight the item
                    self.tree.scrollToItem(item)
                    item.setSelected(True)
                    
                    # Refresh FileInfoCard if visible
                    if hasattr(self, 'info_card'):
                        self.info_card.update_info(new_path_str, new_metadata)
                    
                    logger.info(f"UI Tree synchronized: {new_path_obj.name}")
                else:
                    logger.warning(f"Could not find tree item for {norm_old_path}")
                
                # Update _selected_files
                if old_path_str in self._selected_files:
                    self._selected_files.discard(old_path_str)
                    self._selected_files.add(new_path_str)
            
        except Exception as e:
            logger.error(f"Error syncing translation applied: {e}", exc_info=True)
    
    def _update_folder_node_recursive(self, parent_item: QTreeWidgetItem, old_path_norm: str, new_path_norm: str):
        """递归查找并更新文件夹节点路径"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            
            if data:
                item_path = data.get("path", "")
                item_path_norm = os.path.normpath(item_path)
                
                # Check if this is the folder we're looking for
                if item_path_norm == old_path_norm:
                    # Update folder node
                    new_path_str = item_path.replace(old_path_norm, new_path_norm, 1)
                    data["path"] = new_path_str
                    child.setData(0, Qt.ItemDataRole.UserRole, data)
                    child.setText(0, Path(new_path_str).name)
                    logger.info(f"Folder node updated: {old_path_norm} -> {new_path_norm}")
                    return True
                
                # Check if this path is a parent of the target
                if old_path_norm.startswith(item_path_norm + os.sep):
                    if self._update_folder_node_recursive(child, old_path_norm, new_path_norm):
                        return True
        
        return False
    
    def _on_clear_library(self):
        """清空音效库"""
        reply = QMessageBox.question(
            self, "确认清空", "是否确认清空所有音效数据？\n此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self._db_manager.truncate_tables()
            self._audio_files.clear()
            self._folder_structure.clear()
            self._file_items.clear()
            self._root_folders = []
            
            self._update_tree()
            NotificationHelper.success(self, "清空成功", "音效库已清空")



    def _on_play_clicked(self, file_path: str):
        """播放按钮点击"""
        logger.info(f"Play file: {file_path}")
        self.play_file.emit(file_path)
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """单击选中文件，显示详情"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "file":
            file_path = data.get("path")
            metadata = self._file_metadata.get(file_path)
            self.info_card.update_info(file_path, metadata)
            self.file_selected.emit(file_path)
        else:
            self.info_card.clear_info()
    
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """复选框状态改变"""
        if column != 0:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        
        if data.get("type") == "folder":
            self._set_children_checked(item, is_checked)
        else:
            file_path = data.get("path")
            if is_checked:
                self._selected_files.add(file_path)
            else:
                self._selected_files.discard(file_path)
        
        self._update_selected_count()
    
    def _set_children_checked(self, parent_item: QTreeWidgetItem, checked: bool):
        """递归设置子项选中状态"""
        self.tree.blockSignals(True)
        
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "file":
                file_path = data.get("path")
                if checked:
                    self._selected_files.add(file_path)
                else:
                    self._selected_files.discard(file_path)
            
            if child.childCount() > 0:
                self._set_children_checked(child, checked)
        
        self.tree.blockSignals(False)
    
    def _update_selected_count(self):
        """更新选中计数"""
        count = len(self._selected_files)
        self.selected_label.setText(f"已选择 {count} 个文件")
        self.files_checked.emit(list(self._selected_files))
        
        # Enable/Disable buttons based on selection
        # has_selection = count > 0
        # self.ai_search_btn.setEnabled(has_selection) # Removed
        # self.translate_btn.setEnabled(has_selection) # Removed
    
    def get_selected_files(self) -> List[str]:
        """获取选中的文件路径列表 - 支持虚拟全选"""
        if self._is_all_selected:
            # 全选状态：直接返回所有文件路径
            return [str(path) for path, _ in self._all_file_data]
        else:
            # 部分选中：返回实际选中的文件
            return list(self._selected_files)
    
    def _on_select_all(self, state):
        """全选/取消全选 - 优化版本，不加载所有文件"""
        checked = state == Qt.CheckState.Checked.value
        
        if checked:
            # 标记全选状态（不加载所有文件到 UI）
            self._is_all_selected = True
            total_files = len(self._all_file_data)
            self.selected_label.setText(f"已选 {total_files}")
            
            # 发送所有文件路径给 AI 模块
            all_file_paths = [str(path) for path, _ in self._all_file_data]
            self.files_checked.emit(all_file_paths)
            
            logger.info(f"All {total_files} files selected (virtual selection)")
        else:
            # 取消全选
            self._is_all_selected = False
            self._selected_files.clear()
            
            # 取消 UI 中已加载文件的选中状态
            self.tree.blockSignals(True)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self._set_children_checked(item, False)
            self.tree.blockSignals(False)
            
            self.selected_label.setText("已选 0")
            self.files_checked.emit([])
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击播放"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "file":
            file_path = data.get("path")
            logger.info(f"Play file: {file_path}")
            self.play_file.emit(file_path)
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 处理搜索框焦点"""
        if obj == self.search_edit:
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.Type.FocusIn:
                self.search_hint.setVisible(True)
            elif event.type() == QEvent.Type.FocusOut:
                if not self.search_edit.text():
                    self.search_hint.setVisible(False)
        
        return super().eventFilter(obj, event)

    def _on_search(self, *args):
        """搜索过滤 - 使用后端 SearchEngine"""
        text = self.search_edit.text().strip()
        field_idx = self.search_field.currentIndex()
        
        # 1. 如果搜索框为空，恢复默认视图（懒加载模式）
        if not text:
            if not self._lazy_load_enabled:
                self._lazy_load_enabled = True
                self._update_tree_lazy() # 重新构建并将懒加载模式打开
            return
            
        # 2. 如果有搜索内容，切换到"全量搜索结果视图"（禁用懒加载）
        self._lazy_load_enabled = False
        
        try:
            # 构建查询字符串
            query_str = text
            if field_idx == 1:  # 文件名
                query_str = f"filename:{text}"
            elif field_idx == 2:  # 格式
                query_str = f"format:{text}"
            elif field_idx == 3:  # 时长
                query_str = f"duration:{text}"
            
            # 执行搜索
            query = self._search_engine.parse_query(query_str)
            # 搜索全部数据库
            result = self._search_engine.execute_sync(query)
            matched_ids = set(result.file_ids)
            
            logger.info(f"Search '{query_str}' found {len(matched_ids)} matches")
            
            # 3. 重建树，只包含匹配项
            self.tree.clear()
            self._file_items.clear()
            
            # 重建文件夹结构
            self._build_folder_tree_structure()
            
            # 填充匹配的文件
            # 痛点：我们需要知道 ID -> FilePath 的反向映射，或者遍历 _all_file_data
            # 为提高效率，我们可以遍历 _all_file_data，因为我们有 _file_path_to_id 映射
            
            count = 0
            # 优化：仅当有匹配时才遍历
            if matched_ids:
                # 预先获取 ID 映射
                path_id_map = self._file_path_to_id
                
                # 冻结刷新
                self.tree.setUpdatesEnabled(False)
                
                for file_path, metadata in self._all_file_data:
                    path_str = str(file_path)
                    fid = path_id_map.get(path_str)
                    
                    if fid in matched_ids:
                        # 是匹配项，添加到树中
                        # 确保 file_path 是 Path 对象
                        if not isinstance(file_path, Path):
                            file_path = Path(file_path)
                            
                        # 添加到对应文件夹
                        parent_path = file_path.parent
                        parent_item = self._folder_items.get(str(parent_path))
                        
                        if parent_item:
                            self._create_file_item(parent_item, file_path)
                            # 展开该文件的父文件夹路径
                            temp = parent_item
                            while temp:
                                temp.setExpanded(True)
                                temp = temp.parent()
                            count += 1
                
                self.tree.setUpdatesEnabled(True)
            
            # 更新统计
            self.stats_label.setText(f"搜索结果: {count} 个")
            
            # 隐藏没有子项的文件夹
            self._hide_empty_folders()

        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            self.stats_label.setText("搜索出错")

    def _hide_empty_folders(self):
        """隐藏空文件夹 (用于搜索结果视图)"""
        if not self._folder_items:
            return
            
        def check_vis(item):
            has_visible_child = False
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                
                if data and data.get("type") == "file":
                    # 文件肯定可见（因为我们只添加了匹配的）
                    has_visible_child = True
                else:
                    # 文件夹，递归检查
                    if check_vis(child):
                        has_visible_child = True
            
            item.setHidden(not has_visible_child)
            return has_visible_child

        # 从根节点开始检查
        for i in range(self.tree.topLevelItemCount()):
            check_vis(self.tree.topLevelItem(i))

    def _show_all_items(self):
        # Deprecated by new logic
        pass

    def _recursive_set_hidden(self, item, hidden):
        # Deprecated
        pass

    def _filter_tree_by_ids(self, matched_ids):
        # Deprecated
        pass
    
    def _on_ai_search_clicked(self):
        """跳转到 AI 检索页面"""
        files = list(self._selected_files)
        if not files:
            NotificationHelper.warning(
                self,
                "提示",
                "请先勾选要AI检索的文件"
            )
            return
            
        logger.info(f"Requesting AI Search for {len(files)} files")
        self.request_ai_search.emit(files)
        NotificationHelper.info(
            self,
            "AI检索",
            f"已选择 {len(self._selected_files)} 个文件，请切换到AI检索页面"
        )
    
    def _on_ai_translate(self):
        """AI翻译选中的文件"""
        if not self._selected_files:
            NotificationHelper.warning(
                self,
                "提示",
                "请先勾选要翻译的文件"
            )
            return
        
        self.files_checked.emit(list(self._selected_files))
        NotificationHelper.info(
            self,
            "AI翻译",
            f"已选择 {len(self._selected_files)} 个文件，请切换到AI翻译页面"
        )
    
    def get_selected_files(self) -> list:
        """获取选中的文件列表"""
        return list(self._selected_files)
    
    def get_all_files(self) -> list:
        """获取所有文件列表"""
        return [str(f) for f in self._audio_files]
    
    def get_file_metadata(self, file_path: str):
        """获取文件元数据"""
        return self._file_metadata.get(file_path)

    def _on_clear_library(self):
        """清空音效库"""
        from qfluentwidgets import MessageDialog
        dialog = MessageDialog(
            "清空音效库",
            "确定要清空所有音效库数据吗？\n此操作将删除数据库中的所有记录，但不会删除硬盘上的文件。",
            self
        )
        dialog.yesButton.setText("确定清空")
        dialog.cancelButton.setText("取消")
        
        if dialog.exec():
            try:
                from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath
                with session_scope() as session:
                    # Truncate tables
                    session.query(AudioFile).delete()
                    session.query(LibraryPath).delete()
                    session.commit()
                
                # Clear memory
                self._audio_files = []
                self._library_roots = []
                self._file_metadata = {}
                self._folder_structure.clear()
                self._selected_files.clear()
                
                # Clear UI
                self.tree.clear()
                self.stats_label.setText("")
                self.selected_label.setText("已选 0")
                self.info_card.clear_info()
                self.stack.setCurrentWidget(self.empty_state)
                
                # Emit signals
                self.files_checked.emit([]) # Clear selection in other pages
                self.library_cleared.emit() # Notify global clear
                
                NotificationHelper.success(self, "已清空", "音效库已重置")
                logger.info("Library cleared by user")
                
            except Exception as e:
                logger.error(f"Failed to clear library: {e}")
                NotificationHelper.error(self, "错误", f"清空失败: {e}")

    # ==================== 懒加载相关方法 ====================
    
    def _update_tree_lazy(self):
        """懒加载模式更新文件树 - 改进版：先构建文件夹结构，再懒加载文件"""
        self.tree.clear()
        self._file_items.clear()
        self._loaded_count = 0
        
        # 重置全选状态
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(False)
        self.select_all_cb.blockSignals(False)
        self._selected_files.clear()
        self._update_selected_count()
        
        if not self._all_file_data:
            self.stack.setCurrentWidget(self.empty_state)
            return
        
        # 第一步：构建文件夹结构（不添加文件）
        self._build_folder_tree_structure()
        
        # 改进：如果文件总数不多（< 500），直接全部加载，避免用户困惑
        total_files = len(self._all_file_data)
        if total_files < 500:
            logger.info(f"Total files ({total_files}) < 500, loading all at once")
            self._lazy_load_enabled = False
            # 加载所有文件
            for file_path, metadata in self._all_file_data:
                if not isinstance(file_path, Path):
                    file_path = Path(file_path)
                self._create_file_item_lazy(file_path, metadata)
            self._loaded_count = total_files
            self._update_stats()
        else:
            # 第二步：懒加载文件（大量文件时）
            self._lazy_load_enabled = True
            self._load_next_batch()
    
    def _build_folder_tree_structure(self):
        """构建文件夹树结构（不包含文件）"""
        # 按根目录分组文件
        files_by_root = defaultdict(list)
        
        logger.info(f"Building folder tree for {len(self._all_file_data)} files, {len(self._library_roots)} roots")
        
        for file_path, metadata in self._all_file_data:
            # 找到文件所属的根目录
            path_obj = Path(file_path) if not isinstance(file_path, Path) else file_path
            root_found = None
            
            for root in self._library_roots:
                try:
                    path_obj.relative_to(root)
                    root_found = root
                    break
                except ValueError:
                    continue
            
            if root_found:
                files_by_root[root_found].append((path_obj, metadata))
            else:
                logger.warning(f"File {path_obj} does not belong to any root!")
        
        # 为每个根目录创建文件夹树
        self._folder_items = {}  # {folder_path_str: QTreeWidgetItem}
        
        for root_path in self._library_roots:
            files = files_by_root.get(root_path, [])
            
            if not files:
                # 即使没有文件，也创建根节点
                logger.warning(f"No files found for root: {root_path}")
                root_item = QTreeWidgetItem([root_path.name, "", ""])
                root_item.setIcon(0, FluentIcon.FOLDER.icon())
                root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
                root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
                root_item.setCheckState(0, Qt.CheckState.Unchecked)
                self.tree.addTopLevelItem(root_item)
                self._folder_items[str(root_path)] = root_item
                root_item.setExpanded(True)
                continue
            
            # 创建根节点
            root_item = QTreeWidgetItem([root_path.name, "", ""])
            root_item.setIcon(0, FluentIcon.FOLDER.icon())
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
            root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
            root_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(root_item)
            self._folder_items[str(root_path)] = root_item
            
            # 收集所有子文件夹
            folders = set()
            for file_path, _ in files:
                parent = file_path.parent
                while parent != root_path:
                    folders.add(parent)
                    parent = parent.parent
                    if parent == parent.parent:
                        break
            
            # 按层级排序文件夹
            sorted_folders = sorted(folders, key=lambda p: (len(p.parts), str(p)))
            
            # 创建文件夹节点
            for folder_path in sorted_folders:
                parent_path = folder_path.parent
                parent_item = self._folder_items.get(str(parent_path), root_item)
                
                folder_item = QTreeWidgetItem([folder_path.name, "", ""])
                folder_item.setIcon(0, FluentIcon.FOLDER.icon())
                folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(folder_path)})
                folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                
                if parent_item:
                    parent_item.addChild(folder_item)
                    self._folder_items[str(folder_path)] = folder_item
                else:
                    logger.warning(f"Parent item not found for folder: {folder_path}")
            
            root_item.setExpanded(True)
    
    def _load_next_batch(self):
        """加载下一批文件"""
        if self._is_loading or not self._lazy_load_enabled:
            return
        
        self._is_loading = True
        
        start = self._loaded_count
        end = min(start + self._batch_size, len(self._all_file_data))
        
        if start >= end:
            self._is_loading = False
            return
        
        logger.info(f"Loading batch: {start}-{end} of {len(self._all_file_data)}")
        
        # 加载这批文件
        for i in range(start, end):
            file_path, metadata = self._all_file_data[i]
            if not isinstance(file_path, Path):
                file_path = Path(file_path)
            self._create_file_item_lazy(file_path, metadata)
        
        self._loaded_count = end
        self._is_loading = False
        
        logger.info(f"Loaded {self._loaded_count}/{len(self._all_file_data)} files")
        self._update_stats()
    
    def _on_scroll(self, value):
        """滚动事件 - 触发懒加载"""
        if not self._lazy_load_enabled:
            return
        
        scrollbar = self.tree.verticalScrollBar()
        
        # 滚动到底部 80% 时加载下一批
        if scrollbar.maximum() > 0 and value >= scrollbar.maximum() * 0.8:
            if self._loaded_count < len(self._all_file_data):
                self._load_next_batch()
    
    def _create_file_item_lazy(self, file_path: Path, metadata):
        """创建文件项（懒加载版，添加到对应文件夹）"""
        # 找到父文件夹节点
        parent_path = file_path.parent
        parent_path_str = str(parent_path)
        parent_item = self._folder_items.get(parent_path_str)
        
        if not parent_item:
            # 如果找不到父文件夹，记录警告并跳过
            logger.warning(f"Parent folder not found for {file_path.name}, parent: {parent_path_str}")
            return
        
        # 创建文件项
        self._create_file_item(parent_item, file_path)
    
    def _update_stats(self):
        """更新统计信息"""
        total = len(self._all_file_data) if self._all_file_data else len(self._audio_files)
        loaded = self._loaded_count if self._lazy_load_enabled else total
        
        if self._lazy_load_enabled and loaded < total:
            self.stats_label.setText(f"已加载 {loaded}/{total} 个音效")
        else:
            self.stats_label.setText(f"共 {total} 个音效")
    
    # ==================== 标签批量更新相关方法 ====================
    
    def _on_tags_batch_updated(self, batch_updates: list):
        """
        批量更新文件标签显示
        
        参数：
            batch_updates: [{'file_path': str, 'tags': list}, ...]
        """
        for update in batch_updates:
            file_path = update['file_path']
            tags = update['tags']
            
            # 在树中查找对应的 item
            if file_path in self._file_items:
                item = self._file_items[file_path]
                
                # 更新元数据
                if file_path in self._file_metadata:
                    metadata = self._file_metadata[file_path]
                    if hasattr(metadata, 'tags'):
                        metadata.tags = tags
                
                # 更新 tooltip（显示标签）
                tags_text = ", ".join(tags) if tags else "无标签"
                current_tooltip = item.toolTip(0) or file_path
                # 更新 tooltip，添加标签信息
                new_tooltip = f"{current_tooltip}\n标签: {tags_text}"
                item.setToolTip(0, new_tooltip)
                
                logger.debug(f"Updated tags for {Path(file_path).name}: {tags}")
        
        logger.info(f"Batch updated {len(batch_updates)} files' tags")
