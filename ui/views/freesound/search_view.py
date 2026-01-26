"""
Freesound Search View

Main search interface for Freesound integration.
Includes search bar, filters, and results display.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, GObject
from typing import Optional, Callable, List
import asyncio

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundClient,
    FreesoundSearchService,
    FreesoundSearchOptions,
    FreesoundSearchResult,
    FreesoundSettings,
)


class FilterPopover(Gtk.Popover):
    """Popover for advanced search filters."""
    
    __gsignals__ = {
        'filters-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self):
        super().__init__()
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the filter UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Duration filter
        duration_label = Gtk.Label(label="时长", xalign=0)
        duration_label.add_css_class('heading')
        box.append(duration_label)
        
        self.duration_combo = Gtk.ComboBoxText()
        self.duration_combo.append('all', '全部')
        self.duration_combo.append('short', '0-5 秒')
        self.duration_combo.append('medium', '5-30 秒')
        self.duration_combo.append('long', '30秒-2分钟')
        self.duration_combo.append('very_long', '2分钟以上')
        self.duration_combo.set_active_id('all')
        self.duration_combo.connect('changed', self._on_filter_changed)
        box.append(self.duration_combo)
        
        # License filter
        license_label = Gtk.Label(label="授权协议", xalign=0)
        license_label.add_css_class('heading')
        box.append(license_label)
        
        self.license_combo = Gtk.ComboBoxText()
        self.license_combo.append('all', '全部')
        self.license_combo.append('commercial', '可商用 (CC0, CC BY)')
        self.license_combo.append('free', '完全免费 (CC0)')
        self.license_combo.set_active_id('all')
        self.license_combo.connect('changed', self._on_filter_changed)
        box.append(self.license_combo)
        
        # Rating filter
        rating_label = Gtk.Label(label="最低评分", xalign=0)
        rating_label.add_css_class('heading')
        box.append(rating_label)
        
        self.rating_combo = Gtk.ComboBoxText()
        self.rating_combo.append('0', '全部')
        self.rating_combo.append('3', '3星以上')
        self.rating_combo.append('4', '4星以上')
        self.rating_combo.append('5', '5星')
        self.rating_combo.set_active_id('0')
        self.rating_combo.connect('changed', self._on_filter_changed)
        box.append(self.rating_combo)
        
        # File type filter
        type_label = Gtk.Label(label="文件格式", xalign=0)
        type_label.add_css_class('heading')
        box.append(type_label)
        
        type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.type_wav = Gtk.CheckButton(label='WAV')
        self.type_wav.set_active(True)
        self.type_wav.connect('toggled', self._on_filter_changed)
        type_box.append(self.type_wav)
        
        self.type_mp3 = Gtk.CheckButton(label='MP3')
        self.type_mp3.set_active(True)
        self.type_mp3.connect('toggled', self._on_filter_changed)
        type_box.append(self.type_mp3)
        
        self.type_flac = Gtk.CheckButton(label='FLAC')
        self.type_flac.connect('toggled', self._on_filter_changed)
        type_box.append(self.type_flac)
        
        self.type_ogg = Gtk.CheckButton(label='OGG')
        self.type_ogg.connect('toggled', self._on_filter_changed)
        type_box.append(self.type_ogg)
        
        box.append(type_box)
        
        # Sort order
        sort_label = Gtk.Label(label="排序方式", xalign=0)
        sort_label.add_css_class('heading')
        box.append(sort_label)
        
        self.sort_combo = Gtk.ComboBoxText()
        self.sort_combo.append('score', '相关度')
        self.sort_combo.append('rating_desc', '评分最高')
        self.sort_combo.append('downloads_desc', '下载最多')
        self.sort_combo.append('created_desc', '最新上传')
        self.sort_combo.set_active_id('score')
        self.sort_combo.connect('changed', self._on_filter_changed)
        box.append(self.sort_combo)
        
        # Reset button
        reset_btn = Gtk.Button(label='重置筛选')
        reset_btn.connect('clicked', self._on_reset_clicked)
        box.append(reset_btn)
        
        self.set_child(box)
    
    def _on_filter_changed(self, widget):
        """Handle filter change."""
        self.emit('filters-changed')
    
    def _on_reset_clicked(self, button):
        """Reset all filters to defaults."""
        self.duration_combo.set_active_id('all')
        self.license_combo.set_active_id('all')
        self.rating_combo.set_active_id('0')
        self.type_wav.set_active(True)
        self.type_mp3.set_active(True)
        self.type_flac.set_active(False)
        self.type_ogg.set_active(False)
        self.sort_combo.set_active_id('score')
        self.emit('filters-changed')
    
    def get_duration_preset(self) -> Optional[str]:
        """Get selected duration preset."""
        value = self.duration_combo.get_active_id()
        return None if value == 'all' else value
    
    def get_license_preset(self) -> Optional[str]:
        """Get selected license preset."""
        value = self.license_combo.get_active_id()
        return None if value == 'all' else value
    
    def get_min_rating(self) -> Optional[float]:
        """Get minimum rating filter."""
        value = self.rating_combo.get_active_id()
        return None if value == '0' else float(value)
    
    def get_file_types(self) -> Optional[List[str]]:
        """Get selected file types."""
        types = []
        if self.type_wav.get_active():
            types.append('wav')
        if self.type_mp3.get_active():
            types.append('mp3')
        if self.type_flac.get_active():
            types.append('flac')
        if self.type_ogg.get_active():
            types.append('ogg')
        return types if types else None
    
    def get_sort_order(self) -> str:
        """Get selected sort order."""
        return self.sort_combo.get_active_id() or 'score'


class FreesoundSearchView(Adw.Bin):
    """
    Main Freesound search view.
    
    Includes:
    - Search bar with auto-translation
    - Filter popover
    - Results display
    - Download queue
    """
    
    __gsignals__ = {
        'search-started': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'search-completed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'search-error': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'sound-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'download-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(
        self,
        search_service: Optional[FreesoundSearchService] = None,
    ):
        super().__init__()
        
        self.search_service = search_service
        self._current_query = ""
        self._current_page = 1
        self._total_pages = 1
        self._is_searching = False
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the search view UI."""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Header bar with search
        header = self._build_header()
        main_box.append(header)
        
        # Content area
        content = self._build_content()
        main_box.append(content)
        
        self.set_child(main_box)
    
    def _build_header(self) -> Gtk.Widget:
        """Build the header with search bar."""
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.add_css_class('view')
        header_box.set_margin_top(16)
        header_box.set_margin_bottom(8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)
        
        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="🧪 实验室 - Freesound 全球音效库")
        title.add_css_class('title-2')
        title.set_xalign(0)
        title_box.append(title)
        
        # NEW badge
        new_badge = Gtk.Label(label="NEW")
        new_badge.add_css_class('accent')
        new_badge.add_css_class('caption')
        title_box.append(new_badge)
        
        header_box.append(title_box)
        
        # Subtitle
        subtitle = Gtk.Label(label="搜索 50 万+ CC 授权音效，支持中文搜索，一键下载翻译")
        subtitle.add_css_class('dim-label')
        subtitle.set_xalign(0)
        header_box.append(subtitle)
        
        # Search bar row
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_row.set_margin_top(12)
        
        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("输入中文或英文关键词搜索...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect('activate', self._on_search_activated)
        self.search_entry.connect('search-changed', self._on_search_changed)
        search_row.append(self.search_entry)
        
        # Filter button
        filter_btn = Gtk.MenuButton()
        filter_btn.set_icon_name('funnel-symbolic')
        filter_btn.set_tooltip_text('筛选条件')
        
        self.filter_popover = FilterPopover()
        self.filter_popover.connect('filters-changed', self._on_filters_changed)
        filter_btn.set_popover(self.filter_popover)
        search_row.append(filter_btn)
        
        # Search button
        self.search_btn = Gtk.Button()
        self.search_btn.set_icon_name('system-search-symbolic')
        self.search_btn.add_css_class('suggested-action')
        self.search_btn.connect('clicked', self._on_search_clicked)
        search_row.append(self.search_btn)
        
        header_box.append(search_row)
        
        # Popular tags
        tags_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tags_box.set_margin_top(8)
        
        tags_label = Gtk.Label(label="热门标签:")
        tags_label.add_css_class('dim-label')
        tags_box.append(tags_label)
        
        popular_tags = ['impact', 'whoosh', 'ambient', 'footsteps', 'explosion', 'ui']
        for tag in popular_tags:
            tag_btn = Gtk.Button(label=tag)
            tag_btn.add_css_class('pill')
            tag_btn.add_css_class('flat')
            tag_btn.connect('clicked', self._on_tag_clicked, tag)
            tags_box.append(tag_btn)
        
        header_box.append(tags_box)
        
        return header_box
    
    def _build_content(self) -> Gtk.Widget:
        """Build the content area."""
        # Stack for different states
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_vexpand(True)
        
        # Empty state
        empty_page = self._build_empty_state()
        self.content_stack.add_named(empty_page, 'empty')
        
        # Loading state
        loading_page = self._build_loading_state()
        self.content_stack.add_named(loading_page, 'loading')
        
        # Results state
        results_page = self._build_results_area()
        self.content_stack.add_named(results_page, 'results')
        
        # Error state
        error_page = self._build_error_state()
        self.content_stack.add_named(error_page, 'error')
        
        self.content_stack.set_visible_child_name('empty')
        
        return self.content_stack
    
    def _build_empty_state(self) -> Gtk.Widget:
        """Build empty state placeholder."""
        status = Adw.StatusPage()
        status.set_icon_name('system-search-symbolic')
        status.set_title('搜索全球音效')
        status.set_description('输入关键词开始搜索 Freesound 音效库\n支持中文搜索，结果自动翻译')
        return status
    
    def _build_loading_state(self) -> Gtk.Widget:
        """Build loading state."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        box.append(spinner)
        
        self.loading_label = Gtk.Label(label="正在搜索...")
        self.loading_label.add_css_class('dim-label')
        box.append(self.loading_label)
        
        return box
    
    def _build_results_area(self) -> Gtk.Widget:
        """Build results display area."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Results info bar
        info_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_bar.set_margin_start(16)
        info_bar.set_margin_end(16)
        info_bar.set_margin_top(8)
        info_bar.set_margin_bottom(8)
        
        self.results_label = Gtk.Label(label="")
        self.results_label.set_xalign(0)
        self.results_label.set_hexpand(True)
        info_bar.append(self.results_label)
        
        box.append(info_bar)
        
        # Scrolled results
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Results list
        self.results_list = Gtk.ListBox()
        self.results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.results_list.add_css_class('boxed-list')
        self.results_list.set_margin_start(16)
        self.results_list.set_margin_end(16)
        self.results_list.set_margin_bottom(16)
        
        scrolled.set_child(self.results_list)
        box.append(scrolled)
        
        # Pagination
        pagination = self._build_pagination()
        box.append(pagination)
        
        return box
    
    def _build_pagination(self) -> Gtk.Widget:
        """Build pagination controls."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(8)
        box.set_margin_bottom(16)
        
        self.prev_btn = Gtk.Button()
        self.prev_btn.set_icon_name('go-previous-symbolic')
        self.prev_btn.set_sensitive(False)
        self.prev_btn.connect('clicked', self._on_prev_page)
        box.append(self.prev_btn)
        
        self.page_label = Gtk.Label(label="1 / 1")
        self.page_label.set_width_chars(10)
        box.append(self.page_label)
        
        self.next_btn = Gtk.Button()
        self.next_btn.set_icon_name('go-next-symbolic')
        self.next_btn.set_sensitive(False)
        self.next_btn.connect('clicked', self._on_next_page)
        box.append(self.next_btn)
        
        return box
    
    def _build_error_state(self) -> Gtk.Widget:
        """Build error state."""
        status = Adw.StatusPage()
        status.set_icon_name('dialog-error-symbolic')
        status.set_title('搜索失败')
        
        self.error_label = Gtk.Label(label="")
        status.set_description('')
        
        retry_btn = Gtk.Button(label='重试')
        retry_btn.set_halign(Gtk.Align.CENTER)
        retry_btn.add_css_class('pill')
        retry_btn.connect('clicked', self._on_retry_clicked)
        status.set_child(retry_btn)
        
        return status
    
    def _on_search_activated(self, entry):
        """Handle search entry activation."""
        self._perform_search()
    
    def _on_search_changed(self, entry):
        """Handle search text change."""
        # Could implement auto-complete here
        pass
    
    def _on_search_clicked(self, button):
        """Handle search button click."""
        self._perform_search()
    
    def _on_tag_clicked(self, button, tag: str):
        """Handle popular tag click."""
        self.search_entry.set_text(tag)
        self._perform_search()
    
    def _on_filters_changed(self, popover):
        """Handle filter change."""
        if self._current_query:
            self._current_page = 1
            self._perform_search()
    
    def _on_prev_page(self, button):
        """Go to previous page."""
        if self._current_page > 1:
            self._current_page -= 1
            self._perform_search()
    
    def _on_next_page(self, button):
        """Go to next page."""
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._perform_search()
    
    def _on_retry_clicked(self, button):
        """Retry failed search."""
        self._perform_search()
    
    def _perform_search(self):
        """Perform the search."""
        query = self.search_entry.get_text().strip()
        if not query:
            return
        
        if self._is_searching:
            return
        
        self._current_query = query
        self._is_searching = True
        
        # Show loading state
        self.loading_label.set_text(f"正在搜索 \"{query}\"...")
        self.content_stack.set_visible_child_name('loading')
        
        self.emit('search-started', query)
        
        # Perform async search
        if self.search_service:
            GLib.idle_add(self._do_async_search)
        else:
            # No service, show error
            self._show_error("搜索服务未配置")
    
    def _do_async_search(self):
        """Execute async search in background."""
        async def search():
            try:
                result = await self.search_service.search(
                    query=self._current_query,
                    page=self._current_page,
                    duration_preset=self.filter_popover.get_duration_preset(),
                    license_preset=self.filter_popover.get_license_preset(),
                    file_types=self.filter_popover.get_file_types(),
                    min_rating=self.filter_popover.get_min_rating(),
                    sort=self.filter_popover.get_sort_order(),
                )
                GLib.idle_add(self._on_search_success, result)
            except Exception as e:
                GLib.idle_add(self._show_error, str(e))
        
        # Run in asyncio event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(search())
        finally:
            loop.close()
        
        return False
    
    def _on_search_success(self, result: FreesoundSearchResult):
        """Handle successful search."""
        self._is_searching = False
        self._total_pages = result.total_pages
        
        # Update results label
        self.results_label.set_text(f"共找到 {result.count:,} 个音效")
        
        # Update pagination
        self.page_label.set_text(f"{self._current_page} / {self._total_pages}")
        self.prev_btn.set_sensitive(self._current_page > 1)
        self.next_btn.set_sensitive(self._current_page < self._total_pages)
        
        # Clear and populate results
        self._clear_results()
        for sound in result.results:
            row = self._create_sound_row(sound)
            self.results_list.append(row)
        
        # Show results
        self.content_stack.set_visible_child_name('results')
        
        self.emit('search-completed', result)
    
    def _show_error(self, message: str):
        """Show error state."""
        self._is_searching = False
        self.content_stack.set_visible_child_name('error')
        self.emit('search-error', message)
    
    def _clear_results(self):
        """Clear results list."""
        while True:
            row = self.results_list.get_first_child()
            if row is None:
                break
            self.results_list.remove(row)
    
    def _create_sound_row(self, sound) -> Gtk.Widget:
        """Create a row widget for a sound."""
        # Import here to avoid circular imports
        from .sound_card import FreesoundSoundCard
        
        card = FreesoundSoundCard(sound)
        card.connect('play-clicked', lambda c, s: self.emit('sound-selected', s))
        card.connect('download-clicked', lambda c, s: self.emit('download-requested', s))
        
        return card
    
    def set_search_service(self, service: FreesoundSearchService):
        """Set the search service."""
        self.search_service = service
