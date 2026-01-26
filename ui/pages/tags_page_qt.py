
import logging
import subprocess
from pathlib import Path
from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidgetItem, 
    QHeaderView, QAbstractItemView, QApplication
)
from PySide6.QtGui import QFont, QAction

from qfluentwidgets import (
    TreeWidget, FluentIcon, SubtitleLabel, CaptionLabel,
    RoundMenu, Action, IconWidget, TransparentToolButton,
    CheckBox, PushButton, MessageBox
)

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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tagsPage")
        
        # 懒加载相关
        self._all_tag_groups = {}  # 所有标签分组 {tag_name: [files]}
        self._loaded_tags = []     # 已加载的标签
        self._batch_size = 20      # 每批加载 20 个标签
        self._is_loading = False
        
        # 全选相关
        self._is_all_selected = False  # 全选状态标记
        self._selected_items = set()   # 选中的项目
        
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
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除选中标签")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        self.delete_btn.setEnabled(False)
        toolbar.addWidget(self.delete_btn)
        
        layout.addLayout(toolbar)
        
        # Tree
        self.tree = TreeWidget()
        self.tree.setHeaderLabels(["标签 / 文件名", "时长", "格式", ""])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.header().resizeSection(3, 40)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        
        # 连接双击事件
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        # 连接选中变化事件
        self.tree.itemChanged.connect(self._on_item_changed)
        
        layout.addWidget(self.tree)
        
    def refresh(self):
        """Load tags and files from database"""
        self.tree.clear()
        self._loaded_tags.clear()
        self._selected_items.clear()
        self._is_all_selected = False
        self.select_all_cb.setChecked(False)
        
        try:
            with session_scope() as session:
                # Query all tags joined with files
                tags = session.query(AudioFileTag).join(AudioFile).all()
                
                # Group by tag
                tag_groups = defaultdict(list)
                for t in tags:
                    tag_groups[t.tag].append(t.audio_file)
                
                # 保存所有标签分组
                self._all_tag_groups = dict(tag_groups)
                
                logger.info(f"Loaded {len(self._all_tag_groups)} tags from database")
                
                # 更新统计
                self.stats_label.setText(f"共 {len(self._all_tag_groups)} 个标签")
                
                # 懒加载：只加载初始批次
                self._load_next_tag_batch()
                
                # 连接滚动信号
                scrollbar = self.tree.verticalScrollBar()
                try:
                    scrollbar.valueChanged.disconnect(self._on_scroll)
                except:
                    pass
                scrollbar.valueChanged.connect(self._on_scroll)
                
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
        """加载下一批标签"""
        if self._is_loading:
            return
        
        self._is_loading = True
        
        # 获取未加载的标签
        all_tags = sorted(self._all_tag_groups.keys())
        remaining_tags = [t for t in all_tags if t not in self._loaded_tags]
        
        if not remaining_tags:
            self._is_loading = False
            return
        
        # 加载下一批
        batch_tags = remaining_tags[:self._batch_size]
        
        for tag_name in batch_tags:
            files = self._all_tag_groups[tag_name]
            
            # 获取标签解释
            tag_explanation = TAG_EXPLANATIONS.get(tag_name, "")
            
            # Root Item: Tag (添加解释和复选框)
            display_text = f"{tag_name} ({len(files)})"
            
            tag_item = QTreeWidgetItem([display_text, "", "", ""])
            tag_item.setIcon(0, FluentIcon.TAG.icon())
            tag_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
            tag_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "tag", "name": tag_name})
            tag_item.setCheckState(0, Qt.CheckState.Unchecked)  # 添加复选框
            
            # 设置 tooltip 显示完整解释
            if tag_explanation:
                tag_item.setToolTip(0, f"{tag_name}\n\n{tag_explanation}")
            else:
                tag_item.setToolTip(0, tag_name)
            
            self.tree.addTopLevelItem(tag_item)
            
            # Children: Files
            for f in files:
                duration_str = f"{int(f.duration//60):02d}:{int(f.duration%60):02d}"
                
                file_item = QTreeWidgetItem([f.filename, duration_str, f.format, ""])
                file_item.setIcon(0, FluentIcon.MUSIC.icon())
                file_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "file", 
                    "path": f.file_path, 
                    "id": f.id,
                    "tag": tag_name
                })
                
                # 添加播放按钮
                play_btn = TransparentToolButton(FluentIcon.PLAY)
                play_btn.setFixedSize(28, 28)
                play_btn.clicked.connect(lambda checked, fp=f.file_path: self.play_file.emit(fp))
                self.tree.setItemWidget(file_item, 3, play_btn)
                
                tag_item.addChild(file_item)
            
            tag_item.setExpanded(True)
            self._loaded_tags.append(tag_name)
        
        self._is_loading = False
        logger.info(f"Loaded {len(self._loaded_tags)}/{len(self._all_tag_groups)} tags")
    
    def _on_scroll(self, value):
        """滚动事件 - 触发懒加载"""
        scrollbar = self.tree.verticalScrollBar()
        
        # 滚动到底部 80% 时加载下一批
        if scrollbar.maximum() > 0 and value >= scrollbar.maximum() * 0.8:
            if len(self._loaded_tags) < len(self._all_tag_groups):
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
            
            # 取消 UI 中已加载标签的选中状态
            self.tree.blockSignals(True)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self._set_children_checked(item, False)
            self.tree.blockSignals(False)
            
            self.selected_label.setText("已选 0")
            self.delete_btn.setEnabled(False)
    
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
