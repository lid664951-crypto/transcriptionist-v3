"""
Queue View Widget

GTK4 播放队列显示组件，显示和管理播放队列。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List, Callable
from dataclasses import dataclass

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject, Gio, Pango

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """队列项"""
    id: str
    title: str
    subtitle: str = ""
    duration_ms: int = 0
    file_path: Optional[Path] = None


class QueueItemWidget(Gtk.Box):
    """队列项组件"""
    
    __gtype_name__ = "QueueItemWidget"
    
    def __init__(self, item: QueueItem, index: int):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("queue-item")
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        self._item = item
        self._index = index
        self._is_current = False
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 序号
        self._index_label = Gtk.Label(label=str(self._index + 1))
        self._index_label.set_width_chars(3)
        self._index_label.add_css_class("dim-label")
        self.append(self._index_label)
        
        # 信息区域
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        # 标题
        title_label = Gtk.Label(label=self._item.title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        info_box.append(title_label)
        
        # 副标题
        if self._item.subtitle:
            subtitle_label = Gtk.Label(label=self._item.subtitle)
            subtitle_label.set_halign(Gtk.Align.START)
            subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle_label.add_css_class("dim-label")
            subtitle_label.add_css_class("caption")
            info_box.append(subtitle_label)
        
        self.append(info_box)
        
        # 时长
        if self._item.duration_ms > 0:
            duration_str = self._format_duration(self._item.duration_ms)
            duration_label = Gtk.Label(label=duration_str)
            duration_label.add_css_class("dim-label")
            duration_label.add_css_class("monospace")
            self.append(duration_label)
    
    def _format_duration(self, ms: int) -> str:
        """格式化时长"""
        seconds = ms // 1000
        minutes = seconds // 60
        return f"{minutes}:{seconds % 60:02d}"
    
    def set_current(self, is_current: bool) -> None:
        """设置是否为当前播放项"""
        self._is_current = is_current
        if is_current:
            self.add_css_class("current-item")
            self._index_label.set_label("▶")
        else:
            self.remove_css_class("current-item")
            self._index_label.set_label(str(self._index + 1))
    
    @property
    def item(self) -> QueueItem:
        return self._item
    
    @property
    def index(self) -> int:
        return self._index


class QueueView(Gtk.Box):
    """
    播放队列视图
    
    功能：
    - 显示播放队列
    - 高亮当前播放项
    - 支持拖拽排序
    - 支持删除项目
    - 支持清空队列
    """
    
    __gtype_name__ = "QueueView"
    
    __gsignals__ = {
        "item-activated": (GObject.SignalFlags.RUN_LAST, None, (str,)),  # item_id
        "item-removed": (GObject.SignalFlags.RUN_LAST, None, (str,)),  # item_id
        "queue-cleared": (GObject.SignalFlags.RUN_LAST, None, ()),
        "order-changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("queue-view")
        
        self._items: List[QueueItem] = []
        self._current_index = -1
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题栏
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("toolbar")
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(8)
        header.set_margin_bottom(4)
        
        title = Gtk.Label(label="播放队列")
        title.add_css_class("heading")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        
        # 队列数量
        self._count_label = Gtk.Label(label="0 首")
        self._count_label.add_css_class("dim-label")
        header.append(self._count_label)
        
        # 清空按钮
        clear_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        clear_button.add_css_class("flat")
        clear_button.set_tooltip_text("清空队列")
        clear_button.connect("clicked", self._on_clear_clicked)
        header.append(clear_button)
        
        self.append(header)
        
        # 分隔线
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(separator)
        
        # 滚动区域
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # 列表容器
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.connect("row-activated", self._on_row_activated)
        
        # 空状态占位符
        self._empty_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._empty_placeholder.set_valign(Gtk.Align.CENTER)
        self._empty_placeholder.set_margin_top(48)
        self._empty_placeholder.set_margin_bottom(48)
        
        empty_icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        self._empty_placeholder.append(empty_icon)
        
        empty_label = Gtk.Label(label="队列为空")
        empty_label.add_css_class("dim-label")
        self._empty_placeholder.append(empty_label)
        
        self._list_box.set_placeholder(self._empty_placeholder)
        
        scrolled.set_child(self._list_box)
        self.append(scrolled)
    
    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """行激活"""
        if row:
            widget = row.get_child()
            if isinstance(widget, QueueItemWidget):
                self.emit("item-activated", widget.item.id)
    
    def _on_clear_clicked(self, button: Gtk.Button) -> None:
        """清空队列"""
        self.clear()
        self.emit("queue-cleared")
    
    def _update_count(self) -> None:
        """更新数量显示"""
        count = len(self._items)
        self._count_label.set_label(f"{count} 首")
    
    def _rebuild_list(self) -> None:
        """重建列表"""
        # 清空现有行
        while True:
            row = self._list_box.get_row_at_index(0)
            if row is None:
                break
            self._list_box.remove(row)
        
        # 添加新行
        for i, item in enumerate(self._items):
            widget = QueueItemWidget(item, i)
            widget.set_current(i == self._current_index)
            self._list_box.append(widget)
        
        self._update_count()
    
    def set_items(self, items: List[QueueItem]) -> None:
        """设置队列项"""
        self._items = items.copy()
        self._rebuild_list()
    
    def add_item(self, item: QueueItem) -> None:
        """添加项目"""
        self._items.append(item)
        widget = QueueItemWidget(item, len(self._items) - 1)
        self._list_box.append(widget)
        self._update_count()
    
    def insert_item(self, index: int, item: QueueItem) -> None:
        """插入项目"""
        self._items.insert(index, item)
        self._rebuild_list()
    
    def remove_item(self, item_id: str) -> None:
        """移除项目"""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                self._items.pop(i)
                if self._current_index >= i:
                    self._current_index = max(-1, self._current_index - 1)
                break
        self._rebuild_list()
        self.emit("item-removed", item_id)
    
    def clear(self) -> None:
        """清空队列"""
        self._items.clear()
        self._current_index = -1
        self._rebuild_list()
    
    def set_current_index(self, index: int) -> None:
        """设置当前播放索引"""
        self._current_index = index
        
        # 更新所有项的状态
        for i in range(len(self._items)):
            row = self._list_box.get_row_at_index(i)
            if row:
                widget = row.get_child()
                if isinstance(widget, QueueItemWidget):
                    widget.set_current(i == index)
        
        # 滚动到当前项
        if 0 <= index < len(self._items):
            row = self._list_box.get_row_at_index(index)
            if row:
                row.grab_focus()
    
    def set_current_item(self, item_id: str) -> None:
        """设置当前播放项"""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                self.set_current_index(i)
                return
    
    def get_current_item(self) -> Optional[QueueItem]:
        """获取当前播放项"""
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return None
    
    def get_next_item(self) -> Optional[QueueItem]:
        """获取下一项"""
        next_index = self._current_index + 1
        if 0 <= next_index < len(self._items):
            return self._items[next_index]
        return None
    
    def get_previous_item(self) -> Optional[QueueItem]:
        """获取上一项"""
        prev_index = self._current_index - 1
        if 0 <= prev_index < len(self._items):
            return self._items[prev_index]
        return None
    
    def move_to_next(self) -> Optional[QueueItem]:
        """移动到下一项"""
        next_item = self.get_next_item()
        if next_item:
            self.set_current_index(self._current_index + 1)
        return next_item
    
    def move_to_previous(self) -> Optional[QueueItem]:
        """移动到上一项"""
        prev_item = self.get_previous_item()
        if prev_item:
            self.set_current_index(self._current_index - 1)
        return prev_item
    
    @property
    def items(self) -> List[QueueItem]:
        """获取所有项目"""
        return self._items.copy()
    
    @property
    def count(self) -> int:
        """获取项目数量"""
        return len(self._items)
    
    @property
    def current_index(self) -> int:
        """获取当前索引"""
        return self._current_index
