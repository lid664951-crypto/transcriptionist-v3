"""
顶部标题栏组件
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio


class HeaderBarMixin:
    """顶部标题栏功能混入类"""
    
    def _create_header_bar(self) -> Gtk.HeaderBar:
        """创建顶部标题栏"""
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        
        # 左侧：应用标题
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        app_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        app_icon.set_pixel_size(20)
        title_box.append(app_icon)
        
        title_label = Gtk.Label(label="音译家")
        title_label.add_css_class("title")
        title_box.append(title_label)
        
        header.set_title_widget(title_box)
        
        # 右侧按钮组
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        # 主题切换按钮
        self._theme_button = Gtk.Button()
        self._theme_button.set_icon_name("weather-clear-symbolic")
        self._theme_button.set_tooltip_text("切换深色/浅色主题")
        self._theme_button.connect("clicked", self._on_theme_toggle)
        self._theme_button.add_css_class("flat")
        right_box.append(self._theme_button)
        
        # 菜单按钮
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("菜单")
        menu_button.add_css_class("flat")
        
        menu = Gio.Menu()
        menu.append("关于", "app.about")
        menu.append("退出", "app.quit")
        menu_button.set_menu_model(menu)
        right_box.append(menu_button)
        
        header.pack_end(right_box)
        
        return header
    
    def _on_theme_toggle(self, button: Gtk.Button) -> None:
        """主题切换按钮点击"""
        style_manager = Adw.StyleManager.get_default()
        
        if style_manager.get_dark():
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            button.set_icon_name("weather-clear-symbolic")
            if hasattr(self, '_theme_switch'):
                self._theme_switch.set_active(False)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            button.set_icon_name("weather-clear-night-symbolic")
            if hasattr(self, '_theme_switch'):
                self._theme_switch.set_active(True)
