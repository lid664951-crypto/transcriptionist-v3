
import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QApplication,
    QStackedWidget, QScrollArea, QSizePolicy, QFrame
)
from PySide6.QtGui import QFont, QAction

from qfluentwidgets import (
    TreeWidget, FluentIcon, SubtitleLabel, CaptionLabel,
    RoundMenu, Action, IconWidget, TransparentToolButton,
    CheckBox, PushButton, MessageBox, CardWidget, ScrollArea
)
from transcriptionist_v3.ui.utils.flow_layout import FlowLayout

from sqlalchemy import func
from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag
from transcriptionist_v3.ui.utils.notifications import NotificationHelper

logger = logging.getLogger(__name__)

# 标签解释字典 - 为专业术语提供通俗解释
TAG_EXPLANATIONS = {
    # 专业乐器
    "特雷门琴": "一种不用接触就能演奏的电子乐器，常用于科幻/恐怖片配乐",
    "theremin": "Theremin - 特雷门琴，电子乐器",
    
    # 音效类型
    "拟音": "Foley - 为影片后期添加的各种生活音效，如脚步声、衣服摩擦声等",
    "foley": "Foley - 拟音，影视后期制作中的生活音效",
    "物之声": "建议改为'拟音'或'物体音'",
    
    # 环境音
    "环境音": "Ambience - 场景的背景声音，营造氛围",
    "氛围": "建议改为'环境音'",
    "房间音": "Room Tone - 录音现场的环境底噪",
    
    # 撞击音
    "撞击": "Impact - 物体碰撞的声音",
    "打击": "Hit - 敲击、打击的声音",
    "闷响": "Thud - 沉闷的撞击声",
    
    # 嗖声
    "嗖声": "Whoosh - 快速移动产生的风声，常用于转场",
    "扫频": "Sweep - 频率扫过的声音，常用于转场",
    
    # 界面音
    "界面音": "UI Sound - 软件、游戏中的按钮、提示音",
    "UI": "User Interface - 用户界面音效",
    
    # 转场
    "转场": "Transition - 场景切换时的音效",
    "上升音": "Riser - 音高逐渐上升的转场音效",
    "下降音": "Drop - 音高突然下降的转场音效",
    "刺针音": "Stinger - 短促有力的转场音效",
    
    # 其他常见术语
    "循环": "Loop - 可无缝循环播放的音频",
    "单次": "One-shot - 单次播放的音效",
    "干声": "Dry - 未经混响等效果处理的原始声音",
    "湿声": "Wet - 经过混响等效果处理的声音",
}

class TagsPage(QWidget):
    """
    标签管理页面 (Tags Panel)
    Displays audio files grouped by AI tags.
    """
    
    play_file = Signal(str)
    # 选中标签变化时发出，用于更新音效列表：(display_name, file_paths)
    tags_selection_changed = Signal(str, list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tagsPage")
        
        # 懒加载相关
        self._all_tag_groups = {}  # 所有标签统计 {tag_name: count}
        self._loaded_tags = []     # 已加载的标签
        self._batch_size = 20      # 每批加载 20 个标签
        self._is_loading = False
        
        # 全选相关
        self._is_all_selected = False  # 全选状态标记
        self._selected_items = set()   # 选中的项目
        
        # 平铺视图：tag_name -> checkbox，用于全选/取消时同步
        self._tile_checkboxes = {}
        
        # 标签选中 → 音效列表：防抖计时器
        self._tags_panel_update_timer = QTimer(self)
        self._tags_panel_update_timer.setInterval(120)
        self._tags_panel_update_timer.setSingleShot(True)
        self._tags_panel_update_timer.timeout.connect(self._update_audio_files_panel_from_tags)
        
        self._init_ui()
        self.refresh()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # 全选复选框
        self.select_all_cb = CheckBox("全选")
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        toolbar.addWidget(self.select_all_cb)
        
        # 统计标签
        self.stats_label = CaptionLabel("共 0 个标签")
        toolbar.addWidget(self.stats_label)
        
        toolbar.addStretch()
        
        # 已选标签
        self.selected_label = CaptionLabel("已选 0")
        toolbar.addWidget(self.selected_label)
        
        # 删除按钮
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除选中")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        self.delete_btn.setEnabled(False)
        toolbar.addWidget(self.delete_btn)
        
        # 视图切换：一个按钮，点击弹出菜单选择「列表」或「平铺」
        list_icon = getattr(FluentIcon, 'LIST', FluentIcon.DOCUMENT)
        grid_icon = getattr(FluentIcon, 'GRID', FluentIcon.ALBUM)
        self._view_list_icon = list_icon
        self._view_grid_icon = grid_icon
        self._view_mode_index = 0  # 0=列表 1=平铺
        self.view_mode_btn = TransparentToolButton(list_icon)
        self.view_mode_btn.setToolTip("视图：列表 / 平铺")
        self.view_mode_btn.setFixedSize(32, 32)
        self.view_mode_btn.clicked.connect(self._show_view_mode_menu)
        toolbar.addStretch()
        toolbar.addWidget(self.view_mode_btn)
        
        layout.addLayout(toolbar)
        
        # 列表 / 平铺 双视图
        self.view_stack = QStackedWidget()
        
        # 列表视图：仅标签行，不展开音效（音效在右侧面板勾选标签后显示）
        self.tree = TreeWidget()
        self.tree.setHeaderLabels(["标签"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.view_stack.addWidget(self.tree)
        
        # 平铺视图：标签卡片流式布局
        self.tile_scroll = ScrollArea()
        self.tile_scroll.setWidgetResizable(True)
        self.tile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tile_widget = QWidget()
        self.tile_layout = FlowLayout(self.tile_widget)
        self.tile_scroll.setWidget(self.tile_widget)
        self.view_stack.addWidget(self.tile_scroll)
        
        self.view_stack.setCurrentIndex(0)  # 默认列表
        layout.addWidget(self.view_stack)
    
    def _show_view_mode_menu(self):
        """点击视图按钮时弹出菜单，选择列表或平铺"""
        menu = RoundMenu(parent=self)
        list_action = Action(self._view_list_icon, "列表")
        list_action.triggered.connect(self._on_view_list)
        grid_action = Action(self._view_grid_icon, "平铺")
        grid_action.triggered.connect(self._on_view_tile)
        menu.addAction(list_action)
        menu.addAction(grid_action)
        pos = self.view_mode_btn.mapToGlobal(self.view_mode_btn.rect().bottomLeft())
        menu.exec(pos)
    
    def _on_view_list(self):
        """切换到列表呈现，并同步选中状态"""
        self._view_mode_index = 0
        self.view_mode_btn.setIcon(self._view_list_icon)
        self.view_stack.setCurrentIndex(0)
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "tag":
                tag_name = data.get("name")
                item.setCheckState(0, Qt.CheckState.Checked if (tag_name in self._selected_items or self._is_all_selected) else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
    
    def _on_view_tile(self):
        """切换到平铺呈现，并同步选中状态"""
        self._view_mode_index = 1
        self.view_mode_btn.setIcon(self._view_grid_icon)
        self.view_stack.setCurrentIndex(1)
        for tag_name, cb in self._tile_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(tag_name in self._selected_items or self._is_all_selected)
            cb.blockSignals(False)
        
    def refresh(self):
        """Load tags and files from database"""
        self.tree.clear()
        self._loaded_tags.clear()
        self._selected_items.clear()
        self._is_all_selected = False
        self.select_all_cb.setChecked(False)
        # 清空平铺视图
        self._tile_checkboxes.clear()
        while self.tile_layout.count():
            item = self.tile_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 刷新后若之前有选中，音效列表应清空
        self.tags_selection_changed.emit("", [])
        
        try:
            with session_scope() as session:
                # 只加载标签统计，避免一次性拉取全部文件对象
                tag_counts = (
                    session.query(AudioFileTag.tag, func.count(AudioFileTag.id))
                    .group_by(AudioFileTag.tag)
                    .all()
                )
                self._all_tag_groups = {tag: int(count) for tag, count in tag_counts}
                logger.info(f"Loaded {len(self._all_tag_groups)} tags from database")
            
            # 在会话外更新 UI，避免长时间持锁；并确保首批一定会加载
            total = len(self._all_tag_groups)
            self.stats_label.setText(f"共 {total} 个标签" if total == 0 else f"已加载 0/{total} 个标签")
            self._is_loading = False
            self._load_next_tag_batch()
            
            for sb in (self.tree.verticalScrollBar(), self.tile_scroll.verticalScrollBar()):
                try:
                    sb.valueChanged.disconnect(self._on_scroll)
                except Exception:
                    pass
                sb.valueChanged.connect(self._on_scroll)
                
        except Exception as e:
            logger.error(f"Failed to load tags: {e}")
            NotificationHelper.error(self, "加载失败", str(e))

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = data.get("type")
        
        menu = RoundMenu(parent=self)
        
        if item_type == "file":
            # 播放
            play_action = Action(FluentIcon.PLAY, "播放", self)
            play_action.triggered.connect(lambda: self.play_file.emit(data.get("path")))
            menu.addAction(play_action)
            
            menu.addSeparator()
            
            # Remove Tag
            remove_action = Action(FluentIcon.DELETE, "移除标签", self)
            remove_action.triggered.connect(lambda: self._remove_tag(data.get("id"), data.get("tag")))
            menu.addAction(remove_action)
            
            # Open Folder
            open_action = Action(FluentIcon.FOLDER, "打开所在文件夹", self)
            open_action.triggered.connect(lambda: self._open_folder(data.get("path")))
            menu.addAction(open_action)
        
        elif item_type == "tag":
            # 删除整个标签
            delete_tag_action = Action(FluentIcon.DELETE, "删除此标签", self)
            delete_tag_action.triggered.connect(lambda: self._delete_tag_group(data.get("name")))
            menu.addAction(delete_tag_action)
            
        menu.exec(self.tree.mapToGlobal(pos))

    def _remove_tag(self, file_id, tag_name):
        try:
            with session_scope() as session:
                session.query(AudioFileTag).filter_by(audio_file_id=file_id, tag=tag_name).delete()
                session.commit()
            
            NotificationHelper.success(self, "已移除", f"标签 '{tag_name}' 已移除")
            self.refresh() # Reload tree
            
        except Exception as e:
            NotificationHelper.error(self, "移除失败", str(e))
            
    def _open_folder(self, path_str):
        path = Path(path_str).parent
        if path.exists():
            subprocess.run(['explorer', str(path)])

    def _load_next_tag_batch(self):
        """加载下一批标签（仅标签行，不展开音效；音效在右侧面板勾选标签后显示）"""
        if self._is_loading:
            return
        
        self._is_loading = True
        try:
            all_tags = sorted(self._all_tag_groups.keys())
            remaining_tags = [t for t in all_tags if t not in self._loaded_tags]
            if not remaining_tags:
                return
            
            batch_tags = remaining_tags[:self._batch_size]
            
            for tag_name in batch_tags:
                count = int(self._all_tag_groups.get(tag_name, 0))
                tag_explanation = TAG_EXPLANATIONS.get(tag_name, "")
                display_text = f"{tag_name} ({count})"
                
                # 列表视图：仅标签行
                tag_item = QTreeWidgetItem([display_text])
                tag_item.setIcon(0, FluentIcon.TAG.icon())
                tag_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
                tag_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "tag", "name": tag_name})
                tag_item.setCheckState(0, Qt.CheckState.Checked if (tag_name in self._selected_items or self._is_all_selected) else Qt.CheckState.Unchecked)
                tag_item.setToolTip(0, f"{tag_name}\n\n{tag_explanation}" if tag_explanation else tag_name)
                self.tree.addTopLevelItem(tag_item)
                
                # 平铺视图：标签卡片（使用 QFrame 实现透明背景）
                card = QFrame(self)
                card.setFixedSize(140, 56)
                card.setStyleSheet("""
                    QFrame {
                        background-color: transparent;
                        border: 1px solid #3a3a3a;
                        border-radius: 6px;
                    }
                    QFrame:hover {
                        border-color: #5a5a5a;
                    }
                """)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(10, 6, 10, 6)
                card_layout.setSpacing(4)
                cb = CheckBox(display_text)
                cb.setObjectName("tag_check")
                cb.setChecked(tag_name in self._selected_items or self._is_all_selected)
                cb.stateChanged.connect(lambda state, tn=tag_name: self._on_tile_check_changed(tn, state))
                card_layout.addWidget(cb)
                self._tile_checkboxes[tag_name] = cb
                self.tile_layout.addWidget(card)
                
                self._loaded_tags.append(tag_name)
            
            loaded, total = len(self._loaded_tags), len(self._all_tag_groups)
            logger.info(f"Loaded {loaded}/{total} tags")
            # 更新统计：全部加载完显示「共 N 个标签」，否则「已加载 X/N 个标签」
            self.stats_label.setText(f"共 {total} 个标签" if loaded >= total else f"已加载 {loaded}/{total} 个标签")
            # 若还有未加载标签且当前滚动条无范围（用户无法通过滚动触发加载），则继续加载下一批
            self._schedule_next_batch_if_needed()
        finally:
            self._is_loading = False

    def _schedule_next_batch_if_needed(self):
        """当还有剩余标签且滚动条不可用（maximum<=0）时，用定时器调度加载下一批，避免只显示首批 20 个。"""
        if len(self._loaded_tags) >= len(self._all_tag_groups):
            return
        scrollbar = self.tree.verticalScrollBar() if self.view_stack.currentIndex() == 0 else self.tile_scroll.verticalScrollBar()
        if scrollbar is None or scrollbar.maximum() > 0:
            return
        QTimer.singleShot(0, self._load_next_tag_batch)
    
    def _on_tile_check_changed(self, tag_name: str, state: int):
        """平铺视图复选框变化：与列表逻辑一致，更新选中集合并刷新音效列表"""
        checked = state == Qt.CheckState.Checked.value
        if checked:
            self._selected_items.add(tag_name)
        else:
            self._selected_items.discard(tag_name)
            self._is_all_selected = False
            self.select_all_cb.blockSignals(True)
            self.select_all_cb.setChecked(False)
            self.select_all_cb.blockSignals(False)
        self._update_selected_count()
        self._schedule_tags_panel_update()
    
    def _on_scroll(self, value):
        """滚动事件 - 触发懒加载（列表/平铺共用，由触发滚动的 scrollbar 判断）"""
        scrollbar = self.sender()
        if scrollbar is None or scrollbar.maximum() <= 0:
            return
        if value >= scrollbar.maximum() * 0.8 and len(self._loaded_tags) < len(self._all_tag_groups):
            self._load_next_tag_batch()
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击播放音频文件"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "file":
            file_path = data.get("path")
            logger.info(f"Play file: {file_path}")
            self.play_file.emit(file_path)
    
    def _on_select_all(self, state):
        """全选/取消全选 - 优化版本，不加载所有标签"""
        checked = state == Qt.CheckState.Checked.value
        
        if checked:
            # 标记全选状态（不加载所有标签到 UI）
            self._is_all_selected = True
            total_tags = len(self._all_tag_groups)
            self.selected_label.setText(f"已选 {total_tags} 个标签")
            self.delete_btn.setEnabled(True)
            logger.info(f"All {total_tags} tags selected (virtual selection)")
        else:
            # 取消全选
            self._is_all_selected = False
            self._selected_items.clear()
            
            self.tree.blockSignals(True)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.blockSignals(False)
            
            for cb in self._tile_checkboxes.values():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            
            self.selected_label.setText("已选 0")
            self.delete_btn.setEnabled(False)
        
        # 防抖后更新音效列表
        self._schedule_tags_panel_update()
    
    def _set_children_checked(self, parent_item: QTreeWidgetItem, checked: bool):
        """递归设置子节点的选中状态"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._set_children_checked(child, checked)
    
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """项目选中状态变化"""
        if column != 0:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        item_type = data.get("type")
        checked = item.checkState(0) == Qt.CheckState.Checked
        
        if item_type == "tag":
            tag_name = data.get("name")
            if checked:
                self._selected_items.add(tag_name)
            else:
                self._selected_items.discard(tag_name)
                self._is_all_selected = False
                self.select_all_cb.blockSignals(True)
                self.select_all_cb.setChecked(False)
                self.select_all_cb.blockSignals(False)
        
        # 更新统计
        self._update_selected_count()
        # 防抖后更新音效列表
        self._schedule_tags_panel_update()
    
    def _schedule_tags_panel_update(self):
        """防抖：短时间内的多次勾选只触发一次音效列表更新"""
        self._tags_panel_update_timer.start()
    
    def _update_audio_files_panel_from_tags(self):
        """根据当前选中的标签，收集文件路径并发出 tags_selection_changed"""
        if self._is_all_selected:
            tag_names = list(self._all_tag_groups.keys())
        else:
            tag_names = list(self._selected_items)
        
        if not tag_names:
            self.tags_selection_changed.emit("", [])
            return
        
        path_set = set()
        try:
            with session_scope() as session:
                q = session.query(AudioFile.file_path).join(AudioFileTag)
                if not self._is_all_selected:
                    q = q.filter(AudioFileTag.tag.in_(tag_names))
                q = q.distinct()
                processed = 0
                for (path_str,) in q.yield_per(1000):
                    if path_str:
                        path_set.add(str(path_str))
                    processed += 1
                    if processed % 1000 == 0:
                        QApplication.processEvents()
        except Exception as e:
            logger.error(f"Failed to build file list from tags: {e}")
            NotificationHelper.error(self, "构建文件列表失败", str(e))
            self.tags_selection_changed.emit("", [])
            return
        
        paths = sorted(path_set)
        if len(tag_names) == 1:
            display_name = tag_names[0]
        elif len(tag_names) <= 3:
            display_name = ", ".join(tag_names)
        else:
            display_name = f"{tag_names[0]}, {tag_names[1]} +{len(tag_names) - 2}个"
        
        logger.info(f"Tags selection: {len(paths)} files from {len(tag_names)} tags -> sound list")
        self.tags_selection_changed.emit(display_name, paths)
    
    def _update_selected_count(self):
        """更新选中数量显示"""
        if self._is_all_selected:
            count = len(self._all_tag_groups)
        else:
            count = len(self._selected_items)
        
        self.selected_label.setText(f"已选 {count}")
        self.delete_btn.setEnabled(count > 0)
    
    def _on_delete_selected(self):
        """删除选中的标签"""
        if self._is_all_selected:
            # 全选状态：删除所有标签
            tag_names = list(self._all_tag_groups.keys())
        else:
            # 部分选中：删除选中的标签
            tag_names = list(self._selected_items)
        
        if not tag_names:
            NotificationHelper.warning(self, "未选中", "请先选择要删除的标签")
            return
        
        # 确认对话框
        reply = MessageBox(
            "确认删除",
            f"确定要删除 {len(tag_names)} 个标签吗？\n这将移除这些标签与所有音频文件的关联。",
            self
        ).exec()
        
        if not reply:
            return
        
        try:
            with session_scope() as session:
                # 批量删除标签
                session.query(AudioFileTag).filter(
                    AudioFileTag.tag.in_(tag_names)
                ).delete(synchronize_session=False)
                session.commit()
            
            logger.info(f"Deleted {len(tag_names)} tags")
            NotificationHelper.success(self, "删除成功", f"已删除 {len(tag_names)} 个标签")
            
            # 刷新界面
            self.refresh()
            
        except Exception as e:
            logger.error(f"Failed to delete tags: {e}")
            NotificationHelper.error(self, "删除失败", str(e))
    
    def _delete_tag_group(self, tag_name: str):
        """删除单个标签组"""
        reply = MessageBox(
            "确认删除",
            f"确定要删除标签 '{tag_name}' 吗？\n这将移除该标签与所有音频文件的关联。",
            self
        ).exec()
        
        if not reply:
            return
        
        try:
            with session_scope() as session:
                session.query(AudioFileTag).filter_by(tag=tag_name).delete()
                session.commit()
            
            logger.info(f"Deleted tag: {tag_name}")
            NotificationHelper.success(self, "删除成功", f"已删除标签 '{tag_name}'")
            
            # 刷新界面
            self.refresh()
            
        except Exception as e:
            logger.error(f"Failed to delete tag: {e}")
            NotificationHelper.error(self, "删除失败", str(e))
