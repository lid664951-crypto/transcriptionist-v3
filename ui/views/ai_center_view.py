"""
AI Center View

AI中心视图，提供AI服务配置和翻译功能界面。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, List, Callable

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject, Pango

from transcriptionist_v3.application.ai_engine import (
    AIServiceConfig,
    ProviderRegistry,
    ProviderConfig,
    TranslationManager,
    TranslationResult,
)

logger = logging.getLogger(__name__)


class ProviderSelector(Gtk.Box):
    """
    服务提供者选择器
    
    下拉选择AI服务提供者。
    """
    
    __gtype_name__ = "ProviderSelector"
    
    __gsignals__ = {
        "provider-changed": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        self._providers = ProviderRegistry.instance().get_all_providers()
        self._current_provider_id = ""
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标签
        label = Gtk.Label(label="选择服务商")
        label.set_halign(Gtk.Align.START)
        label.add_css_class("heading")
        self.append(label)
        
        # 下拉框
        self._dropdown = Gtk.DropDown()
        
        # 创建模型
        store = Gtk.StringList()
        for provider in self._providers:
            store.append(f"{provider.name} - {provider.description}")
        
        self._dropdown.set_model(store)
        self._dropdown.connect("notify::selected", self._on_selection_changed)
        self.append(self._dropdown)
    
    def _on_selection_changed(self, dropdown: Gtk.DropDown, param) -> None:
        """选择改变"""
        index = dropdown.get_selected()
        if 0 <= index < len(self._providers):
            provider = self._providers[index]
            self._current_provider_id = provider.id
            self.emit("provider-changed", provider.id)
    
    def get_selected_provider(self) -> Optional[ProviderConfig]:
        """获取选中的提供者"""
        index = self._dropdown.get_selected()
        if 0 <= index < len(self._providers):
            return self._providers[index]
        return None
    
    def set_selected_provider(self, provider_id: str) -> None:
        """设置选中的提供者"""
        for i, provider in enumerate(self._providers):
            if provider.id == provider_id:
                self._dropdown.set_selected(i)
                self._current_provider_id = provider_id
                break


class APIConfigPanel(Gtk.Box):
    """
    API配置面板
    
    配置API Key、Base URL、模型名称等。
    """
    
    __gtype_name__ = "APIConfigPanel"
    
    __gsignals__ = {
        "config-changed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("api-config-panel")
        
        self._provider_config: Optional[ProviderConfig] = None
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # API Key
        api_key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        api_key_label = Gtk.Label(label="API Key")
        api_key_label.set_halign(Gtk.Align.START)
        api_key_label.add_css_class("caption")
        api_key_box.append(api_key_label)
        
        key_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self._api_key_entry = Gtk.PasswordEntry()
        self._api_key_entry.set_hexpand(True)
        self._api_key_entry.set_placeholder_text("sk-...")
        self._api_key_entry.set_show_peek_icon(True)
        self._api_key_entry.connect("changed", lambda e: self.emit("config-changed"))
        key_row.append(self._api_key_entry)
        
        # 获取Key链接按钮
        self._help_button = Gtk.LinkButton(label="获取Key")
        self._help_button.set_visible(False)
        key_row.append(self._help_button)
        
        api_key_box.append(key_row)
        self.append(api_key_box)
        
        # Base URL（仅自定义模式显示）
        self._base_url_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        base_url_label = Gtk.Label(label="API 服务器地址")
        base_url_label.set_halign(Gtk.Align.START)
        base_url_label.add_css_class("caption")
        self._base_url_box.append(base_url_label)
        
        self._base_url_entry = Gtk.Entry()
        self._base_url_entry.set_placeholder_text("http://localhost:1234/v1")
        self._base_url_entry.connect("changed", lambda e: self.emit("config-changed"))
        self._base_url_box.append(self._base_url_entry)
        
        self.append(self._base_url_box)
        
        # 模型名称
        model_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        model_label = Gtk.Label(label="模型名称")
        model_label.set_halign(Gtk.Align.START)
        model_label.add_css_class("caption")
        model_box.append(model_label)
        
        self._model_entry = Gtk.Entry()
        self._model_entry.set_placeholder_text("模型ID")
        self._model_entry.connect("changed", lambda e: self.emit("config-changed"))
        model_box.append(self._model_entry)
        
        self.append(model_box)
    
    def set_provider(self, provider: ProviderConfig) -> None:
        """设置当前提供者"""
        self._provider_config = provider
        
        # 更新帮助链接
        if provider.help_url:
            self._help_button.set_uri(provider.help_url)
            self._help_button.set_visible(True)
        else:
            self._help_button.set_visible(False)
        
        # 更新Base URL显示
        self._base_url_box.set_visible(provider.is_custom)
        if provider.default_base_url:
            self._base_url_entry.set_text(provider.default_base_url)
        
        # 更新模型占位符
        if provider.model_placeholder:
            self._model_entry.set_placeholder_text(provider.model_placeholder)
    
    def get_config(self) -> AIServiceConfig:
        """获取配置"""
        provider_id = self._provider_config.id if self._provider_config else ""
        
        return AIServiceConfig(
            provider_id=provider_id,
            api_key=self._api_key_entry.get_text(),
            base_url=self._base_url_entry.get_text(),
            model_name=self._model_entry.get_text(),
        )
    
    def set_config(self, config: AIServiceConfig) -> None:
        """设置配置"""
        self._api_key_entry.set_text(config.api_key)
        self._base_url_entry.set_text(config.base_url)
        self._model_entry.set_text(config.model_name)


class ConnectionStatusBar(Gtk.Box):
    """
    连接状态栏
    
    显示API连接状态和测试按钮。
    """
    
    __gtype_name__ = "ConnectionStatusBar"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_margin_top(8)
        
        self._is_connected = False
        self._is_testing = False
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 状态图标和文字
        self._status_icon = Gtk.Image.new_from_icon_name("network-offline-symbolic")
        self.append(self._status_icon)
        
        self._status_label = Gtk.Label(label="未连接")
        self._status_label.add_css_class("dim-label")
        self._status_label.set_hexpand(True)
        self._status_label.set_halign(Gtk.Align.START)
        self.append(self._status_label)
        
        # 测试按钮
        self._test_button = Gtk.Button(label="测试连接")
        self._test_button.add_css_class("suggested-action")
        self.append(self._test_button)
        
        # 保存按钮
        self._save_button = Gtk.Button(label="保存配置")
        self.append(self._save_button)
    
    def set_testing(self, testing: bool) -> None:
        """设置测试中状态"""
        self._is_testing = testing
        self._test_button.set_sensitive(not testing)
        
        if testing:
            self._status_label.set_label("正在测试...")
            self._status_icon.set_from_icon_name("content-loading-symbolic")
    
    def set_connected(self, connected: bool, message: str = "") -> None:
        """设置连接状态"""
        self._is_connected = connected
        
        if connected:
            self._status_icon.set_from_icon_name("network-transmit-receive-symbolic")
            self._status_label.set_label(message or "连接成功")
            self._status_label.remove_css_class("dim-label")
            self._status_label.add_css_class("success")
        else:
            self._status_icon.set_from_icon_name("network-offline-symbolic")
            self._status_label.set_label(message or "连接失败")
            self._status_label.remove_css_class("success")
            self._status_label.add_css_class("dim-label")
    
    def connect_test_clicked(self, callback: Callable) -> None:
        """连接测试按钮点击"""
        self._test_button.connect("clicked", lambda b: callback())
    
    def connect_save_clicked(self, callback: Callable) -> None:
        """连接保存按钮点击"""
        self._save_button.connect("clicked", lambda b: callback())


class TranslationResultRow(Gtk.Box):
    """翻译结果行"""
    
    __gtype_name__ = "TranslationResultRow"
    
    def __init__(self, original: str, translated: str):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # 原文
        original_label = Gtk.Label(label=original)
        original_label.set_hexpand(True)
        original_label.set_halign(Gtk.Align.START)
        original_label.set_ellipsize(Pango.EllipsizeMode.END)
        original_label.add_css_class("dim-label")
        self.append(original_label)
        
        # 箭头
        arrow = Gtk.Label(label="→")
        arrow.add_css_class("dim-label")
        self.append(arrow)
        
        # 译文
        translated_label = Gtk.Label(label=translated)
        translated_label.set_hexpand(True)
        translated_label.set_halign(Gtk.Align.START)
        translated_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(translated_label)


class TranslationPanel(Gtk.Box):
    """
    翻译面板
    
    提供文件名翻译功能。
    """
    
    __gtype_name__ = "TranslationPanel"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("translation-panel")
        
        self._results: List[TranslationResult] = []
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="文件名翻译")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)
        
        # 翻译按钮
        self._translate_button = Gtk.Button(label="开始翻译")
        self._translate_button.add_css_class("suggested-action")
        header.append(self._translate_button)
        
        self.append(header)
        
        # 输入区域
        input_frame = Gtk.Frame()
        input_frame.set_label("输入文件名（每行一个）")
        
        self._input_view = Gtk.TextView()
        self._input_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._input_view.set_monospace(True)
        self._input_view.set_vexpand(True)
        
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_min_content_height(120)
        input_scroll.set_child(self._input_view)
        
        input_frame.set_child(input_scroll)
        self.append(input_frame)
        
        # 进度条
        self._progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._progress_box.set_visible(False)
        
        self._progress_label = Gtk.Label(label="翻译中...")
        self._progress_label.set_halign(Gtk.Align.START)
        self._progress_box.append(self._progress_label)
        
        self._progress_bar = Gtk.ProgressBar()
        self._progress_box.append(self._progress_bar)
        
        self.append(self._progress_box)
        
        # 结果区域
        result_frame = Gtk.Frame()
        result_frame.set_label("翻译结果")
        
        self._result_list = Gtk.ListBox()
        self._result_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._result_list.add_css_class("boxed-list")
        
        result_scroll = Gtk.ScrolledWindow()
        result_scroll.set_min_content_height(150)
        result_scroll.set_child(self._result_list)
        
        result_frame.set_child(result_scroll)
        self.append(result_frame)
    
    def get_input_texts(self) -> List[str]:
        """获取输入的文本列表"""
        buffer = self._input_view.get_buffer()
        start, end = buffer.get_bounds()
        text = buffer.get_text(start, end, False)
        
        lines = [line.strip() for line in text.split("\n")]
        return [line for line in lines if line]
    
    def set_progress(self, current: int, total: int, message: str = "") -> None:
        """设置进度"""
        self._progress_box.set_visible(True)
        self._progress_label.set_label(message or f"翻译中 {current}/{total}")
        
        if total > 0:
            self._progress_bar.set_fraction(current / total)
    
    def hide_progress(self) -> None:
        """隐藏进度"""
        self._progress_box.set_visible(False)
    
    def set_results(self, results: List[TranslationResult]) -> None:
        """设置翻译结果"""
        self._results = results
        
        # 清空现有结果
        while True:
            row = self._result_list.get_row_at_index(0)
            if row is None:
                break
            self._result_list.remove(row)
        
        # 添加新结果
        for result in results:
            row = TranslationResultRow(result.original, result.translated)
            self._result_list.append(row)
    
    def connect_translate_clicked(self, callback: Callable) -> None:
        """连接翻译按钮点击"""
        self._translate_button.connect("clicked", lambda b: callback())
    
    def set_translating(self, translating: bool) -> None:
        """设置翻译中状态"""
        self._translate_button.set_sensitive(not translating)
        if translating:
            self._translate_button.set_label("翻译中...")
        else:
            self._translate_button.set_label("开始翻译")


class AICenterView(Gtk.Box):
    """
    AI中心视图
    
    整合AI服务配置和翻译功能的主视图。
    """
    
    __gtype_name__ = "AICenterView"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("ai-center-view")
        
        self._translation_manager = TranslationManager.instance()
        self._build_ui()
        self._connect_signals()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 标题栏
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="AI 翻译中心"))
        self.append(header)
        
        # 主内容区域（可滚动）
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        
        # AI模型配置卡片
        config_card = Adw.PreferencesGroup()
        config_card.set_title("AI 模型配置")
        config_card.set_description("选择并配置AI翻译服务")
        
        # 服务商选择
        self._provider_selector = ProviderSelector()
        config_card.add(self._provider_selector)
        
        # API配置
        self._api_config = APIConfigPanel()
        self._api_config.set_margin_top(12)
        config_card.add(self._api_config)
        
        # 连接状态
        self._status_bar = ConnectionStatusBar()
        config_card.add(self._status_bar)
        
        content.append(config_card)
        
        # 分隔线
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.append(separator)
        
        # 翻译面板
        self._translation_panel = TranslationPanel()
        content.append(self._translation_panel)
        
        scrolled.set_child(content)
        self.append(scrolled)
    
    def _connect_signals(self) -> None:
        """连接信号"""
        # 提供者选择改变
        self._provider_selector.connect(
            "provider-changed",
            self._on_provider_changed,
        )
        
        # 测试连接
        self._status_bar.connect_test_clicked(self._on_test_connection)
        
        # 保存配置
        self._status_bar.connect_save_clicked(self._on_save_config)
        
        # 开始翻译
        self._translation_panel.connect_translate_clicked(self._on_translate)
        
        # 初始化选择第一个提供者
        providers = ProviderRegistry.instance().get_all_providers()
        if providers:
            self._provider_selector.set_selected_provider(providers[0].id)
            self._api_config.set_provider(providers[0])
    
    def _on_provider_changed(self, selector: ProviderSelector, provider_id: str) -> None:
        """提供者改变"""
        provider = selector.get_selected_provider()
        if provider:
            self._api_config.set_provider(provider)
    
    def _on_test_connection(self) -> None:
        """测试连接"""
        config = self._api_config.get_config()
        provider = self._provider_selector.get_selected_provider()
        
        if provider:
            config.provider_id = provider.id
        
        # 配置翻译管理器
        if not self._translation_manager.configure(config):
            self._status_bar.set_connected(False, "配置无效")
            return
        
        self._status_bar.set_testing(True)
        
        # 异步测试连接
        def do_test():
            async def test():
                result = await self._translation_manager.test_connection()
                GLib.idle_add(
                    self._on_test_complete,
                    result.success,
                    result.error or "",
                )
            
            asyncio.run(test())
        
        import threading
        thread = threading.Thread(target=do_test, daemon=True)
        thread.start()
    
    def _on_test_complete(self, success: bool, error: str) -> bool:
        """测试完成回调"""
        self._status_bar.set_testing(False)
        
        if success:
            self._status_bar.set_connected(True, "连接成功")
        else:
            self._status_bar.set_connected(False, error or "连接失败")
        
        return False
    
    def _on_save_config(self) -> None:
        """保存配置"""
        config = self._api_config.get_config()
        provider = self._provider_selector.get_selected_provider()
        
        if provider:
            config.provider_id = provider.id
        
        # TODO: 保存到配置文件
        logger.info(f"Saving config: {config.provider_id}")
        
        # 显示保存成功提示
        toast = Adw.Toast(title="配置已保存")
        # 需要找到窗口来显示toast
    
    def _on_translate(self) -> None:
        """开始翻译"""
        texts = self._translation_panel.get_input_texts()
        
        if not texts:
            return
        
        config = self._api_config.get_config()
        provider = self._provider_selector.get_selected_provider()
        
        if provider:
            config.provider_id = provider.id
        
        # 配置翻译管理器
        if not self._translation_manager.configure(config):
            return
        
        self._translation_panel.set_translating(True)
        
        # 异步翻译
        def do_translate():
            async def translate():
                def progress_callback(current: int, total: int, msg: str):
                    GLib.idle_add(
                        self._translation_panel.set_progress,
                        current, total, msg,
                    )
                
                result = await self._translation_manager.translate_batch(
                    texts,
                    progress_callback=progress_callback,
                )
                
                GLib.idle_add(self._on_translate_complete, result.data or [])
            
            asyncio.run(translate())
        
        import threading
        thread = threading.Thread(target=do_translate, daemon=True)
        thread.start()
    
    def _on_translate_complete(self, results: List[TranslationResult]) -> bool:
        """翻译完成回调"""
        self._translation_panel.set_translating(False)
        self._translation_panel.hide_progress()
        self._translation_panel.set_results(results)
        return False
