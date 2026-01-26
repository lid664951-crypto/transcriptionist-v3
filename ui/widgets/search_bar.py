"""
Search Bar Widget

A GTK4 search bar with advanced search options.
Inspired by Quod Libet's SearchBarBox but adapted for GTK4/Libadwaita.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GObject, GLib
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False


class SearchBar(Gtk.Box):
    """
    A search bar widget with advanced search options.
    
    Features:
    - Text search with debouncing
    - Field-specific search (duration, format, etc.)
    - Saved searches
    - Search history
    - Advanced options popover
    """
    
    __gtype_name__ = 'SearchBar'
    
    __gsignals__ = {
        'search-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'search-activated': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'advanced-search': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    # Default debounce timeout in milliseconds
    DEFAULT_TIMEOUT = 300
    
    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        if not GTK_AVAILABLE:
            return
        
        self._timeout = timeout
        self._debounce_id: Optional[int] = None
        self._search_history: List[str] = []
        self._saved_searches: List[str] = []
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Set up the search bar UI."""
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        
        # Search entry with icon
        self._entry = Gtk.SearchEntry()
        self._entry.set_placeholder_text("搜索音效...")
        self._entry.set_hexpand(True)
        self._entry.set_tooltip_text(
            "搜索提示:\n"
            "• 直接输入文字搜索文件名\n"
            "• duration:>5 搜索时长大于5秒\n"
            "• format:wav 搜索WAV格式\n"
            "• AND/OR/NOT 组合搜索"
        )
        
        # Connect signals
        self._entry.connect("search-changed", self._on_search_changed)
        self._entry.connect("activate", self._on_search_activated)
        self._entry.connect("stop-search", self._on_stop_search)
        
        self.append(self._entry)
        
        # Advanced options button
        self._options_button = Gtk.MenuButton()
        self._options_button.set_icon_name("view-more-symbolic")
        self._options_button.set_tooltip_text("高级搜索选项")
        self._options_button.add_css_class("flat")
        
        # Create options popover
        self._options_button.set_popover(self._create_options_popover())
        
        self.append(self._options_button)
    
    def _create_options_popover(self) -> Gtk.Popover:
        """Create the advanced options popover."""
        popover = Gtk.Popover()
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Field filters section
        filters_label = Gtk.Label(label="字段过滤")
        filters_label.add_css_class("heading")
        filters_label.set_halign(Gtk.Align.START)
        box.append(filters_label)
        
        # Duration filter
        duration_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        duration_label = Gtk.Label(label="时长:")
        duration_label.set_width_chars(8)
        duration_label.set_halign(Gtk.Align.START)
        duration_box.append(duration_label)
        
        self._duration_op = Gtk.DropDown.new_from_strings([">", "<", "=", ">=", "<="])
        self._duration_op.set_selected(0)
        duration_box.append(self._duration_op)
        
        self._duration_value = Gtk.SpinButton.new_with_range(0, 3600, 1)
        self._duration_value.set_value(0)
        duration_box.append(self._duration_value)
        
        duration_unit = Gtk.Label(label="秒")
        duration_box.append(duration_unit)
        
        box.append(duration_box)
        
        # Format filter
        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        format_label = Gtk.Label(label="格式:")
        format_label.set_width_chars(8)
        format_label.set_halign(Gtk.Align.START)
        format_box.append(format_label)
        
        self._format_dropdown = Gtk.DropDown.new_from_strings([
            "全部", "WAV", "MP3", "FLAC", "OGG", "M4A", "AIFF"
        ])
        self._format_dropdown.set_selected(0)
        self._format_dropdown.set_hexpand(True)
        format_box.append(self._format_dropdown)
        
        box.append(format_box)
        
        # Sample rate filter
        sr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sr_label = Gtk.Label(label="采样率:")
        sr_label.set_width_chars(8)
        sr_label.set_halign(Gtk.Align.START)
        sr_box.append(sr_label)
        
        self._sr_dropdown = Gtk.DropDown.new_from_strings([
            "全部", "44.1kHz", "48kHz", "96kHz", "192kHz"
        ])
        self._sr_dropdown.set_selected(0)
        self._sr_dropdown.set_hexpand(True)
        sr_box.append(self._sr_dropdown)
        
        box.append(sr_box)
        
        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Saved searches section
        saved_label = Gtk.Label(label="保存的搜索")
        saved_label.add_css_class("heading")
        saved_label.set_halign(Gtk.Align.START)
        box.append(saved_label)
        
        self._saved_list = Gtk.ListBox()
        self._saved_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._saved_list.add_css_class("boxed-list")
        self._saved_list.set_placeholder(
            Gtk.Label(label="暂无保存的搜索", css_classes=["dim-label"])
        )
        
        saved_scroll = Gtk.ScrolledWindow()
        saved_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        saved_scroll.set_max_content_height(150)
        saved_scroll.set_child(self._saved_list)
        box.append(saved_scroll)
        
        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        
        save_button = Gtk.Button(label="保存当前搜索")
        save_button.connect("clicked", self._on_save_search)
        button_box.append(save_button)
        
        apply_button = Gtk.Button(label="应用过滤")
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self._on_apply_filters)
        button_box.append(apply_button)
        
        box.append(button_box)
        
        popover.set_child(box)
        return popover
    
    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes with debouncing."""
        # Cancel previous debounce
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        
        # Set up new debounce
        self._debounce_id = GLib.timeout_add(
            self._timeout,
            self._emit_search_changed
        )
    
    def _emit_search_changed(self) -> bool:
        """Emit the search-changed signal."""
        self._debounce_id = None
        text = self._entry.get_text()
        self.emit('search-changed', text)
        return False  # Don't repeat
    
    def _on_search_activated(self, entry: Gtk.SearchEntry) -> None:
        """Handle search activation (Enter key)."""
        # Cancel debounce
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        
        text = entry.get_text()
        
        # Add to history
        if text and text not in self._search_history:
            self._search_history.insert(0, text)
            # Keep only last 20 searches
            self._search_history = self._search_history[:20]
        
        self.emit('search-activated', text)
    
    def _on_stop_search(self, entry: Gtk.SearchEntry) -> None:
        """Handle search stop (Escape key)."""
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        
        entry.set_text("")
        self.emit('search-changed', "")
    
    def _on_save_search(self, button: Gtk.Button) -> None:
        """Save the current search."""
        text = self._entry.get_text()
        if text and text not in self._saved_searches:
            self._saved_searches.append(text)
            self._update_saved_list()
    
    def _on_apply_filters(self, button: Gtk.Button) -> None:
        """Apply advanced filters."""
        filters = self._build_filter_query()
        
        # Combine with current search text
        current = self._entry.get_text().strip()
        if filters:
            if current:
                query = f"{current} AND {filters}"
            else:
                query = filters
            self._entry.set_text(query)
        
        # Close popover
        self._options_button.get_popover().popdown()
        
        # Emit search
        self.emit('search-activated', self._entry.get_text())
    
    def _build_filter_query(self) -> str:
        """Build a query string from the filter options."""
        parts = []
        
        # Duration filter
        duration = self._duration_value.get_value()
        if duration > 0:
            ops = [">", "<", "=", ">=", "<="]
            op = ops[self._duration_op.get_selected()]
            parts.append(f"duration:{op}{int(duration)}")
        
        # Format filter
        format_idx = self._format_dropdown.get_selected()
        if format_idx > 0:
            formats = ["", "wav", "mp3", "flac", "ogg", "m4a", "aiff"]
            parts.append(f"format:{formats[format_idx]}")
        
        # Sample rate filter
        sr_idx = self._sr_dropdown.get_selected()
        if sr_idx > 0:
            rates = ["", "44100", "48000", "96000", "192000"]
            parts.append(f"samplerate:{rates[sr_idx]}")
        
        return " AND ".join(parts)
    
    def _update_saved_list(self) -> None:
        """Update the saved searches list."""
        # Clear existing
        while True:
            row = self._saved_list.get_row_at_index(0)
            if row:
                self._saved_list.remove(row)
            else:
                break
        
        # Add saved searches
        for search in self._saved_searches:
            row = Adw.ActionRow()
            row.set_title(search)
            row.set_activatable(True)
            row.connect("activated", lambda r, s=search: self._load_saved_search(s))
            
            # Delete button
            delete_btn = Gtk.Button()
            delete_btn.set_icon_name("edit-delete-symbolic")
            delete_btn.add_css_class("flat")
            delete_btn.connect("clicked", lambda b, s=search: self._delete_saved_search(s))
            row.add_suffix(delete_btn)
            
            self._saved_list.append(row)
    
    def _load_saved_search(self, search: str) -> None:
        """Load a saved search."""
        self._entry.set_text(search)
        self._options_button.get_popover().popdown()
        self.emit('search-activated', search)
    
    def _delete_saved_search(self, search: str) -> None:
        """Delete a saved search."""
        if search in self._saved_searches:
            self._saved_searches.remove(search)
            self._update_saved_list()
    
    # Public API
    def get_text(self) -> str:
        """Get the current search text."""
        return self._entry.get_text()
    
    def set_text(self, text: str) -> None:
        """Set the search text."""
        self._entry.set_text(text)
    
    def clear(self) -> None:
        """Clear the search."""
        self._entry.set_text("")
    
    def grab_focus(self) -> None:
        """Focus the search entry."""
        self._entry.grab_focus()
    
    def get_saved_searches(self) -> List[str]:
        """Get the list of saved searches."""
        return self._saved_searches.copy()
    
    def set_saved_searches(self, searches: List[str]) -> None:
        """Set the saved searches."""
        self._saved_searches = searches.copy()
        self._update_saved_list()
    
    def get_search_history(self) -> List[str]:
        """Get the search history."""
        return self._search_history.copy()
    
    def set_search_history(self, history: List[str]) -> None:
        """Set the search history."""
        self._search_history = history.copy()
