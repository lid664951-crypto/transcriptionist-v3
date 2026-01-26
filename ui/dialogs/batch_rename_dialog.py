"""
Batch Rename Dialog

批量重命名对话框，支持模板应用、预览和冲突检测。
集成了 Quod Libet 的成熟过滤器功能。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Gio, Pango, GObject

from transcriptionist_v3.application.naming_manager import (
    BatchRenameManager,
    RenameOperation,
    RenameResult,
    ConflictResolution,
    TemplateManager,
    NamingTemplate,
    UCSParser,
    BUILTIN_TEMPLATES,
)
from transcriptionist_v3.lib.quodlibet_adapter.rename_adapter import (
    FilterChain,
    SpacesToUnderscores,
    StripWindowsIncompat,
    StripDiacriticals,
    Lowercase,
)

logger = logging.getLogger(__name__)


class BatchRenameDialog(Adw.Window):
    """
    批量重命名对话框
    
    功能：
    - 多文件批量重命名
    - 模板选择和应用
    - 实时预览
    - 冲突检测和解决
    - 进度显示
    """
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        files: Optional[List[str]] = None,
        on_complete: Optional[Callable[[RenameResult], None]] = None,
    ):
        super().__init__()
        
        self._files = files or []
        self._on_complete = on_complete
        
        # 获取数据库会话
        from ...infrastructure.database.connection import get_session
        db_session = get_session()
        
        self._rename_manager = BatchRenameManager(db_session=db_session)
        self._template_manager = TemplateManager.instance()
        self._parser = UCSParser()
        
        # 预览数据
        self._preview_operations: List[RenameOperation] = []
        self._conflicts: List[RenameOperation] = []
        
        # 设置窗口属性
        self.set_title("批量重命名")
        self.set_default_size(800, 600)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)
        
        self._build_ui()
        self._populate_file_list()
    
    def _build_ui(self) -> None:
        """构建用户界面"""
        # 主容器
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # 标题栏
        header = self._create_header()
        main_box.append(header)
        
        # 工具栏
        toolbar = self._create_toolbar()
        main_box.append(toolbar)
        
        # 主内容区域（分割视图）
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(400)
        main_box.append(paned)
        
        # 左侧：文件列表和预览
        left_box = self._create_file_list_panel()
        paned.set_start_child(left_box)
        
        # 右侧：设置面板
        right_box = self._create_settings_panel()
        paned.set_end_child(right_box)
        
        # 底部状态栏
        status_bar = self._create_status_bar()
        main_box.append(status_bar)
    
    def _create_header(self) -> Gtk.HeaderBar:
        """创建标题栏"""
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        
        # 取消按钮
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)
        
        # 执行按钮
        self._execute_btn = Gtk.Button(label="执行重命名")
        self._execute_btn.add_css_class("suggested-action")
        self._execute_btn.connect("clicked", self._on_execute)
        self._execute_btn.set_sensitive(False)
        header.pack_end(self._execute_btn)
        
        # 预览按钮
        preview_btn = Gtk.Button(label="预览")
        preview_btn.connect("clicked", self._on_preview)
        header.pack_end(preview_btn)
        
        # 标题
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label(label="批量重命名")
        title_label.add_css_class("title")
        title_box.append(title_label)
        
        self._subtitle_label = Gtk.Label(label=f"已选择 {len(self._files)} 个文件")
        self._subtitle_label.add_css_class("subtitle")
        title_box.append(self._subtitle_label)
        
        header.set_title_widget(title_box)
        
        return header
    
    def _create_toolbar(self) -> Gtk.Box:
        """创建工具栏"""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(8)
        toolbar.set_margin_bottom(8)
        toolbar.add_css_class("toolbar")
        
        # 模板选择
        template_label = Gtk.Label(label="模板:")
        toolbar.append(template_label)
        
        self._template_dropdown = Gtk.DropDown()
        templates = self._template_manager.get_all_templates()
        model = Gtk.StringList()
        for template in templates:
            model.append(template.name)
        self._template_dropdown.set_model(model)
        self._template_dropdown.connect("notify::selected", self._on_template_changed)
        toolbar.append(self._template_dropdown)
        
        # 分隔
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        # 冲突解决策略
        conflict_label = Gtk.Label(label="冲突处理:")
        toolbar.append(conflict_label)
        
        self._conflict_dropdown = Gtk.DropDown()
        conflict_model = Gtk.StringList()
        conflict_model.append("跳过")
        conflict_model.append("自动重命名")
        conflict_model.append("覆盖")
        self._conflict_dropdown.set_model(conflict_model)
        self._conflict_dropdown.set_selected(0)
        toolbar.append(self._conflict_dropdown)
        
        # 弹性空间
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)
        
        # 全选/取消全选
        select_all_btn = Gtk.Button(label="全选")
        select_all_btn.connect("clicked", self._on_select_all)
        toolbar.append(select_all_btn)
        
        return toolbar

    def _create_file_list_panel(self) -> Gtk.Box:
        """创建文件列表面板"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_size_request(350, -1)
        
        # 标题
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title_box.set_margin_start(12)
        title_box.set_margin_end(12)
        title_box.set_margin_top(8)
        title_box.set_margin_bottom(8)
        
        title = Gtk.Label(label="文件预览")
        title.add_css_class("heading")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)
        
        box.append(title_box)
        
        # 列表视图
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        # 使用 ColumnView 显示原名和新名
        self._file_list = Gtk.ColumnView()
        self._file_list.add_css_class("data-table")
        
        # 创建数据模型
        self._list_store = Gio.ListStore.new(BatchRenameItem)
        selection = Gtk.MultiSelection.new(self._list_store)
        self._file_list.set_model(selection)
        
        # 原文件名列
        factory1 = Gtk.SignalListItemFactory()
        factory1.connect("setup", self._on_original_setup)
        factory1.connect("bind", self._on_original_bind)
        column1 = Gtk.ColumnViewColumn(title="原文件名", factory=factory1)
        column1.set_expand(True)
        self._file_list.append_column(column1)
        
        # 箭头列
        factory_arrow = Gtk.SignalListItemFactory()
        factory_arrow.connect("setup", self._on_arrow_setup)
        column_arrow = Gtk.ColumnViewColumn(title="", factory=factory_arrow)
        column_arrow.set_fixed_width(30)
        self._file_list.append_column(column_arrow)
        
        # 新文件名列
        factory2 = Gtk.SignalListItemFactory()
        factory2.connect("setup", self._on_new_setup)
        factory2.connect("bind", self._on_new_bind)
        column2 = Gtk.ColumnViewColumn(title="新文件名", factory=factory2)
        column2.set_expand(True)
        self._file_list.append_column(column2)
        
        # 状态列
        factory3 = Gtk.SignalListItemFactory()
        factory3.connect("setup", self._on_status_setup)
        factory3.connect("bind", self._on_status_bind)
        column3 = Gtk.ColumnViewColumn(title="状态", factory=factory3)
        column3.set_fixed_width(80)
        self._file_list.append_column(column3)
        
        scrolled.set_child(self._file_list)
        box.append(scrolled)
        
        return box
    
    def _create_settings_panel(self) -> Gtk.Box:
        """创建设置面板"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_size_request(350, -1)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        
        # 模板设置组
        template_group = Adw.PreferencesGroup()
        template_group.set_title("模板设置")
        
        # 起始序号
        self._start_index_row = Adw.SpinRow.new_with_range(1, 9999, 1)
        self._start_index_row.set_title("起始序号")
        self._start_index_row.set_subtitle("批量命名时的起始编号")
        self._start_index_row.set_value(1)
        self._start_index_row.connect("notify::value", self._on_settings_changed)
        template_group.add(self._start_index_row)
        
        # 序号位数
        self._index_digits_row = Adw.SpinRow.new_with_range(1, 6, 1)
        self._index_digits_row.set_title("序号位数")
        self._index_digits_row.set_subtitle("序号的补零位数")
        self._index_digits_row.set_value(3)
        self._index_digits_row.connect("notify::value", self._on_settings_changed)
        template_group.add(self._index_digits_row)
        
        content.append(template_group)
        
        # UCS设置组
        ucs_group = Adw.PreferencesGroup()
        ucs_group.set_title("UCS组件覆盖")
        ucs_group.set_description("设置后将覆盖所有文件的对应组件")
        
        # 类别覆盖
        self._category_override = Adw.EntryRow()
        self._category_override.set_title("类别 (Category)")
        self._category_override.connect("changed", self._on_settings_changed)
        ucs_group.add(self._category_override)
        
        # 子类别覆盖
        self._subcategory_override = Adw.EntryRow()
        self._subcategory_override.set_title("子类别 (Subcategory)")
        self._subcategory_override.connect("changed", self._on_settings_changed)
        ucs_group.add(self._subcategory_override)
        
        content.append(ucs_group)
        
        # 高级选项组
        advanced_group = Adw.PreferencesGroup()
        advanced_group.set_title("高级选项")
        
        # 保留原扩展名
        self._keep_extension_row = Adw.SwitchRow()
        self._keep_extension_row.set_title("保留原扩展名")
        self._keep_extension_row.set_subtitle("使用原文件的扩展名")
        self._keep_extension_row.set_active(True)
        advanced_group.add(self._keep_extension_row)
        
        # 移动到目标目录
        self._target_dir_row = Adw.ActionRow()
        self._target_dir_row.set_title("目标目录")
        self._target_dir_row.set_subtitle("保持原位置")
        
        choose_dir_btn = Gtk.Button.new_from_icon_name("folder-symbolic")
        choose_dir_btn.set_valign(Gtk.Align.CENTER)
        choose_dir_btn.connect("clicked", self._on_choose_target_dir)
        self._target_dir_row.add_suffix(choose_dir_btn)
        
        clear_dir_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        clear_dir_btn.set_valign(Gtk.Align.CENTER)
        clear_dir_btn.connect("clicked", self._on_clear_target_dir)
        self._target_dir_row.add_suffix(clear_dir_btn)
        
        advanced_group.add(self._target_dir_row)
        
        content.append(advanced_group)
        
        # 过滤器组（从 Quod Libet 移植的成熟功能）
        filter_group = Adw.PreferencesGroup()
        filter_group.set_title("文件名过滤器")
        filter_group.set_description("应用过滤器处理文件名（来自 Quod Libet）")
        
        # 空格转下划线
        self._filter_spaces = Adw.SwitchRow()
        self._filter_spaces.set_title("空格转下划线")
        self._filter_spaces.set_subtitle("将空格替换为下划线")
        self._filter_spaces.connect("notify::active", self._on_settings_changed)
        filter_group.add(self._filter_spaces)
        
        # Windows 兼容
        self._filter_windows = Adw.SwitchRow()
        self._filter_windows.set_title("Windows 兼容")
        self._filter_windows.set_subtitle("移除 Windows 不支持的字符")
        self._filter_windows.set_active(True)  # 默认启用
        self._filter_windows.connect("notify::active", self._on_settings_changed)
        filter_group.add(self._filter_windows)
        
        # 移除变音符号
        self._filter_diacriticals = Adw.SwitchRow()
        self._filter_diacriticals.set_title("移除变音符号")
        self._filter_diacriticals.set_subtitle("移除字符上的变音符号（如 é → e）")
        self._filter_diacriticals.connect("notify::active", self._on_settings_changed)
        filter_group.add(self._filter_diacriticals)
        
        # 转为小写
        self._filter_lowercase = Adw.SwitchRow()
        self._filter_lowercase.set_title("转为小写")
        self._filter_lowercase.set_subtitle("将文件名转换为全小写")
        self._filter_lowercase.connect("notify::active", self._on_settings_changed)
        filter_group.add(self._filter_lowercase)
        
        content.append(filter_group)
        
        scrolled.set_child(content)
        box.append(scrolled)
        
        return box
    
    def _create_status_bar(self) -> Gtk.Box:
        """创建状态栏"""
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_bar.set_margin_start(12)
        status_bar.set_margin_end(12)
        status_bar.set_margin_top(8)
        status_bar.set_margin_bottom(8)
        status_bar.add_css_class("statusbar")
        
        # 状态图标
        self._status_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        status_bar.append(self._status_icon)
        
        # 状态文本
        self._status_label = Gtk.Label(label="请选择模板并预览更改")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)
        status_bar.append(self._status_label)
        
        # 统计信息
        self._stats_label = Gtk.Label(label="")
        self._stats_label.add_css_class("dim-label")
        status_bar.append(self._stats_label)
        
        return status_bar

    # ColumnView factory methods
    def _on_original_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        list_item.set_child(label)
    
    def _on_original_bind(self, factory, list_item):
        label = list_item.get_child()
        item = list_item.get_item()
        label.set_text(item.original_name)
    
    def _on_arrow_setup(self, factory, list_item):
        label = Gtk.Label(label="→")
        label.add_css_class("dim-label")
        list_item.set_child(label)
    
    def _on_new_setup(self, factory, list_item):
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        list_item.set_child(label)
    
    def _on_new_bind(self, factory, list_item):
        label = list_item.get_child()
        item = list_item.get_item()
        label.set_text(item.new_name)
        
        # 根据状态设置样式
        if item.has_conflict:
            label.add_css_class("warning")
        elif item.is_changed:
            label.add_css_class("success")
        else:
            label.remove_css_class("warning")
            label.remove_css_class("success")
    
    def _on_status_setup(self, factory, list_item):
        icon = Gtk.Image()
        icon.set_pixel_size(16)
        list_item.set_child(icon)
    
    def _on_status_bind(self, factory, list_item):
        icon = list_item.get_child()
        item = list_item.get_item()
        
        if item.has_conflict:
            icon.set_from_icon_name("dialog-warning-symbolic")
            icon.set_tooltip_text("存在冲突")
        elif item.is_changed:
            icon.set_from_icon_name("emblem-ok-symbolic")
            icon.set_tooltip_text("将被重命名")
        else:
            icon.set_from_icon_name("content-loading-symbolic")
            icon.set_tooltip_text("未更改")
    
    def _populate_file_list(self) -> None:
        """填充文件列表"""
        self._list_store.remove_all()
        
        for file_path in self._files:
            item = BatchRenameItem(file_path)
            self._list_store.append(item)
    
    def _on_template_changed(self, dropdown, pspec) -> None:
        """模板选择变化"""
        self._update_preview_list()
    
    def _on_settings_changed(self, *args) -> None:
        """设置变化"""
        self._update_preview_list()
    
    def _on_select_all(self, button: Gtk.Button) -> None:
        """全选/取消全选"""
        selection = self._file_list.get_model()
        if isinstance(selection, Gtk.MultiSelection):
            selection.select_all()
    
    def _on_choose_target_dir(self, button: Gtk.Button) -> None:
        """选择目标目录"""
        dialog = Gtk.FileDialog()
        dialog.set_title("选择目标目录")
        dialog.select_folder(self, None, self._on_target_dir_selected)
    
    def _on_target_dir_selected(self, dialog, result) -> None:
        """目标目录选择完成"""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self._target_dir_row.set_subtitle(path)
                self._update_preview_list()
        except Exception as e:
            logger.error(f"选择目录失败: {e}")
    
    def _on_clear_target_dir(self, button: Gtk.Button) -> None:
        """清除目标目录"""
        self._target_dir_row.set_subtitle("保持原位置")
        self._update_preview_list()
    
    def _get_target_dir(self) -> Optional[str]:
        """获取目标目录"""
        subtitle = self._target_dir_row.get_subtitle()
        if subtitle and subtitle != "保持原位置":
            return subtitle
        return None
    
    def _get_conflict_resolution(self) -> ConflictResolution:
        """获取冲突解决策略"""
        selected = self._conflict_dropdown.get_selected()
        if selected == 0:
            return ConflictResolution.SKIP
        elif selected == 1:
            return ConflictResolution.RENAME
        else:
            return ConflictResolution.OVERWRITE
    
    def _update_preview_list(self) -> None:
        """更新预览列表"""
        templates = self._template_manager.get_all_templates()
        selected_idx = self._template_dropdown.get_selected()
        
        if selected_idx >= len(templates):
            return
        
        template = templates[selected_idx]
        start_index = int(self._start_index_row.get_value())
        index_digits = int(self._index_digits_row.get_value())
        
        # 获取覆盖值
        category_override = self._category_override.get_text().strip()
        subcategory_override = self._subcategory_override.get_text().strip()
        
        # 构建过滤器链（来自 Quod Libet 的成熟功能）
        filter_chain = FilterChain()
        if self._filter_spaces.get_active():
            filter_chain.add_filter(SpacesToUnderscores())
        if self._filter_windows.get_active():
            filter_chain.add_filter(StripWindowsIncompat())
        if self._filter_diacriticals.get_active():
            filter_chain.add_filter(StripDiacriticals())
        if self._filter_lowercase.get_active():
            filter_chain.add_filter(Lowercase())
        
        # 更新每个文件的预览
        for i in range(self._list_store.get_n_items()):
            item = self._list_store.get_item(i)
            
            # 解析原文件名
            parse_result = self._parser.parse(item.original_name)
            ucs_components = {}
            
            if parse_result.success and parse_result.components:
                ucs_components = parse_result.components.to_dict()
            
            # 应用覆盖
            if category_override:
                ucs_components["category"] = category_override
            if subcategory_override:
                ucs_components["subcategory"] = subcategory_override
            
            # 创建上下文
            context = self._template_manager.create_context(
                filename=item.original_name,
                ucs_components=ucs_components,
                index=start_index + i,
            )
            
            # 格式化索引
            context["index"] = start_index + i
            context["index_padded"] = str(start_index + i).zfill(index_digits)
            
            # 应用模板
            new_name = template.format(context)
            
            # 保留扩展名
            if self._keep_extension_row.get_active():
                original_ext = Path(item.original_name).suffix
                new_stem = Path(new_name).stem
                new_name = f"{new_stem}{original_ext}"
            
            # 应用过滤器（来自 Quod Libet）
            if filter_chain.filters:
                new_name, _ = filter_chain.apply(item.original_name, new_name)
            
            item.new_name = new_name
            item.is_changed = (new_name != item.original_name)
        
        # 检测冲突
        self._detect_conflicts()
        
        # 刷新列表显示
        # 通过重新设置模型来触发刷新
        selection = self._file_list.get_model()
        self._file_list.set_model(None)
        self._file_list.set_model(selection)
        
        self._update_status()
    
    def _detect_conflicts(self) -> None:
        """检测冲突"""
        target_dir = self._get_target_dir()
        seen_names: Dict[str, int] = {}
        
        for i in range(self._list_store.get_n_items()):
            item = self._list_store.get_item(i)
            item.has_conflict = False
            
            # 检查目标文件是否已存在
            if target_dir:
                target_path = Path(target_dir) / item.new_name
            else:
                target_path = Path(item.file_path).parent / item.new_name
            
            if target_path.exists() and str(target_path) != item.file_path:
                item.has_conflict = True
            
            # 检查批量操作内的重复
            name_lower = item.new_name.lower()
            if name_lower in seen_names:
                item.has_conflict = True
                # 标记之前的项也有冲突
                prev_idx = seen_names[name_lower]
                prev_item = self._list_store.get_item(prev_idx)
                prev_item.has_conflict = True
            else:
                seen_names[name_lower] = i
    
    def _update_status(self) -> None:
        """更新状态栏"""
        total = self._list_store.get_n_items()
        changed = 0
        conflicts = 0
        
        for i in range(total):
            item = self._list_store.get_item(i)
            if item.is_changed:
                changed += 1
            if item.has_conflict:
                conflicts += 1
        
        self._stats_label.set_text(f"更改: {changed} | 冲突: {conflicts} | 总计: {total}")
        
        if conflicts > 0:
            self._status_icon.set_from_icon_name("dialog-warning-symbolic")
            self._status_label.set_text(f"检测到 {conflicts} 个冲突，请检查或更改冲突处理策略")
            self._execute_btn.set_sensitive(True)  # 仍然允许执行，会根据策略处理
        elif changed > 0:
            self._status_icon.set_from_icon_name("emblem-ok-symbolic")
            self._status_label.set_text(f"预览完成，{changed} 个文件将被重命名")
            self._execute_btn.set_sensitive(True)
        else:
            self._status_icon.set_from_icon_name("dialog-information-symbolic")
            self._status_label.set_text("没有文件需要重命名")
            self._execute_btn.set_sensitive(False)
    
    def _on_preview(self, button: Gtk.Button) -> None:
        """预览按钮点击"""
        self._update_preview_list()
    
    def _on_execute(self, button: Gtk.Button) -> None:
        """执行重命名"""
        # 收集操作
        files = []
        new_names = []
        
        for i in range(self._list_store.get_n_items()):
            item = self._list_store.get_item(i)
            if item.is_changed:
                files.append(item.file_path)
                new_names.append(item.new_name)
        
        if not files:
            return
        
        # 设置冲突解决策略
        self._rename_manager.set_conflict_resolution(self._get_conflict_resolution())
        
        # 创建操作
        target_dir = self._get_target_dir()
        operations = self._rename_manager.create_operations(files, new_names, target_dir)
        
        # 验证
        operations, errors = self._rename_manager.validate_operations(operations)
        
        # 执行
        result = self._rename_manager.execute(operations)
        
        # 回调 - 在显示结果对话框之前调用，确保UI能及时刷新
        if self._on_complete:
            self._on_complete(result)
        
        # 显示结果
        self._show_result_dialog(result)
    
    def _show_result_dialog(self, result: RenameResult) -> None:
        """显示结果对话框"""
        if result.all_success:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="重命名完成",
                body=f"成功重命名 {result.success} 个文件",
            )
            dialog.add_response("ok", "确定")
            dialog.set_default_response("ok")
            dialog.connect("response", lambda d, r: self._on_dialog_close())
        else:
            body = f"成功: {result.success}\n失败: {result.failed}\n跳过: {result.skipped}"
            if result.errors:
                body += f"\n\n错误:\n" + "\n".join(result.errors[:5])
                if len(result.errors) > 5:
                    body += f"\n... 还有 {len(result.errors) - 5} 个错误"
            
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="重命名完成（部分失败）",
                body=body,
            )
            dialog.add_response("ok", "确定")
            dialog.set_default_response("ok")
            dialog.connect("response", lambda d, r: self._on_dialog_close())
        
        dialog.present()
    
    def _on_dialog_close(self) -> None:
        """对话框关闭时的处理"""
        self.close()


class BatchRenameItem(GObject.Object):
    """批量重命名列表项"""
    
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.original_name = Path(file_path).name
        self.new_name = self.original_name
        self.is_changed = False
        self.has_conflict = False


def show_batch_rename_dialog(
    parent: Optional[Gtk.Window],
    files: List[str],
    on_complete: Optional[Callable[[RenameResult], None]] = None,
) -> BatchRenameDialog:
    """
    显示批量重命名对话框
    
    Args:
        parent: 父窗口
        files: 文件路径列表
        on_complete: 完成回调函数
        
    Returns:
        BatchRenameDialog 实例
    """
    dialog = BatchRenameDialog(parent=parent, files=files, on_complete=on_complete)
    dialog.present()
    return dialog
