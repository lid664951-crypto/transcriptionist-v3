"""
侧边栏组件 - 导航菜单
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk


class SidebarMixin:
    """侧边栏功能混入类"""
    
    def _create_sidebar(self) -> Gtk.Box:
        """创建侧边栏 - 按工作流程分组"""
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(180, -1)
        sidebar_box.add_css_class("sidebar")
        
        # 导航列表
        self._nav_list = Gtk.ListBox()
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.add_css_class("navigation-sidebar")
        self._nav_list.connect("row-selected", self._on_nav_selected)
        
        # ─── 核心功能 ───
        core_header = self._create_section_header("核心功能")
        self._nav_list.append(core_header)
        
        library_row = self._create_nav_row("音效库", "folder-music-symbolic", "library")
        self._nav_list.append(library_row)
        
        # ─── AI 工作流 ───
        ai_header = self._create_section_header("AI 工作流")
        self._nav_list.append(ai_header)
        
        ai_translate_row = self._create_nav_row("AI翻译", "accessories-dictionary-symbolic", "ai_translate")
        self._nav_list.append(ai_translate_row)
        
        naming_row = self._create_nav_row("命名规则", "tag-symbolic", "naming_rules")
        self._nav_list.append(naming_row)
        
        # ─── 扩展功能 ───
        ext_header = self._create_section_header("扩展功能")
        self._nav_list.append(ext_header)
        
        online_row = self._create_nav_row("在线资源", "network-workgroup-symbolic", "online")
        self._nav_list.append(online_row)
        
        projects_row = self._create_nav_row("项目", "folder-symbolic", "projects")
        self._nav_list.append(projects_row)
        
        toolbox_row = self._create_nav_row("工具箱", "applications-utilities-symbolic", "toolbox")
        self._nav_list.append(toolbox_row)
        
        # 滚动容器
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._nav_list)
        sidebar_box.append(scrolled)
        
        # ─── 系统 ───
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar_box.append(separator)
        
        # 设置按钮（底部固定）
        settings_row = self._create_nav_row("设置", "preferences-system-symbolic", "settings")
        self._settings_list = Gtk.ListBox()
        self._settings_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._settings_list.add_css_class("navigation-sidebar")
        self._settings_list.connect("row-selected", self._on_settings_selected)
        self._settings_list.append(settings_row)
        sidebar_box.append(self._settings_list)
        
        # 默认选中音效库
        self._nav_list.select_row(library_row)
        
        return sidebar_box
    
    def _create_section_header(self, title: str) -> Gtk.ListBoxRow:
        """创建分组标题行（不可选中）"""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.page_id = None
        
        label = Gtk.Label(label=title)
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(12)
        label.set_margin_top(12)
        label.set_margin_bottom(4)
        label.add_css_class("section-header")
        
        row.set_child(label)
        return row
    
    def _create_nav_row(self, label: str, icon_name: str, page_id: str) -> Gtk.ListBoxRow:
        """创建导航行"""
        row = Gtk.ListBoxRow()
        row.page_id = page_id
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(18)
        icon.add_css_class("nav-icon")
        box.append(icon)
        
        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.START)
        label_widget.set_hexpand(True)
        label_widget.add_css_class("nav-label")
        box.append(label_widget)
        
        row.set_child(box)
        return row
    
    def _on_nav_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """导航项选中事件"""
        if row is None:
            return
        
        if not hasattr(self, '_content_stack') or self._content_stack is None:
            return
        
        page_id = getattr(row, 'page_id', None)
        if not page_id:
            return
        
        if hasattr(self, '_settings_list'):
            self._settings_list.unselect_all()
        
        self._content_stack.set_visible_child_name(page_id)
    
    def _on_settings_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """设置项选中事件"""
        if row is None:
            return
        
        if not hasattr(self, '_content_stack') or self._content_stack is None:
            return
        
        if hasattr(self, '_nav_list'):
            self._nav_list.unselect_all()
        
        self._content_stack.set_visible_child_name("settings")
