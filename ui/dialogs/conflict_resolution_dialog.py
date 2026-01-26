"""
Conflict Resolution Dialog

文件名冲突解决对话框，支持单个和批量冲突处理。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from enum import Enum

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Gio, Pango

from transcriptionist_v3.application.naming_manager import (
    RenameOperation,
    ConflictResolution,
)

logger = logging.getLogger(__name__)


class ConflictAction(Enum):
    """冲突处理动作"""
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"
    KEEP_BOTH = "keep_both"
    CANCEL = "cancel"


class ConflictResolutionDialog(Adw.MessageDialog):
    """
    单个冲突解决对话框
    
    当重命名操作遇到文件名冲突时显示。
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        operation: Optional[RenameOperation] = None,
        on_resolve: Optional[Callable[[ConflictAction, str], None]] = None,
    ):
        super().__init__()
        
        self._operation = operation
        self._on_resolve = on_resolve
        self._new_name = operation.target_name if operation else ""
        
        # 设置对话框属性
        if parent:
            self.set_transient_for(parent)
        self.set_modal(True)
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建用户界面"""
        self.set_heading("文件名冲突")
        
        if self._operation:
            source_name = self._operation.source_name
            target_name = self._operation.target_name
            target_dir = str(Path(self._operation.target).parent)
            
            body = (
                f"目标位置已存在同名文件：\n\n"
                f"源文件: {source_name}\n"
                f"目标文件: {target_name}\n"
                f"目标目录: {target_dir}\n\n"
                f"请选择如何处理此冲突："
            )
        else:
            body = "目标位置已存在同名文件，请选择如何处理此冲突："
        
        self.set_body(body)
        
        # 添加响应按钮
        self.add_response("cancel", "取消")
        self.add_response("skip", "跳过")
        self.add_response("rename", "自动重命名")
        self.add_response("overwrite", "覆盖")
        
        # 设置按钮样式
        self.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
        self.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        
        self.set_default_response("rename")
        self.set_close_response("cancel")
        
        # 添加额外内容区域
        extra_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        extra_box.set_margin_top(16)
        
        # 自定义名称输入
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        name_label = Gtk.Label(label="或输入新名称:")
        name_box.append(name_label)
        
        self._name_entry = Gtk.Entry()
        self._name_entry.set_text(self._new_name)
        self._name_entry.set_hexpand(True)
        self._name_entry.connect("changed", self._on_name_changed)
        name_box.append(self._name_entry)
        
        extra_box.append(name_box)
        
        # 使用自定义名称按钮
        self._use_custom_btn = Gtk.Button(label="使用此名称")
        self._use_custom_btn.add_css_class("suggested-action")
        self._use_custom_btn.set_halign(Gtk.Align.END)
        self._use_custom_btn.connect("clicked", self._on_use_custom)
        self._use_custom_btn.set_sensitive(False)
        extra_box.append(self._use_custom_btn)
        
        self.set_extra_child(extra_box)
        
        # 连接响应信号
        self.connect("response", self._on_response)
    
    def _on_name_changed(self, entry: Gtk.Entry) -> None:
        """名称输入变化"""
        new_name = entry.get_text().strip()
        is_different = new_name and new_name != self._new_name
        self._use_custom_btn.set_sensitive(is_different)
    
    def _on_use_custom(self, button: Gtk.Button) -> None:
        """使用自定义名称"""
        new_name = self._name_entry.get_text().strip()
        if new_name and self._on_resolve:
            self._on_resolve(ConflictAction.RENAME, new_name)
        self.close()
    
    def _on_response(self, dialog: Adw.MessageDialog, response: str) -> None:
        """响应处理"""
        if not self._on_resolve:
            return
        
        action_map = {
            "cancel": ConflictAction.CANCEL,
            "skip": ConflictAction.SKIP,
            "rename": ConflictAction.RENAME,
            "overwrite": ConflictAction.OVERWRITE,
        }
        
        action = action_map.get(response, ConflictAction.CANCEL)
        self._on_resolve(action, self._new_name)


class BatchConflictResolutionDialog(Adw.Window):
    """
    批量冲突解决对话框
    
    当批量重命名操作遇到多个冲突时显示。
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        conflicts: Optional[List[RenameOperation]] = None,
        on_resolve: Optional[Callable[[Dict[str, ConflictAction]], None]] = None,
    ):
        super().__init__()
        
        self._conflicts = conflicts or []
        self._on_resolve = on_resolve
        self._resolutions: Dict[str, ConflictAction] = {}
        
        # 初始化所有冲突为跳过
        for op in self._conflicts:
            self._resolutions[op.source] = ConflictAction.SKIP
        
        # 设置窗口属性
        self.set_title("解决冲突")
        self.set_default_size(700, 500)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)
        
        self._build_ui()
        self._populate_list()
    
    def _build_ui(self) -> None:
        """构建用户界面"""
        # 主容器
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # 标题栏
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        
        # 取消按钮
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _: self._on_cancel())
        header.pack_start(cancel_btn)
        
        # 应用按钮
        self._apply_btn = Gtk.Button(label="应用")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", self._on_apply)
        header.pack_end(self._apply_btn)
        
        # 标题
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label(label="解决文件名冲突")
        title_label.add_css_class("title")
        title_box.append(title_label)
        
        subtitle_label = Gtk.Label(label=f"发现 {len(self._conflicts)} 个冲突")
        subtitle_label.add_css_class("subtitle")
        title_box.append(subtitle_label)
        
        header.set_title_widget(title_box)
        main_box.append(header)
        
        # 工具栏
        toolbar = self._create_toolbar()
        main_box.append(toolbar)
        
        # 冲突列表
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        self._list_box.set_margin_top(8)
        self._list_box.set_margin_bottom(16)
        
        scrolled.set_child(self._list_box)
        main_box.append(scrolled)
        
        # 状态栏
        status_bar = self._create_status_bar()
        main_box.append(status_bar)
    
    def _create_toolbar(self) -> Gtk.Box:
        """创建工具栏"""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(16)
        toolbar.set_margin_end(16)
        toolbar.set_margin_top(8)
        toolbar.set_margin_bottom(8)
        
        # 批量操作标签
        label = Gtk.Label(label="全部设为:")
        toolbar.append(label)
        
        # 全部跳过
        skip_all_btn = Gtk.Button(label="跳过")
        skip_all_btn.connect("clicked", lambda _: self._set_all_action(ConflictAction.SKIP))
        toolbar.append(skip_all_btn)
        
        # 全部重命名
        rename_all_btn = Gtk.Button(label="自动重命名")
        rename_all_btn.connect("clicked", lambda _: self._set_all_action(ConflictAction.RENAME))
        toolbar.append(rename_all_btn)
        
        # 全部覆盖
        overwrite_all_btn = Gtk.Button(label="覆盖")
        overwrite_all_btn.add_css_class("destructive-action")
        overwrite_all_btn.connect("clicked", lambda _: self._set_all_action(ConflictAction.OVERWRITE))
        toolbar.append(overwrite_all_btn)
        
        return toolbar
    
    def _create_status_bar(self) -> Gtk.Box:
        """创建状态栏"""
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_bar.set_margin_start(16)
        status_bar.set_margin_end(16)
        status_bar.set_margin_top(8)
        status_bar.set_margin_bottom(8)
        
        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)
        status_bar.append(self._status_label)
        
        self._update_status()
        
        return status_bar
    
    def _populate_list(self) -> None:
        """填充冲突列表"""
        for op in self._conflicts:
            row = self._create_conflict_row(op)
            self._list_box.append(row)
    
    def _create_conflict_row(self, operation: RenameOperation) -> Adw.ExpanderRow:
        """创建冲突行"""
        row = Adw.ExpanderRow()
        row.set_title(operation.source_name)
        row.set_subtitle(f"→ {operation.target_name}")
        row.operation = operation  # 存储操作引用
        
        # 警告图标
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(16)
        row.add_prefix(icon)
        
        # 操作选择下拉框
        action_dropdown = Gtk.DropDown()
        model = Gtk.StringList()
        model.append("跳过")
        model.append("自动重命名")
        model.append("覆盖")
        action_dropdown.set_model(model)
        action_dropdown.set_selected(0)
        action_dropdown.set_valign(Gtk.Align.CENTER)
        action_dropdown.connect("notify::selected", self._on_action_changed, operation)
        row.add_suffix(action_dropdown)
        row.action_dropdown = action_dropdown
        
        # 展开内容：详细信息
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        detail_box.set_margin_start(16)
        detail_box.set_margin_end(16)
        detail_box.set_margin_top(8)
        detail_box.set_margin_bottom(8)
        
        # 源文件路径
        source_label = Gtk.Label(label=f"源文件: {operation.source}")
        source_label.set_halign(Gtk.Align.START)
        source_label.set_wrap(True)
        source_label.add_css_class("dim-label")
        detail_box.append(source_label)
        
        # 目标文件路径
        target_label = Gtk.Label(label=f"目标: {operation.target}")
        target_label.set_halign(Gtk.Align.START)
        target_label.set_wrap(True)
        target_label.add_css_class("dim-label")
        detail_box.append(target_label)
        
        # 冲突原因
        if Path(operation.target).exists():
            reason = "目标文件已存在"
        else:
            reason = "与其他重命名操作冲突"
        
        reason_label = Gtk.Label(label=f"原因: {reason}")
        reason_label.set_halign(Gtk.Align.START)
        reason_label.add_css_class("warning")
        detail_box.append(reason_label)
        
        row.add_row(detail_box)
        
        return row
    
    def _on_action_changed(self, dropdown: Gtk.DropDown, pspec, operation: RenameOperation) -> None:
        """操作选择变化"""
        selected = dropdown.get_selected()
        action_map = {
            0: ConflictAction.SKIP,
            1: ConflictAction.RENAME,
            2: ConflictAction.OVERWRITE,
        }
        self._resolutions[operation.source] = action_map.get(selected, ConflictAction.SKIP)
        self._update_status()
    
    def _set_all_action(self, action: ConflictAction) -> None:
        """设置所有冲突的操作"""
        action_index = {
            ConflictAction.SKIP: 0,
            ConflictAction.RENAME: 1,
            ConflictAction.OVERWRITE: 2,
        }.get(action, 0)
        
        # 更新所有下拉框
        row = self._list_box.get_row_at_index(0)
        index = 0
        while row:
            if hasattr(row, 'action_dropdown'):
                row.action_dropdown.set_selected(action_index)
            if hasattr(row, 'operation'):
                self._resolutions[row.operation.source] = action
            index += 1
            row = self._list_box.get_row_at_index(index)
        
        self._update_status()
    
    def _update_status(self) -> None:
        """更新状态"""
        skip_count = sum(1 for a in self._resolutions.values() if a == ConflictAction.SKIP)
        rename_count = sum(1 for a in self._resolutions.values() if a == ConflictAction.RENAME)
        overwrite_count = sum(1 for a in self._resolutions.values() if a == ConflictAction.OVERWRITE)
        
        self._status_label.set_text(
            f"跳过: {skip_count} | 重命名: {rename_count} | 覆盖: {overwrite_count}"
        )
    
    def _on_cancel(self) -> None:
        """取消"""
        # 所有设为取消
        for key in self._resolutions:
            self._resolutions[key] = ConflictAction.CANCEL
        
        if self._on_resolve:
            self._on_resolve(self._resolutions)
        
        self.close()
    
    def _on_apply(self, button: Gtk.Button) -> None:
        """应用"""
        if self._on_resolve:
            self._on_resolve(self._resolutions)
        
        self.close()
    
    def get_resolutions(self) -> Dict[str, ConflictAction]:
        """获取解决方案"""
        return self._resolutions.copy()


def show_conflict_dialog(
    parent: Optional[Gtk.Window],
    operation: RenameOperation,
    on_resolve: Optional[Callable[[ConflictAction, str], None]] = None,
) -> ConflictResolutionDialog:
    """
    显示单个冲突解决对话框
    
    Args:
        parent: 父窗口
        operation: 冲突的重命名操作
        on_resolve: 解决回调 (action, new_name) -> None
        
    Returns:
        ConflictResolutionDialog 实例
    """
    dialog = ConflictResolutionDialog(
        parent=parent,
        operation=operation,
        on_resolve=on_resolve,
    )
    dialog.present()
    return dialog


def show_batch_conflict_dialog(
    parent: Optional[Gtk.Window],
    conflicts: List[RenameOperation],
    on_resolve: Optional[Callable[[Dict[str, ConflictAction]], None]] = None,
) -> BatchConflictResolutionDialog:
    """
    显示批量冲突解决对话框
    
    Args:
        parent: 父窗口
        conflicts: 冲突的重命名操作列表
        on_resolve: 解决回调 {source_path: action} -> None
        
    Returns:
        BatchConflictResolutionDialog 实例
    """
    dialog = BatchConflictResolutionDialog(
        parent=parent,
        conflicts=conflicts,
        on_resolve=on_resolve,
    )
    dialog.present()
    return dialog
