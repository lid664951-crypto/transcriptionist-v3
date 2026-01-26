"""
Template Editor Dialog

命名模板编辑器，支持创建、编辑和测试自定义命名模板。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Pango

from transcriptionist_v3.application.naming_manager import (
    NamingTemplate,
    TemplateManager,
    TemplateVariable,
    BUILTIN_TEMPLATES,
)

logger = logging.getLogger(__name__)


class TemplateEditorDialog(Adw.Window):
    """
    模板编辑器对话框
    
    功能：
    - 创建新模板
    - 编辑现有模板
    - 变量插入
    - 实时预览
    - 语法帮助
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        template: Optional[NamingTemplate] = None,
        on_save: Optional[Callable[[NamingTemplate], None]] = None,
    ):
        super().__init__()
        
        self._template = template
        self._on_save = on_save
        self._template_manager = TemplateManager.instance()
        self._is_new = template is None
        
        # 设置窗口属性
        self.set_title("编辑模板" if template else "新建模板")
        self.set_default_size(600, 700)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)
        
        self._build_ui()
        self._populate_fields()
    
    def _build_ui(self) -> None:
        """构建用户界面"""
        # 主容器
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # 标题栏
        header = self._create_header()
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
        
        # 基本信息
        self._create_basic_section(content_box)
        
        # 模板模式
        self._create_pattern_section(content_box)
        
        # 变量参考
        self._create_variables_section(content_box)
        
        # 预览
        self._create_preview_section(content_box)
        
        # 语法帮助
        self._create_help_section(content_box)
    
    def _create_header(self) -> Gtk.HeaderBar:
        """创建标题栏"""
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        
        # 取消按钮
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)
        
        # 保存按钮
        self._save_btn = Gtk.Button(label="保存")
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self._save_btn)
        
        # 标题
        title = "编辑模板" if self._template else "新建模板"
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("title")
        header.set_title_widget(title_label)
        
        return header
    
    def _create_basic_section(self, parent: Gtk.Box) -> None:
        """创建基本信息区域"""
        group = Adw.PreferencesGroup()
        group.set_title("基本信息")
        
        # 模板名称
        self._name_row = Adw.EntryRow()
        self._name_row.set_title("模板名称")
        self._name_row.connect("changed", self._on_field_changed)
        group.add(self._name_row)
        
        # 模板描述
        self._desc_row = Adw.EntryRow()
        self._desc_row.set_title("描述")
        group.add(self._desc_row)
        
        parent.append(group)
    
    def _create_pattern_section(self, parent: Gtk.Box) -> None:
        """创建模板模式区域"""
        group = Adw.PreferencesGroup()
        group.set_title("模板模式")
        group.set_description("使用 {变量名} 插入变量，使用 [条件|真值|假值] 进行条件判断")
        
        # 模式输入框
        pattern_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # 文本视图
        self._pattern_view = Gtk.TextView()
        self._pattern_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._pattern_view.set_monospace(True)
        self._pattern_view.set_left_margin(8)
        self._pattern_view.set_right_margin(8)
        self._pattern_view.set_top_margin(8)
        self._pattern_view.set_bottom_margin(8)
        self._pattern_view.get_buffer().connect("changed", self._on_pattern_changed)
        
        # 滚动容器
        pattern_scroll = Gtk.ScrolledWindow()
        pattern_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        pattern_scroll.set_min_content_height(80)
        pattern_scroll.set_max_content_height(120)
        pattern_scroll.set_child(self._pattern_view)
        pattern_scroll.add_css_class("card")
        
        pattern_box.append(pattern_scroll)
        
        # 快速插入按钮
        insert_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        insert_box.set_margin_top(8)
        
        insert_label = Gtk.Label(label="快速插入:")
        insert_label.add_css_class("dim-label")
        insert_box.append(insert_label)
        
        # 常用变量按钮
        common_vars = [
            ("类别", "category"),
            ("子类别", "subcategory"),
            ("描述符", "descriptor"),
            ("序号", "index_padded"),
            ("文件名", "filename"),
            ("扩展名", "extension"),
        ]
        
        for label, var in common_vars:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.add_css_class("pill")
            btn.connect("clicked", self._on_insert_variable, var)
            insert_box.append(btn)
        
        pattern_box.append(insert_box)
        
        # 将 pattern_box 包装在一个 ActionRow 中
        row = Adw.ActionRow()
        row.set_title("模式字符串")
        row.set_activatable(False)
        
        # 使用自定义布局
        custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        custom_box.set_margin_top(8)
        custom_box.set_margin_bottom(8)
        custom_box.append(pattern_box)
        
        group.add(row)
        parent.append(group)
        parent.append(pattern_box)

    def _create_variables_section(self, parent: Gtk.Box) -> None:
        """创建变量参考区域"""
        # 使用展开器
        expander = Gtk.Expander()
        expander.set_label("可用变量")
        expander.set_margin_top(8)
        
        # 变量列表
        var_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        var_box.set_margin_start(16)
        var_box.set_margin_top(8)
        
        # 变量分组
        variable_groups = {
            "文件信息": [
                ("filename", "原文件名（不含扩展名）"),
                ("extension", "扩展名"),
                ("dirname", "目录名"),
            ],
            "UCS组件": [
                ("category", "类别"),
                ("subcategory", "子类别"),
                ("descriptor", "描述符"),
                ("variation", "变体号"),
                ("version", "版本号"),
            ],
            "序号": [
                ("index", "序号"),
                ("index_padded", "补零序号"),
            ],
            "日期时间": [
                ("date", "当前日期 (YYYYMMDD)"),
                ("time", "当前时间 (HHMMSS)"),
                ("datetime", "日期时间"),
            ],
            "其他": [
                ("translated", "翻译后的名称"),
            ],
        }
        
        for group_name, variables in variable_groups.items():
            # 组标题
            group_label = Gtk.Label(label=group_name)
            group_label.add_css_class("heading")
            group_label.set_halign(Gtk.Align.START)
            group_label.set_margin_top(8)
            var_box.append(group_label)
            
            # 变量列表
            for var_name, var_desc in variables:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                
                # 变量名（可点击）
                var_btn = Gtk.Button(label=f"{{{var_name}}}")
                var_btn.add_css_class("flat")
                var_btn.set_tooltip_text(f"点击插入 {{{var_name}}}")
                var_btn.connect("clicked", self._on_insert_variable, var_name)
                row.append(var_btn)
                
                # 描述
                desc_label = Gtk.Label(label=var_desc)
                desc_label.add_css_class("dim-label")
                desc_label.set_halign(Gtk.Align.START)
                row.append(desc_label)
                
                var_box.append(row)
        
        expander.set_child(var_box)
        parent.append(expander)
    
    def _create_preview_section(self, parent: Gtk.Box) -> None:
        """创建预览区域"""
        group = Adw.PreferencesGroup()
        group.set_title("预览")
        group.set_description("使用示例数据预览模板效果")
        
        # 示例文件名输入
        self._sample_row = Adw.EntryRow()
        self._sample_row.set_title("示例文件名")
        self._sample_row.set_text("Explosion_Large_Debris_01_v1.wav")
        self._sample_row.connect("changed", self._update_preview)
        group.add(self._sample_row)
        
        # 预览结果
        self._preview_row = Adw.ActionRow()
        self._preview_row.set_title("预览结果")
        self._preview_row.set_subtitle("...")
        self._preview_row.add_css_class("property")
        group.add(self._preview_row)
        
        parent.append(group)
    
    def _create_help_section(self, parent: Gtk.Box) -> None:
        """创建语法帮助区域"""
        expander = Gtk.Expander()
        expander.set_label("语法帮助")
        expander.set_margin_top(8)
        
        help_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        help_box.set_margin_start(16)
        help_box.set_margin_top(8)
        
        help_items = [
            ("变量替换", "{变量名}", "例如: {category}_{subcategory}"),
            ("带默认值", "{变量名|默认值}", "例如: {descriptor|Unknown}"),
            ("格式化", "{变量名:格式}", "例如: {index:03} 补零3位"),
            ("条件表达式", "[条件|真值|假值]", "例如: [descriptor|_{descriptor}|]"),
            ("大小写", "{变量名:upper/lower/title}", "例如: {category:upper}"),
        ]
        
        for title, syntax, example in help_items:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            
            title_label = Gtk.Label(label=title)
            title_label.add_css_class("heading")
            title_label.set_halign(Gtk.Align.START)
            row.append(title_label)
            
            syntax_label = Gtk.Label(label=f"语法: {syntax}")
            syntax_label.set_halign(Gtk.Align.START)
            syntax_label.add_css_class("monospace")
            row.append(syntax_label)
            
            example_label = Gtk.Label(label=example)
            example_label.set_halign(Gtk.Align.START)
            example_label.add_css_class("dim-label")
            row.append(example_label)
            
            help_box.append(row)
        
        expander.set_child(help_box)
        parent.append(expander)
    
    def _populate_fields(self) -> None:
        """填充字段值"""
        if self._template:
            self._name_row.set_text(self._template.name)
            self._desc_row.set_text(self._template.description)
            self._pattern_view.get_buffer().set_text(self._template.pattern)
        else:
            # 默认模板
            self._name_row.set_text("新模板")
            self._pattern_view.get_buffer().set_text("{category}_{subcategory}_{descriptor}.{extension}")
        
        self._update_preview()
    
    def _on_field_changed(self, entry: Adw.EntryRow) -> None:
        """字段变化"""
        self._validate_form()
    
    def _on_pattern_changed(self, buffer: Gtk.TextBuffer) -> None:
        """模式变化"""
        self._update_preview()
        self._validate_form()
    
    def _on_insert_variable(self, button: Gtk.Button, var_name: str) -> None:
        """插入变量"""
        buffer = self._pattern_view.get_buffer()
        buffer.insert_at_cursor(f"{{{var_name}}}")
        self._pattern_view.grab_focus()
    
    def _get_pattern(self) -> str:
        """获取模式字符串"""
        buffer = self._pattern_view.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, False)
    
    def _update_preview(self, *args) -> None:
        """更新预览"""
        pattern = self._get_pattern()
        sample_filename = self._sample_row.get_text()
        
        if not pattern or not sample_filename:
            self._preview_row.set_subtitle("...")
            return
        
        # 创建临时模板
        temp_template = NamingTemplate(
            id="preview",
            name="Preview",
            pattern=pattern,
        )
        
        # 解析示例文件名
        from transcriptionist_v3.application.naming_manager import UCSParser
        parser = UCSParser()
        parse_result = parser.parse(sample_filename)
        
        ucs_components = {}
        if parse_result.success and parse_result.components:
            ucs_components = parse_result.components.to_dict()
        
        # 创建上下文
        context = self._template_manager.create_context(
            filename=sample_filename,
            ucs_components=ucs_components,
            index=1,
        )
        
        try:
            result = temp_template.format(context)
            self._preview_row.set_subtitle(result)
            self._preview_row.remove_css_class("error")
        except Exception as e:
            self._preview_row.set_subtitle(f"错误: {e}")
            self._preview_row.add_css_class("error")
    
    def _validate_form(self) -> bool:
        """验证表单"""
        name = self._name_row.get_text().strip()
        pattern = self._get_pattern().strip()
        
        is_valid = bool(name and pattern)
        self._save_btn.set_sensitive(is_valid)
        
        return is_valid
    
    def _on_save_clicked(self, button: Gtk.Button) -> None:
        """保存按钮点击"""
        if not self._validate_form():
            return
        
        name = self._name_row.get_text().strip()
        description = self._desc_row.get_text().strip()
        pattern = self._get_pattern().strip()
        
        # 创建或更新模板
        if self._template and not self._template.is_builtin:
            # 更新现有模板
            template = NamingTemplate(
                id=self._template.id,
                name=name,
                pattern=pattern,
                description=description,
                category="user",
                is_builtin=False,
            )
            self._template_manager.update_template(template)
        else:
            # 创建新模板
            template_id = f"user_{uuid.uuid4().hex[:8]}"
            template = NamingTemplate(
                id=template_id,
                name=name,
                pattern=pattern,
                description=description,
                category="user",
                is_builtin=False,
            )
            self._template_manager.add_template(template)
        
        # 回调
        if self._on_save:
            self._on_save(template)
        
        self.close()
    
    def get_template(self) -> Optional[NamingTemplate]:
        """获取编辑后的模板"""
        if not self._validate_form():
            return None
        
        name = self._name_row.get_text().strip()
        description = self._desc_row.get_text().strip()
        pattern = self._get_pattern().strip()
        
        template_id = self._template.id if self._template else f"user_{uuid.uuid4().hex[:8]}"
        
        return NamingTemplate(
            id=template_id,
            name=name,
            pattern=pattern,
            description=description,
            category="user",
            is_builtin=False,
        )


class TemplateListDialog(Adw.Window):
    """
    模板列表对话框
    
    管理所有命名模板，支持查看、编辑、删除。
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        on_select: Optional[Callable[[NamingTemplate], None]] = None,
    ):
        super().__init__()
        
        self._on_select = on_select
        self._template_manager = TemplateManager.instance()
        
        # 设置窗口属性
        self.set_title("命名模板")
        self.set_default_size(500, 500)
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
        header.set_show_title_buttons(True)
        
        # 新建按钮
        new_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        new_btn.set_tooltip_text("新建模板")
        new_btn.connect("clicked", self._on_new_template)
        header.pack_start(new_btn)
        
        # 标题
        title_label = Gtk.Label(label="命名模板")
        title_label.add_css_class("title")
        header.set_title_widget(title_label)
        
        main_box.append(header)
        
        # 模板列表
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        self._list_box.set_margin_top(16)
        self._list_box.set_margin_bottom(16)
        self._list_box.connect("row-activated", self._on_row_activated)
        
        scrolled.set_child(self._list_box)
        main_box.append(scrolled)
    
    def _populate_list(self) -> None:
        """填充模板列表"""
        # 清空列表
        while True:
            row = self._list_box.get_row_at_index(0)
            if row:
                self._list_box.remove(row)
            else:
                break
        
        # 添加内置模板
        builtin_templates = self._template_manager.get_builtin_templates()
        if builtin_templates:
            # 分组标题
            header = Gtk.Label(label="内置模板")
            header.add_css_class("heading")
            header.set_halign(Gtk.Align.START)
            header.set_margin_start(8)
            header.set_margin_top(8)
            header.set_margin_bottom(4)
            self._list_box.append(header)
            
            for template in builtin_templates:
                row = self._create_template_row(template)
                self._list_box.append(row)
        
        # 添加用户模板
        user_templates = self._template_manager.get_user_templates()
        if user_templates:
            # 分组标题
            header = Gtk.Label(label="自定义模板")
            header.add_css_class("heading")
            header.set_halign(Gtk.Align.START)
            header.set_margin_start(8)
            header.set_margin_top(16)
            header.set_margin_bottom(4)
            self._list_box.append(header)
            
            for template in user_templates:
                row = self._create_template_row(template)
                self._list_box.append(row)
    
    def _create_template_row(self, template: NamingTemplate) -> Adw.ActionRow:
        """创建模板行"""
        row = Adw.ActionRow()
        row.set_title(template.name)
        row.set_subtitle(template.description or template.pattern)
        row.template = template  # 存储模板引用
        
        # 图标
        if template.is_builtin:
            icon = Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        else:
            icon = Gtk.Image.new_from_icon_name("document-edit-symbolic")
        icon.set_pixel_size(16)
        row.add_prefix(icon)
        
        # 操作按钮
        if not template.is_builtin:
            # 编辑按钮
            edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic")
            edit_btn.set_valign(Gtk.Align.CENTER)
            edit_btn.add_css_class("flat")
            edit_btn.set_tooltip_text("编辑")
            edit_btn.connect("clicked", self._on_edit_template, template)
            row.add_suffix(edit_btn)
            
            # 删除按钮
            delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            delete_btn.set_valign(Gtk.Align.CENTER)
            delete_btn.add_css_class("flat")
            delete_btn.set_tooltip_text("删除")
            delete_btn.connect("clicked", self._on_delete_template, template)
            row.add_suffix(delete_btn)
        
        # 选择箭头
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.set_pixel_size(16)
        row.add_suffix(arrow)
        
        row.set_activatable(True)
        
        return row
    
    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """行激活"""
        if hasattr(row, 'template') and self._on_select:
            self._on_select(row.template)
            self.close()
    
    def _on_new_template(self, button: Gtk.Button) -> None:
        """新建模板"""
        dialog = TemplateEditorDialog(
            parent=self,
            on_save=lambda t: self._populate_list(),
        )
        dialog.present()
    
    def _on_edit_template(self, button: Gtk.Button, template: NamingTemplate) -> None:
        """编辑模板"""
        dialog = TemplateEditorDialog(
            parent=self,
            template=template,
            on_save=lambda t: self._populate_list(),
        )
        dialog.present()
    
    def _on_delete_template(self, button: Gtk.Button, template: NamingTemplate) -> None:
        """删除模板"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="删除模板",
            body=f"确定要删除模板 \"{template.name}\" 吗？此操作无法撤销。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "删除")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_delete_response, template)
        dialog.present()
    
    def _on_delete_response(self, dialog: Adw.MessageDialog, response: str, template: NamingTemplate) -> None:
        """删除确认响应"""
        if response == "delete":
            self._template_manager.remove_template(template.id)
            self._populate_list()


def show_template_editor(
    parent: Optional[Gtk.Window],
    template: Optional[NamingTemplate] = None,
    on_save: Optional[Callable[[NamingTemplate], None]] = None,
) -> TemplateEditorDialog:
    """
    显示模板编辑器
    
    Args:
        parent: 父窗口
        template: 要编辑的模板（None表示新建）
        on_save: 保存回调
        
    Returns:
        TemplateEditorDialog 实例
    """
    dialog = TemplateEditorDialog(parent=parent, template=template, on_save=on_save)
    dialog.present()
    return dialog


def show_template_list(
    parent: Optional[Gtk.Window],
    on_select: Optional[Callable[[NamingTemplate], None]] = None,
) -> TemplateListDialog:
    """
    显示模板列表
    
    Args:
        parent: 父窗口
        on_select: 选择回调
        
    Returns:
        TemplateListDialog 实例
    """
    dialog = TemplateListDialog(parent=parent, on_select=on_select)
    dialog.present()
    return dialog
