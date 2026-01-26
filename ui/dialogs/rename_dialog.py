"""
Rename Dialog

单文件重命名对话框，支持UCS命名预览和验证。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Pango

from transcriptionist_v3.application.naming_manager import (
    UCSParser,
    UCSBuilder,
    NamingValidator,
    ValidationResult,
    TemplateManager,
    NamingTemplate,
    BUILTIN_TEMPLATES,
)
from transcriptionist_v3.domain.models import UCSComponents

logger = logging.getLogger(__name__)


class RenameDialog(Adw.Window):
    """
    重命名对话框
    
    功能：
    - 单文件重命名
    - UCS组件编辑
    - 实时预览
    - 验证反馈
    - 模板应用
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        file_path: str = "",
        on_rename: Optional[Callable[[str, str], None]] = None,
    ):
        super().__init__()
        
        self._file_path = file_path
        self._on_rename = on_rename
        self._parser = UCSParser()
        self._builder = UCSBuilder()
        self._validator = NamingValidator()
        self._template_manager = TemplateManager.instance()
        
        # 解析当前文件名
        self._original_name = Path(file_path).name if file_path else ""
        self._parse_result = self._parser.parse(self._original_name) if self._original_name else None
        
        # 设置窗口属性
        self.set_title("重命名")
        self.set_default_size(500, 600)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)
        
        self._build_ui()
        self._populate_fields()
        self._update_preview()
    
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
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)
        
        # 确认按钮
        self._confirm_btn = Gtk.Button(label="重命名")
        self._confirm_btn.add_css_class("suggested-action")
        self._confirm_btn.connect("clicked", self._on_confirm)
        header.pack_end(self._confirm_btn)
        
        # 标题
        title_label = Gtk.Label(label="重命名文件")
        title_label.add_css_class("title")
        header.set_title_widget(title_label)
        
        main_box.append(header)
        
        # 滚动容器
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        main_box.append(scrolled)
        
        # 内容容器
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(24)
        scrolled.set_child(content_box)
        
        # 原始文件名显示
        self._create_original_section(content_box)
        
        # 模板选择
        self._create_template_section(content_box)
        
        # UCS组件编辑
        self._create_ucs_section(content_box)
        
        # 自定义名称输入
        self._create_custom_section(content_box)
        
        # 预览区域
        self._create_preview_section(content_box)
    
    def _create_original_section(self, parent: Gtk.Box) -> None:
        """创建原始文件名区域"""
        group = Adw.PreferencesGroup()
        group.set_title("原始文件名")
        
        row = Adw.ActionRow()
        row.set_title(self._original_name or "未选择文件")
        row.set_subtitle(str(Path(self._file_path).parent) if self._file_path else "")
        row.add_css_class("property")
        
        # 文件图标
        icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon.set_pixel_size(24)
        row.add_prefix(icon)
        
        group.add(row)
        parent.append(group)
    
    def _create_template_section(self, parent: Gtk.Box) -> None:
        """创建模板选择区域"""
        group = Adw.PreferencesGroup()
        group.set_title("命名模板")
        
        # 模板下拉框
        row = Adw.ComboRow()
        row.set_title("选择模板")
        row.set_subtitle("使用预设模板快速命名")
        
        # 创建模板列表
        templates = self._template_manager.get_all_templates()
        model = Gtk.StringList()
        model.append("自定义")
        for template in templates:
            model.append(template.name)
        
        row.set_model(model)
        row.set_selected(0)
        row.connect("notify::selected", self._on_template_changed)
        self._template_row = row
        
        group.add(row)
        parent.append(group)
    
    def _create_ucs_section(self, parent: Gtk.Box) -> None:
        """创建UCS组件编辑区域"""
        group = Adw.PreferencesGroup()
        group.set_title("UCS组件")
        group.set_description("编辑UCS命名规范的各个组件")
        
        # 类别
        self._category_row = Adw.EntryRow()
        self._category_row.set_title("类别 (Category)")
        self._category_row.connect("changed", self._on_field_changed)
        group.add(self._category_row)
        
        # 子类别
        self._subcategory_row = Adw.EntryRow()
        self._subcategory_row.set_title("子类别 (Subcategory)")
        self._subcategory_row.connect("changed", self._on_field_changed)
        group.add(self._subcategory_row)
        
        # 描述符
        self._descriptor_row = Adw.EntryRow()
        self._descriptor_row.set_title("描述符 (Descriptor)")
        self._descriptor_row.connect("changed", self._on_field_changed)
        group.add(self._descriptor_row)
        
        # 变体号
        self._variation_row = Adw.EntryRow()
        self._variation_row.set_title("变体号 (Variation)")
        self._variation_row.connect("changed", self._on_field_changed)
        group.add(self._variation_row)
        
        # 版本号
        self._version_row = Adw.EntryRow()
        self._version_row.set_title("版本号 (Version)")
        self._version_row.connect("changed", self._on_field_changed)
        group.add(self._version_row)
        
        parent.append(group)
        self._ucs_group = group

    def _create_custom_section(self, parent: Gtk.Box) -> None:
        """创建自定义名称输入区域"""
        group = Adw.PreferencesGroup()
        group.set_title("自定义名称")
        group.set_description("直接输入新文件名（不含扩展名）")
        
        self._custom_entry = Adw.EntryRow()
        self._custom_entry.set_title("新文件名")
        self._custom_entry.connect("changed", self._on_custom_changed)
        group.add(self._custom_entry)
        
        parent.append(group)
        self._custom_group = group
    
    def _create_preview_section(self, parent: Gtk.Box) -> None:
        """创建预览区域"""
        group = Adw.PreferencesGroup()
        group.set_title("预览")
        
        # 新文件名预览
        self._preview_row = Adw.ActionRow()
        self._preview_row.set_title("新文件名")
        self._preview_row.set_subtitle("...")
        self._preview_row.add_css_class("property")
        
        # 复制按钮
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.set_valign(Gtk.Align.CENTER)
        copy_btn.set_tooltip_text("复制文件名")
        copy_btn.add_css_class("flat")
        copy_btn.connect("clicked", self._on_copy_preview)
        self._preview_row.add_suffix(copy_btn)
        
        group.add(self._preview_row)
        
        # 验证状态
        self._validation_row = Adw.ActionRow()
        self._validation_row.set_title("验证状态")
        self._validation_row.set_subtitle("检查中...")
        
        self._validation_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self._validation_icon.set_pixel_size(16)
        self._validation_row.add_prefix(self._validation_icon)
        
        group.add(self._validation_row)
        
        parent.append(group)
    
    def _populate_fields(self) -> None:
        """填充字段值"""
        if self._parse_result and self._parse_result.success and self._parse_result.components:
            comp = self._parse_result.components
            self._category_row.set_text(comp.category)
            self._subcategory_row.set_text(comp.subcategory)
            self._descriptor_row.set_text(comp.descriptor)
            self._variation_row.set_text(comp.variation)
            self._version_row.set_text(comp.version)
        
        # 设置自定义名称为原始文件名（不含扩展名）
        if self._original_name:
            stem = Path(self._original_name).stem
            self._custom_entry.set_text(stem)
    
    def _on_template_changed(self, row: Adw.ComboRow, pspec) -> None:
        """模板选择变化"""
        selected = row.get_selected()
        
        if selected == 0:
            # 自定义模式
            self._ucs_group.set_sensitive(True)
            self._custom_group.set_sensitive(True)
        else:
            # 使用模板
            templates = self._template_manager.get_all_templates()
            if selected - 1 < len(templates):
                template = templates[selected - 1]
                self._apply_template(template)
        
        self._update_preview()
    
    def _apply_template(self, template: NamingTemplate) -> None:
        """应用模板"""
        # 创建上下文
        context = self._template_manager.create_context(
            filename=self._original_name,
            ucs_components=self._get_ucs_dict(),
            index=1,
        )
        
        # 格式化
        result = template.format(context)
        
        # 更新自定义名称
        stem = Path(result).stem if "." in result else result
        self._custom_entry.set_text(stem)
    
    def _on_field_changed(self, entry: Adw.EntryRow) -> None:
        """UCS字段变化"""
        self._update_preview()
    
    def _on_custom_changed(self, entry: Adw.EntryRow) -> None:
        """自定义名称变化"""
        self._update_preview()
    
    def _get_ucs_dict(self) -> Dict[str, str]:
        """获取UCS组件字典"""
        return {
            "category": self._category_row.get_text(),
            "subcategory": self._subcategory_row.get_text(),
            "descriptor": self._descriptor_row.get_text(),
            "variation": self._variation_row.get_text(),
            "version": self._version_row.get_text(),
        }
    
    def _get_new_filename(self) -> str:
        """获取新文件名"""
        # 获取扩展名
        ext = Path(self._original_name).suffix if self._original_name else ".wav"
        
        # 检查模板选择
        selected = self._template_row.get_selected()
        
        if selected == 0:
            # 自定义模式 - 使用自定义输入
            custom_name = self._custom_entry.get_text().strip()
            if custom_name:
                return f"{custom_name}{ext}"
            
            # 如果自定义为空，尝试从UCS组件构建
            try:
                self._builder.reset()
                self._builder.category(self._category_row.get_text())
                self._builder.subcategory(self._subcategory_row.get_text())
                self._builder.descriptor(self._descriptor_row.get_text())
                self._builder.variation(self._variation_row.get_text())
                self._builder.version(self._version_row.get_text())
                self._builder.extension(ext.lstrip("."))
                return self._builder.preview()
            except Exception:
                return self._original_name
        else:
            # 模板模式
            custom_name = self._custom_entry.get_text().strip()
            return f"{custom_name}{ext}" if custom_name else self._original_name
    
    def _update_preview(self) -> None:
        """更新预览"""
        new_name = self._get_new_filename()
        self._preview_row.set_subtitle(new_name)
        
        # 验证
        target_dir = str(Path(self._file_path).parent) if self._file_path else None
        result = self._validator.validate(new_name, target_dir=target_dir)
        
        self._update_validation_status(result, new_name)
    
    def _update_validation_status(self, result: ValidationResult, new_name: str) -> None:
        """更新验证状态显示"""
        if result.is_valid:
            self._validation_icon.set_from_icon_name("emblem-ok-symbolic")
            self._validation_icon.remove_css_class("error")
            self._validation_icon.add_css_class("success")
            
            if new_name == self._original_name:
                self._validation_row.set_subtitle("文件名未更改")
                self._confirm_btn.set_sensitive(False)
            else:
                self._validation_row.set_subtitle("✓ 文件名有效")
                self._confirm_btn.set_sensitive(True)
        else:
            self._validation_icon.set_from_icon_name("dialog-warning-symbolic")
            self._validation_icon.remove_css_class("success")
            self._validation_icon.add_css_class("error")
            
            errors = "; ".join(result.error_messages)
            self._validation_row.set_subtitle(f"✗ {errors}")
            self._confirm_btn.set_sensitive(False)
    
    def _on_copy_preview(self, button: Gtk.Button) -> None:
        """复制预览文件名"""
        new_name = self._get_new_filename()
        clipboard = self.get_clipboard()
        clipboard.set(new_name)
    
    def _on_confirm(self, button: Gtk.Button) -> None:
        """确认重命名"""
        new_name = self._get_new_filename()
        
        if self._on_rename and new_name != self._original_name:
            self._on_rename(self._file_path, new_name)
        
        self.close()
    
    def get_new_filename(self) -> str:
        """获取新文件名（供外部调用）"""
        return self._get_new_filename()


def show_rename_dialog(
    parent: Optional[Gtk.Window],
    file_path: str,
    on_rename: Optional[Callable[[str, str], None]] = None,
) -> RenameDialog:
    """
    显示重命名对话框
    
    Args:
        parent: 父窗口
        file_path: 文件路径
        on_rename: 重命名回调函数 (old_path, new_name) -> None
        
    Returns:
        RenameDialog 实例
    """
    dialog = RenameDialog(parent=parent, file_path=file_path, on_rename=on_rename)
    dialog.present()
    return dialog
