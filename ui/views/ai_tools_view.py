"""
AI Tools View

AI工具视图，包含分类、标签建议、相似音频搜索等功能。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject, Pango

from transcriptionist_v3.application.ai_engine import (
    TagManager,
    AudioAnalyzer,
    ClassificationResult,
    SimilarityResult,
)

logger = logging.getLogger(__name__)


class ClassificationResultCard(Gtk.Box):
    """
    分类结果卡片
    
    显示单个文件的分类结果。
    """
    
    __gtype_name__ = "ClassificationResultCard"
    
    def __init__(self, filename: str, result: Optional[ClassificationResult] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        
        self._filename = filename
        self._result = result
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 文件名
        name_label = Gtk.Label(label=self._filename)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name_label.add_css_class("heading")
        self.append(name_label)
        
        if self._result:
            # 主分类
            category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            category_label = Gtk.Label(label=self._result.category)
            category_label.add_css_class("title-4")
            category_box.append(category_label)
            
            # 置信度
            confidence_label = Gtk.Label(
                label=f"{self._result.confidence * 100:.1f}%"
            )
            confidence_label.add_css_class("dim-label")
            category_box.append(confidence_label)
            
            self.append(category_box)
            
            # 子分类标签
            if self._result.subcategories:
                tags_box = Gtk.FlowBox()
                tags_box.set_selection_mode(Gtk.SelectionMode.NONE)
                tags_box.set_max_children_per_line(5)
                
                for subcat in self._result.subcategories:
                    tag = Gtk.Label(label=subcat)
                    tag.add_css_class("tag")
                    tags_box.append(tag)
                
                self.append(tags_box)
        else:
            # 未分类状态
            pending_label = Gtk.Label(label="等待分类...")
            pending_label.add_css_class("dim-label")
            self.append(pending_label)


class ClassificationPanel(Gtk.Box):
    """
    分类面板
    
    显示音频分类结果。
    注意：分类功能预留，等待CLAP模型集成。
    """
    
    __gtype_name__ = "ClassificationPanel"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("classification-panel")
        
        self._results: Dict[str, ClassificationResult] = {}
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="音频分类")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        
        # 分类按钮
        self._classify_button = Gtk.Button(label="开始分类")
        self._classify_button.add_css_class("suggested-action")
        self._classify_button.set_sensitive(False)  # 功能未实现
        header.append(self._classify_button)
        
        self.append(header)
        
        # 提示信息
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.add_css_class("info-box")
        
        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_box.append(info_icon)
        
        info_label = Gtk.Label(
            label="音频分类功能正在开发中，将使用CLAP模型进行智能分类。"
        )
        info_label.set_wrap(True)
        info_label.add_css_class("dim-label")
        info_box.append(info_label)
        
        self.append(info_box)
        
        # 结果列表
        self._result_list = Gtk.ListBox()
        self._result_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._result_list.add_css_class("boxed-list")
        
        # 空状态
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_margin_top(24)
        empty_box.set_margin_bottom(24)
        
        empty_icon = Gtk.Image.new_from_icon_name("folder-music-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        empty_box.append(empty_icon)
        
        empty_label = Gtk.Label(label="选择音频文件进行分类")
        empty_label.add_css_class("dim-label")
        empty_box.append(empty_label)
        
        self._result_list.set_placeholder(empty_box)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        scrolled.set_child(self._result_list)
        
        self.append(scrolled)
    
    def add_result(self, filename: str, result: ClassificationResult) -> None:
        """添加分类结果"""
        self._results[filename] = result
        card = ClassificationResultCard(filename, result)
        self._result_list.append(card)
    
    def clear_results(self) -> None:
        """清空结果"""
        self._results.clear()
        while True:
            row = self._result_list.get_row_at_index(0)
            if row is None:
                break
            self._result_list.remove(row)


class TagSuggestionPanel(Gtk.Box):
    """
    标签建议面板
    
    显示和编辑自动生成的标签。
    """
    
    __gtype_name__ = "TagSuggestionPanel"
    
    __gsignals__ = {
        "tags-applied": (GObject.SignalFlags.RUN_LAST, None, (str, object)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("tag-suggestion-panel")
        
        self._current_filename = ""
        self._suggested_tags: List[str] = []
        self._tag_manager = TagManager.instance()
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="标签建议")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        
        # 生成按钮
        self._generate_button = Gtk.Button(label="生成标签")
        self._generate_button.connect("clicked", self._on_generate_clicked)
        header.append(self._generate_button)
        
        self.append(header)
        
        # 文件名输入
        filename_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        filename_label = Gtk.Label(label="文件名")
        filename_label.set_halign(Gtk.Align.START)
        filename_label.add_css_class("caption")
        filename_box.append(filename_label)
        
        self._filename_entry = Gtk.Entry()
        self._filename_entry.set_placeholder_text("输入文件名以生成标签...")
        filename_box.append(self._filename_entry)
        
        self.append(filename_box)
        
        # 建议的标签
        tags_frame = Gtk.Frame()
        tags_frame.set_label("建议标签")
        
        self._tags_flow = Gtk.FlowBox()
        self._tags_flow.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self._tags_flow.set_max_children_per_line(6)
        self._tags_flow.set_min_children_per_line(2)
        self._tags_flow.set_homogeneous(True)
        self._tags_flow.set_margin_start(8)
        self._tags_flow.set_margin_end(8)
        self._tags_flow.set_margin_top(8)
        self._tags_flow.set_margin_bottom(8)
        
        tags_frame.set_child(self._tags_flow)
        self.append(tags_frame)
        
        # 应用按钮
        apply_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_box.set_halign(Gtk.Align.END)
        
        self._apply_button = Gtk.Button(label="应用选中标签")
        self._apply_button.add_css_class("suggested-action")
        self._apply_button.connect("clicked", self._on_apply_clicked)
        self._apply_button.set_sensitive(False)
        apply_box.append(self._apply_button)
        
        self.append(apply_box)
    
    def _on_generate_clicked(self, button: Gtk.Button) -> None:
        """生成标签"""
        filename = self._filename_entry.get_text().strip()
        if not filename:
            return
        
        self._current_filename = filename
        
        # 异步生成标签
        def do_generate():
            async def generate():
                tags = await self._tag_manager.generate_tags(filename)
                GLib.idle_add(self._on_tags_generated, tags)
            
            asyncio.run(generate())
        
        import threading
        thread = threading.Thread(target=do_generate, daemon=True)
        thread.start()
    
    def _on_tags_generated(self, tags: List[str]) -> bool:
        """标签生成完成"""
        self._suggested_tags = tags
        self._update_tags_display()
        return False
    
    def _update_tags_display(self) -> None:
        """更新标签显示"""
        # 清空现有标签
        while True:
            child = self._tags_flow.get_child_at_index(0)
            if child is None:
                break
            self._tags_flow.remove(child)
        
        # 添加新标签
        for tag in self._suggested_tags:
            tag_button = Gtk.ToggleButton(label=tag)
            tag_button.add_css_class("tag-button")
            tag_button.set_active(True)
            tag_button.connect("toggled", self._on_tag_toggled)
            self._tags_flow.append(tag_button)
        
        self._apply_button.set_sensitive(len(self._suggested_tags) > 0)
    
    def _on_tag_toggled(self, button: Gtk.ToggleButton) -> None:
        """标签切换"""
        # 检查是否有选中的标签
        has_selected = False
        for i in range(100):  # 假设最多100个标签
            child = self._tags_flow.get_child_at_index(i)
            if child is None:
                break
            button = child.get_child()
            if isinstance(button, Gtk.ToggleButton) and button.get_active():
                has_selected = True
                break
        
        self._apply_button.set_sensitive(has_selected)
    
    def _on_apply_clicked(self, button: Gtk.Button) -> None:
        """应用标签"""
        selected_tags = []
        
        for i in range(100):
            child = self._tags_flow.get_child_at_index(i)
            if child is None:
                break
            btn = child.get_child()
            if isinstance(btn, Gtk.ToggleButton) and btn.get_active():
                selected_tags.append(btn.get_label())
        
        if selected_tags:
            self.emit("tags-applied", self._current_filename, selected_tags)
    
    def set_filename(self, filename: str) -> None:
        """设置文件名"""
        self._filename_entry.set_text(filename)


class SimilarSoundsPanel(Gtk.Box):
    """
    相似音频面板
    
    显示相似音频搜索结果。
    注意：功能预留，等待CLAP模型集成。
    """
    
    __gtype_name__ = "SimilarSoundsPanel"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("similar-sounds-panel")
        
        self._results: List[SimilarityResult] = []
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="相似音频")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        
        # 搜索按钮
        self._search_button = Gtk.Button(label="查找相似")
        self._search_button.add_css_class("suggested-action")
        self._search_button.set_sensitive(False)  # 功能未实现
        header.append(self._search_button)
        
        self.append(header)
        
        # 提示信息
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.add_css_class("info-box")
        
        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_box.append(info_icon)
        
        info_label = Gtk.Label(
            label="相似音频搜索功能正在开发中，将使用CLAP模型进行声学特征匹配。"
        )
        info_label.set_wrap(True)
        info_label.add_css_class("dim-label")
        info_box.append(info_label)
        
        self.append(info_box)
        
        # 结果列表
        self._result_list = Gtk.ListBox()
        self._result_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._result_list.add_css_class("boxed-list")
        
        # 空状态
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_margin_top(24)
        empty_box.set_margin_bottom(24)
        
        empty_icon = Gtk.Image.new_from_icon_name("edit-find-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        empty_box.append(empty_icon)
        
        empty_label = Gtk.Label(label="选择音频文件查找相似音效")
        empty_label.add_css_class("dim-label")
        empty_box.append(empty_label)
        
        self._result_list.set_placeholder(empty_box)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        scrolled.set_child(self._result_list)
        
        self.append(scrolled)
    
    def set_results(self, results: List[SimilarityResult]) -> None:
        """设置搜索结果"""
        self._results = results
        
        # 清空现有结果
        while True:
            row = self._result_list.get_row_at_index(0)
            if row is None:
                break
            self._result_list.remove(row)
        
        # 添加新结果
        for result in results:
            row = self._create_result_row(result)
            self._result_list.append(row)
    
    def _create_result_row(self, result: SimilarityResult) -> Gtk.Box:
        """创建结果行"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        
        # 文件名
        name_label = Gtk.Label(label=result.file_path.name)
        name_label.set_hexpand(True)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        row.append(name_label)
        
        # 相似度
        similarity_label = Gtk.Label(
            label=f"{result.similarity * 100:.1f}%"
        )
        similarity_label.add_css_class("dim-label")
        row.append(similarity_label)
        
        return row
