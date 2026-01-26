"""
AI翻译页面 - 完整功能版本
支持：从音效库选择文件、多AI模型、术语库翻译、应用翻译结果
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QTreeWidgetItem
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
from transcriptionist_v3.ui.utils.workers import TranslateWorker, cleanup_thread
from transcriptionist_v3.ui.utils.hierarchical_translate_worker import HierarchicalTranslateWorker
from transcriptionist_v3.application.naming_manager.glossary import GlossaryManager
from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
from transcriptionist_v3.application.naming_manager.templates import TemplateManager, NamingTemplate
from transcriptionist_v3.application.library_manager.renaming_service import RenamingService

logger = logging.getLogger(__name__)


class AITranslatePage(QWidget):
    """AI翻译页面 - 完整功能"""
    
    translation_applied = Signal(str, str)  # 原路径, 新路径
    request_play = Signal(str)  # 请求播放文件 (绝对路径)
    request_stop_player = Signal()  # 请求停止播放以释放文件锁
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiTranslatePage")
        
        self._selected_files = []
        self._translation_results = {}  # 原路径 -> 翻译结果
        self._glossary_manager = GlossaryManager.instance()
        self._cleaning_manager = CleaningManager.instance()
        
        # 使用 runtime_config 获取数据目录初始化 TemplateManager
        from pathlib import Path
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        data_dir = get_data_dir()
        self._template_manager = TemplateManager.instance(str(data_dir))
        
        # QThread worker for translation (architecture refactoring)
        self._translate_thread: Optional[QThread] = None
        self._translate_worker: Optional[TranslateWorker] = None
        
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

    
    def set_selected_files(self, files: list):
        """设置选中的文件列表（从音效库传入）"""
        self._selected_files = files
        self.file_count_label.setText(f"已选择 {len(files)} 个文件")
        logger.info(f"AI Translate: received {len(files)} files")
    
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
        if not self._selected_files:
            NotificationHelper.warning(
                self,
                "提示",
                "请先选择要翻译的文件"
            )
            return

        from transcriptionist_v3.core.config import AppConfig
        api_key = AppConfig.get("ai.api_key", "").strip()
        if not api_key:
             NotificationHelper.error(
                self,
                "配置缺失",
                "请在「设置 -> AI 配置」中配置 API 密钥"
            )
             return
    
        # 清空结果树
        self.result_tree.clear()
        self._translation_results.clear()
        
        # 显示进度展示区域
        self.progress_widget.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在连接AI引擎...")
        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("正在翻译...")
        
        # 获取配置
        from transcriptionist_v3.core.config import AppConfig
        # api_key already retrieved above
        model_index = AppConfig.get("ai.model_index", 0)
        
        # 模型配置映射 (精简版)
        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        }
        model_config = model_configs.get(model_index, model_configs[0])
        
        # 获取源语言和目标语言
        source_lang = self.source_combo.currentText()
        target_lang = self.target_combo.currentText()
        
        # 使用 QThread + Worker（层级化翻译已选为默认）
        self._translate_thread = QThread()
        
        logger.info("Using HierarchicalTranslateWorker")
        # HierarchicalTranslateWorker already imported at top
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
        
        self.progress_widget.hide()
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")
        self.apply_all_btn.setEnabled(True)
        
        file_count = sum(1 for r in results if getattr(r, 'item_type', 'file') == 'file')
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
        """更新翻译结果UI（主线程）"""
        self.result_tree.clear()
        self._translation_results.clear()
        
        logger.info(f"UI updating with {len(items)} hierarchical results")
        
        from transcriptionist_v3.ui.utils.translation_items import TranslationItem
        from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
        from collections import defaultdict
        
        pattern = self._template_manager.get_active_pattern()
        template = NamingTemplate("preview", "Preview", pattern)
        
        # 建立分类映射
        nodes = {} # path -> QTreeWidgetItem
        
        # 按层级排序，确保父目录先添加
        sorted_items = sorted(items, key=lambda x: x.level)
        
        # 按父文件夹分组计算索引（每个文件夹内独立从1开始）
        folder_file_index = defaultdict(int)
        
        for item in sorted_items:
            # 获取译名（移除后缀用于预览生成）
            translated_text = item.translated
            item_path = Path(item.path)
            
            if item.item_type == 'file' and translated_text.lower().endswith(item_path.suffix.lower()):
                pure_translated = translated_text[:-len(item_path.suffix)]
            else:
                pure_translated = translated_text

            # 生成预览名
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
                    index=local_index,  # 使用文件夹内独立索引
                    translated=pure_translated
                )
                preview_name = template.format(context)
                if not preview_name.endswith(item_path.suffix):
                    preview_name += item_path.suffix
                icon = FluentIcon.MUSIC
            else:
                # 文件夹预览：仅使用纯译名（不加原名前缀）
                if pure_translated and pure_translated != item.name:
                    preview_name = pure_translated
                else:
                    preview_name = item.name
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

        # 确定新文件名
        if item.item_type == 'file':
            # 直接使用预览列的名称 (所见即所得，且避免了index重新计算错误)
            new_name = tree_item.text(1)
            
            # 安全检查：如果预览名为空（异常情况），回退到原名
            if not new_name:
                logger.warning(f"Preview name is empty for {old_path}, fallback to original name")
                new_name = item.name
        else:
            # 文件夹重命名：直接使用译名 (Animals -> 动物类)
            # 注意：文件夹的预览列显示的是 "Original_Translated"，所以不能直接用预览列
            if item.translated and item.translated != item.name:
                new_name = item.translated
            else:
                new_name = item.name

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

    def _update_child_paths(self, parent_item: QTreeWidgetItem, old_parent_path: str, new_parent_path: str):
        """递归更新所有子节点的路径"""
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
        """应用所有翻译结果 (自底向上策略，先文件后文件夹)"""
        self.request_stop_player.emit()
        
        all_tree_items = self._get_all_tree_items()
        if not all_tree_items: return
        
        # 按照路径深度倒序排序 (确保自底向上: 最深的文件先处理，最外层的目录最后处理)
        # 使用路径中的分隔符数量作为深度的可靠指标
        import os
        sorted_tree_items = sorted(
            all_tree_items, 
            key=lambda x: str(x.data(0, Qt.ItemDataRole.UserRole).path).count(os.sep) if x.data(0, Qt.ItemDataRole.UserRole) else 0,
            reverse=True
        )
        
        success_count = 0
        total_count = 0
        failed_items = []
        
        for tree_item in sorted_tree_items:
            if tree_item.text(2) == "待应用":
                total_count += 1
                self._on_apply_single(tree_item)
                if tree_item.text(2) == "已应用":
                    success_count += 1
                else:
                    # 记录失败的项目
                    item = tree_item.data(0, Qt.ItemDataRole.UserRole)
                    if item:
                        failed_items.append(item.name)
        
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

    def _on_undo_all(self):
        """撤销所有已应用的重命名（自顶向下策略，带重试机制）"""
        if not self._undo_stack:
            logger.info("Undo stack is empty")
            return
        
        # 停止播放器以释放文件锁
        self.request_stop_player.emit()
        
        import time
        import os
        
        logger.info(f"Starting undo for {len(self._undo_stack)} operations")
        
        # 按路径深度排序（浅到深，确保父文件夹先撤销）
        undo_operations = list(self._undo_stack)
        sorted_operations = sorted(
            undo_operations,
            key=lambda x: x[0].count(os.sep)  # 使用原路径的深度
        )
        
        success_count = 0
        failed_operations = []
        
        for old_path_str, new_path_str in sorted_operations:
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
                    logger.info(f"Undo success: {new_path.name} -> {old_path.name}")
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
        
        # 清空撤销栈（只保留失败的操作）
        self._undo_stack.clear()
        if failed_operations:
            # 将失败的操作放回栈中，以便用户稍后重试
            self._undo_stack.extend([(old, new) for old, new, _ in failed_operations])
            self.undo_btn.setEnabled(True)
        else:
            self.undo_btn.setEnabled(False)
        
        self._refresh_table_status_after_undo()
        
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
