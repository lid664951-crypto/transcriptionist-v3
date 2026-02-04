"""
AudioFilesPanel - 音效文件显示面板（虚拟列表版本）
专门用于显示选中文件夹内的音效文件列表，使用 Qt Model/View 提升大数据量性能
"""

import logging
import subprocess
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QAbstractItemView, QHeaderView
)
from PySide6.QtGui import QColor

from qfluentwidgets import (
    SubtitleLabel, CaptionLabel, TransparentToolButton,
    FluentIcon, SearchLineEdit, RoundMenu, Action, PushButton
)

from transcriptionist_v3.core.utils import format_duration, format_file_size
from transcriptionist_v3.ui.utils.notifications import NotificationHelper

logger = logging.getLogger(__name__)


class _AudioFilesTableModel(QAbstractTableModel):
    """
    只保存数据，不创建 QTreeWidgetItem，依赖视图的虚拟化能力。
    对外保持与旧版 AudioFilesPanel 相同的字段含义。
    """

    HEADERS = ["音效名", "原音效名", "标签", "时长", "大小", "格式"]

    def __init__(self, provider=None, indices: List[int] | None = None, parent=None):
        """
        Args:
            provider: 一个可调用对象，接受全局索引 int，返回文件信息 dict。
            indices: 当前视图中要显示的全局索引列表。
        """
        super().__init__(parent)
        self._provider = provider
        self._indices: List[int] = indices or []

    # ---- 基础行列 ----
    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._indices)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        return len(self.HEADERS)

    # ---- 数据 ----
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._indices):
            return None

        # 懒加载：按需从 provider 获取当前行的文件信息
        if not self._provider:
            return None
        global_index = self._indices[row]
        file_info = self._provider(global_index)
        if not isinstance(file_info, dict):
            return None

        # Display text
        if role == Qt.ItemDataRole.DisplayRole:
            filename = file_info.get("filename", Path(file_info["file_path"]).name)
            translated_name = file_info.get("translated_name", "")
            original_name = file_info.get("original_filename", filename)
            tags = file_info.get("tags", [])
            duration = file_info.get("duration", 0)
            file_size = file_info.get("file_size", 0)
            file_format = file_info.get("format", "")

            if col == 0:
                # 音效名（翻译名优先）
                return translated_name or filename
            if col == 1:
                # 原音效名（只有翻译后才显示）
                return original_name if translated_name else "-"
            if col == 2:
                # 标签
                if not tags:
                    return "未打标"
                tags_text = ", ".join(tags[:3])
                if len(tags) > 3:
                    tags_text += f" +{len(tags) - 3}"
                return tags_text
            if col == 3:
                return format_duration(duration) if duration else "-"
            if col == 4:
                return format_file_size(file_size) if file_size else "-"
            if col == 5:
                return file_format.upper() if file_format else "-"

        # 前景色
        if role == Qt.ItemDataRole.ForegroundRole:
            translated_name = file_info.get("translated_name", "")
            tags = file_info.get("tags", [])
            if col == 1 and translated_name:
                # 原音效名灰色
                return QColor(150, 150, 150)
            if col == 2:
                return QColor(100, 200, 255) if tags else QColor(120, 120, 120)

        # Tooltip：在第一列展示完整路径
        if role == Qt.ItemDataRole.ToolTipRole and col == 0:
            return file_info.get("file_path", "")

        # 自定义角色：整行的原始字典
        if role == Qt.ItemDataRole.UserRole:
            return file_info

        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    # ---- 外部接口 ----
    def set_provider(self, provider):
        """设置数据提供者"""
        self._provider = provider

    def set_indices(self, indices: List[int]):
        """替换全部索引列表（懒加载数据）"""
        self.beginResetModel()
        self._indices = indices or []
        self.endResetModel()

    def append_indices(self, indices: List[int]):
        """增量追加索引，用于「加载更多」避免全表重置。"""
        if not indices:
            return
        start = len(self._indices)
        self._indices.extend(indices)
        self.beginInsertRows(QModelIndex(), start, len(self._indices) - 1)
        self.endInsertRows()

    def files(self) -> List[dict]:
        """兼容旧接口：返回当前所有行对应的文件信息列表（会调用 provider）"""
        if not self._provider:
            return []
        result: List[dict] = []
        for idx in self._indices:
            info = self._provider(idx)
            if isinstance(info, dict):
                result.append(info)
        return result

    def file_at(self, row: int) -> dict | None:
        if not self._provider:
            return None
        if 0 <= row < len(self._indices):
            info = self._provider(self._indices[row])
            if isinstance(info, dict):
                return info
        return None


class AudioFilesPanel(QWidget):
    """音效文件显示面板（虚拟列表实现，接口保持兼容）"""

    # 单次最多显示行数，超过则「加载更多」分批显示，避免几十万行一次性 set_indices 卡死
    DISPLAY_CAP = 10000

    # 信号定义
    files_selected = Signal(list)  # 文件选择变化时触发（List[dict]）
    request_play = Signal(str)  # 请求播放文件
    request_remove = Signal(list)  # 请求移除文件（List[str] file_path）
    request_show_in_folder = Signal(str)  # 请求在文件夹中显示

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_folder: str | None = None
        # 使用全局索引进行懒加载
        self._all_indices: List[int] = []
        self._filtered_indices: List[int] = []
        self._selected_files: List[dict] = []
        self._data_provider = None  # type: ignore
        # 显示上限：当前已传给模型的索引、下一批起始位置、是否还有更多
        self._displayed_offset: int = 0
        self._has_more: bool = False

        self._model = _AudioFilesTableModel(provider=None, indices=[])

        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 标题栏
        header = QHBoxLayout()
        self.title_label = SubtitleLabel("音效列表")
        self.title_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self.title_label)

        self.count_label = CaptionLabel("共 0 个文件")
        self.count_label.setStyleSheet("color: #888;")
        header.addWidget(self.count_label)
        header.addStretch()

        layout.addLayout(header)

        # 工具栏
        toolbar = QHBoxLayout()

        # 搜索框：仅对当前列表中的文件名进行过滤
        self.search_box = SearchLineEdit()
        self.search_box.setPlaceholderText("在当前列表中搜索文件名")
        self.search_box.setFixedWidth(200)
        self.search_box.textChanged.connect(self._on_search_changed)
        # 初始无文件时禁用，避免“空转”造成困惑
        self.search_box.setEnabled(False)
        toolbar.addWidget(self.search_box)

        toolbar.addStretch()

        # 加载更多（仅当当前显示数 < 总数时显示，避免几十万行一次性卡死）
        self.load_more_btn = PushButton(FluentIcon.ADD, "加载更多")
        self.load_more_btn.setToolTip("加载下一批文件到列表")
        self.load_more_btn.clicked.connect(self._on_load_more)
        self.load_more_btn.setVisible(False)
        toolbar.addWidget(self.load_more_btn)

        # 刷新按钮
        self.refresh_btn = TransparentToolButton(FluentIcon.SYNC)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self.refresh_btn)

        layout.addLayout(toolbar)

        # 文件列表视图（使用 QTreeView + 自定义模型）
        self.file_view = QTreeView()
        self.file_view.setModel(self._model)
        self.file_view.setRootIsDecorated(False)
        self.file_view.setAlternatingRowColors(True)
        self.file_view.setSortingEnabled(True)
        self.file_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.file_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # 调整列宽与伸展策略：
        # - 第 0 列（音效名）自适应填充剩余空间
        # - 其他列使用固定宽度，避免整体列表偏向左侧
        header = self.file_view.header()
        header.setStretchLastSection(False)

        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)

        header.resizeSection(0, 350)
        header.resizeSection(1, 250)
        header.resizeSection(2, 200)
        header.resizeSection(3, 80)
        header.resizeSection(4, 80)
        header.resizeSection(5, 60)

        # 样式（沿用原来的 QTreeWidget QSS，控件名改为 QTreeView）
        self.file_view.setStyleSheet("""
            QTreeView {
                background-color: #1e1e1e;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                outline: none;
            }
            QTreeView::item {
                padding: 8px 4px;
                border: none;
                min-height: 32px;
            }
            QTreeView::item:hover {
                background-color: #2a2a2a;
            }
            QTreeView::item:selected {
                background-color: #3399ff;
                color: white;
            }
            QHeaderView::section {
                background-color: #252525;
                color: #aaa;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #1a1a1a;
                font-weight: bold;
            }

            /* Fluent 风格滚动条 */
            QScrollBar:vertical {
                background: transparent;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.25);
            }
            QScrollBar::handle:vertical:pressed {
                background: rgba(255, 255, 255, 0.35);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }

            /* 水平滚动条 */
            QScrollBar:horizontal {
                background: transparent;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: rgba(255, 255, 255, 0.25);
            }
            QScrollBar::handle:horizontal:pressed {
                background: rgba(255, 255, 255, 0.35);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)

        # 右键菜单
        self.file_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_view.customContextMenuRequested.connect(self._show_context_menu)

        # 信号连接
        self.file_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.file_view.doubleClicked.connect(self._on_item_double_clicked)
        self.file_view.verticalScrollBar().valueChanged.connect(self._on_scroll_load_more)

        layout.addWidget(self.file_view)

        # 底部状态栏
        status_bar = QHBoxLayout()
        self.selection_label = CaptionLabel("未选择文件")
        self.selection_label.setStyleSheet("color: #888;")
        status_bar.addWidget(self.selection_label)
        status_bar.addStretch()

        layout.addLayout(status_bar)

    def _on_scroll_load_more(self, value: int):
        """滚动到底部附近时自动加载更多，模拟分页滚动体验。"""
        if not self._has_more:
            return
        bar = self.file_view.verticalScrollBar()
        if bar.maximum() <= 0:
            return
        if value >= int(bar.maximum() * 0.85):
            self._on_load_more()

    # ========= 对外 API（保持兼容） =========
    def set_data_provider(self, provider):
        """
        设置数据提供者。
        provider 接受一个全局索引 (int)，返回包含 file_path, filename 等字段的 dict。
        """
        self._data_provider = provider
        self._model.set_provider(provider)

    def _apply_display_cap(self):
        """根据 _filtered_indices 应用显示上限：只传前 DISPLAY_CAP 条给模型，避免几十万行卡死。"""
        total = len(self._filtered_indices)
        if total <= self.DISPLAY_CAP:
            displayed = list(self._filtered_indices)
            self._displayed_offset = total
            self._has_more = False
        else:
            displayed = list(self._filtered_indices[: self.DISPLAY_CAP])
            self._displayed_offset = len(displayed)
            self._has_more = True
        self._model.set_indices(displayed)
        self._update_count_and_load_more_btn()

    def _update_count_and_load_more_btn(self):
        """更新「共 N 个文件」/「已显示 X / N」文案及「加载更多」按钮可见性。"""
        total = len(self._filtered_indices)
        if self._has_more:
            self.count_label.setText(
                f"已显示 {self._displayed_offset} / {total}，点击「加载更多」或使用搜索"
            )
            self.load_more_btn.setVisible(True)
        else:
            self.count_label.setText(f"共 {total} 个文件")
            self.load_more_btn.setVisible(False)

    def _on_load_more(self):
        """加载下一批到列表（增量 append，避免全表重置）。"""
        total = len(self._filtered_indices)
        if self._displayed_offset >= total:
            self._has_more = False
            self._update_count_and_load_more_btn()
            return
        batch = self._filtered_indices[
            self._displayed_offset : self._displayed_offset + self.DISPLAY_CAP
        ]
        self._model.append_indices(batch)
        self._displayed_offset += len(batch)
        self._has_more = self._displayed_offset < total
        self._update_count_and_load_more_btn()

    def set_folder_indices(self, folder_path: str, indices: List[int]):
        """
        设置当前文件夹及其文件索引列表（懒加载版本）。
        若数量超过 DISPLAY_CAP，只先显示前 DISPLAY_CAP 条，其余通过「加载更多」追加。
        """
        self._current_folder = folder_path
        self._all_indices = indices or []
        self._filtered_indices = list(self._all_indices)
        self._selected_files = []

        folder_name = Path(folder_path).name if folder_path else "未选择文件夹"
        self.title_label.setText(f"音效列表 - {folder_name}")

        self._apply_display_cap()

        self.file_view.selectionModel().clearSelection()
        self.selection_label.setText("未选择文件")
        self.search_box.setEnabled(bool(self._all_indices))

        logger.info(
            f"AudioFilesPanel: Loaded {len(self._filtered_indices)} files from {folder_path}"
        )

    def clear(self):
        """清空文件列表"""
        self._current_folder = None
        self._all_indices = []
        self._filtered_indices = []
        self._selected_files = []
        self._displayed_offset = 0
        self._has_more = False

        self._model.set_indices([])
        self.title_label.setText("音效列表")
        self.count_label.setText("共 0 个文件")
        self.selection_label.setText("未选择文件")
        self.load_more_btn.setVisible(False)
        self.search_box.clear()
        self.search_box.setEnabled(False)

    def get_selected_files(self) -> List[dict]:
        """获取当前选中的文件列表（保持旧接口）"""
        return list(self._selected_files)

    # ========= 内部逻辑 =========
    def _on_search_changed(self, text: str):
        """搜索框文本变化；结果仍受显示上限限制，超出部分可「加载更多」。"""
        text = text.strip().lower()

        if not text:
            self._filtered_indices = list(self._all_indices)
        else:
            filtered: List[int] = []
            if self._data_provider:
                for idx in self._all_indices:
                    info = self._data_provider(idx)
                    if not isinstance(info, dict):
                        continue
                    name = Path(info.get("file_path", "")).name.lower()
                    if text in name:
                        filtered.append(idx)
            self._filtered_indices = filtered

        self._apply_display_cap()
        self.file_view.selectionModel().clearSelection()
        self._selected_files = []
        self.selection_label.setText("未选择文件")
        self.files_selected.emit([])

    def _on_refresh(self):
        """刷新列表：重新应用当前搜索条件"""
        self._on_search_changed(self.search_box.text())
        NotificationHelper.success(self, "已刷新", "文件列表已更新")

    def _indexes_to_files(self, indexes) -> List[dict]:
        """将选中的 QModelIndex 列转为文件 dict 列表"""
        rows = sorted({idx.row() for idx in indexes})
        result: List[dict] = []
        for row in rows:
            file_info = self._model.file_at(row)
            if file_info:
                result.append(file_info)
        return result

    def _on_selection_changed(self, selected, deselected):
        """选择变化"""
        indexes = self.file_view.selectionModel().selectedRows()
        self._selected_files = self._indexes_to_files(indexes)

        count = len(self._selected_files)
        if count == 0:
            self.selection_label.setText("未选择文件")
        else:
            self.selection_label.setText(f"已选择 {count} 个文件")

        self.files_selected.emit(list(self._selected_files))

    def _on_item_double_clicked(self, index: QModelIndex):
        """双击播放"""
        file_info = self._model.data(index, Qt.ItemDataRole.UserRole)
        if isinstance(file_info, dict):
            file_path = file_info.get("file_path")
            if file_path:
                logger.info(f"AudioFilesPanel: Request play {file_path}")
                self.request_play.emit(file_path)

    def _show_context_menu(self, position):
        """显示右键菜单"""
        indexes = self.file_view.selectionModel().selectedRows()
        if not indexes:
            return

        # 使用 qfluentwidgets 的 RoundMenu，和库板块一样的样式
        menu = RoundMenu(parent=self.file_view)

        # 播放
        play_action = Action(FluentIcon.PLAY, "播放")
        play_action.triggered.connect(self._on_play_selected)
        menu.addAction(play_action)

        menu.addSeparator()

        # 在文件夹中显示
        show_in_folder_action = Action(FluentIcon.FOLDER, "在文件夹中显示")
        show_in_folder_action.triggered.connect(self._on_show_in_folder)
        menu.addAction(show_in_folder_action)

        menu.addSeparator()

        # 从库中移除
        remove_action = Action(FluentIcon.DELETE, "从库中移除")
        remove_action.triggered.connect(self._on_remove_selected)
        menu.addAction(remove_action)

        # 在鼠标位置显示菜单
        menu.exec(self.file_view.viewport().mapToGlobal(position))

    def _on_play_selected(self):
        """播放选中的第一个文件"""
        if self._selected_files:
            file_path = self._selected_files[0].get("file_path")
            if file_path:
                logger.info(f"AudioFilesPanel: Play from context menu {file_path}")
                self.request_play.emit(file_path)

    def _on_show_in_folder(self):
        """在文件夹中显示选中文件"""
        if not self._selected_files:
            return

        import os
        import subprocess

        file_path = self._selected_files[0].get("file_path")
        if not file_path:
            return

        if os.path.exists(file_path):
            # Windows 用 explorer /select
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", file_path])
            # macOS 用 open -R
            elif hasattr(os, "uname") and os.uname().sysname == "Darwin":
                subprocess.run(["open", "-R", file_path])
            # Linux 用 xdg-open 打开父目录
            else:
                subprocess.run(["xdg-open", str(Path(file_path).parent)])

            logger.info(f"AudioFilesPanel: Show in folder {file_path}")
        else:
            NotificationHelper.warning(self, "文件不存在", "文件已被移动或删除")

    def _on_remove_selected(self):
        """从库中移除选中文件"""
        if not self._selected_files:
            return

        file_paths = [f.get("file_path") for f in self._selected_files if f.get("file_path")]
        if not file_paths:
            return

        logger.info(f"AudioFilesPanel: Request remove {len(file_paths)} files")
        self.request_remove.emit(file_paths)
