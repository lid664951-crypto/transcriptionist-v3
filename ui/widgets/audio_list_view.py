"""
Audio List View Widget

A GTK4 ListView for displaying audio files with virtual scrolling.
Inspired by Quod Libet's SongList but using GTK4's modern ListView.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GObject, Gio, GLib, Pango
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False


class AudioFileObject(GObject.Object):
    """GObject wrapper for audio file data."""
    
    __gtype_name__ = 'AudioFileObject'
    
    def __init__(self, data: Dict[str, Any]):
        super().__init__()
        self._data = data
    
    @GObject.Property(type=str)
    def file_path(self) -> str:
        return self._data.get('file_path', '')
    
    @GObject.Property(type=str)
    def filename(self) -> str:
        return self._data.get('filename', '')
    
    @GObject.Property(type=str)
    def title(self) -> str:
        return self._data.get('title') or self._data.get('filename', '')
    
    @GObject.Property(type=float)
    def duration(self) -> float:
        return self._data.get('duration', 0.0)
    
    @GObject.Property(type=int)
    def sample_rate(self) -> int:
        return self._data.get('sample_rate', 0)
    
    @GObject.Property(type=str)
    def format(self) -> str:
        return self._data.get('format', '')
    
    @GObject.Property(type=int)
    def file_size(self) -> int:
        return self._data.get('file_size', 0)
    
    @property
    def data(self) -> Dict[str, Any]:
        return self._data


def format_duration(seconds: float) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if seconds < 0:
        return "0:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class AudioListView(Gtk.Box):
    """
    A list view for displaying audio files with virtual scrolling.
    
    Features:
    - Virtual scrolling for large libraries
    - Column sorting
    - Multi-selection
    - Drag and drop
    - Context menu
    - Keyboard navigation
    """
    
    __gtype_name__ = 'AudioListView'
    
    __gsignals__ = {
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'file-activated': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'play-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'context-menu': (GObject.SignalFlags.RUN_FIRST, None, (object, float, float)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        if not GTK_AVAILABLE:
            return
        
        self._model: Optional[Gio.ListStore] = None
        self._selection_model: Optional[Gtk.MultiSelection] = None
        self._list_view: Optional[Gtk.ListView] = None
        self._playing_path: Optional[str] = None
        
        # Callbacks
        self._on_play: Optional[Callable[[Dict], None]] = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Set up the list view UI."""
        # Create list store
        self._model = Gio.ListStore.new(AudioFileObject)
        
        # Create selection model (multi-selection)
        self._selection_model = Gtk.MultiSelection.new(self._model)
        self._selection_model.connect("selection-changed", self._on_selection_changed)
        
        # Create factory for list items
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        
        # Create list view
        self._list_view = Gtk.ListView()
        self._list_view.set_model(self._selection_model)
        self._list_view.set_factory(factory)
        self._list_view.set_single_click_activate(False)
        self._list_view.add_css_class("audio-list")
        
        # Connect signals
        self._list_view.connect("activate", self._on_item_activated)
        
        # Set up keyboard navigation
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self._list_view.add_controller(key_controller)
        
        # Wrap in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._list_view)
        
        self.append(scrolled)
        
        # Status bar
        self._status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._status_bar.set_margin_start(12)
        self._status_bar.set_margin_end(12)
        self._status_bar.set_margin_top(6)
        self._status_bar.set_margin_bottom(6)
        
        self._count_label = Gtk.Label()
        self._count_label.add_css_class("dim-label")
        self._count_label.add_css_class("caption")
        self._status_bar.append(self._count_label)
        
        self._duration_label = Gtk.Label()
        self._duration_label.add_css_class("dim-label")
        self._duration_label.add_css_class("caption")
        self._status_bar.append(self._duration_label)
        
        self.append(self._status_bar)
        
        self._update_status()
    
    def _on_factory_setup(self, factory: Gtk.SignalListItemFactory, 
                          list_item: Gtk.ListItem) -> None:
        """Set up a list item widget."""
        # Create row widget
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.set_margin_start(12)
        row.set_margin_end(12)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon.set_pixel_size(20)
        icon.add_css_class("dim-label")
        row.append(icon)
        
        # Info box
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        title_label = Gtk.Label()
        title_label.set_halign(Gtk.Align.START)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        info_box.append(title_label)
        
        subtitle_label = Gtk.Label()
        subtitle_label.set_halign(Gtk.Align.START)
        subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle_label.add_css_class("dim-label")
        subtitle_label.add_css_class("caption")
        info_box.append(subtitle_label)
        
        row.append(info_box)
        
        # Sample rate
        sr_label = Gtk.Label()
        sr_label.add_css_class("dim-label")
        sr_label.add_css_class("caption")
        sr_label.set_width_chars(6)
        row.append(sr_label)
        
        # Format badge
        format_label = Gtk.Label()
        format_label.add_css_class("caption")
        format_label.set_width_chars(5)
        row.append(format_label)
        
        # Duration
        duration_label = Gtk.Label()
        duration_label.set_width_chars(7)
        duration_label.set_halign(Gtk.Align.END)
        duration_label.add_css_class("numeric")
        row.append(duration_label)
        
        # Store references
        row._icon = icon
        row._title_label = title_label
        row._subtitle_label = subtitle_label
        row._sr_label = sr_label
        row._format_label = format_label
        row._duration_label = duration_label
        
        # Right-click gesture
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.connect("released", self._on_row_right_click, list_item)
        row.add_controller(right_click)
        
        list_item.set_child(row)
    
    def _on_factory_bind(self, factory: Gtk.SignalListItemFactory,
                         list_item: Gtk.ListItem) -> None:
        """Bind data to a list item widget."""
        row = list_item.get_child()
        item: AudioFileObject = list_item.get_item()
        
        if not item:
            return
        
        data = item.data
        
        # Update title
        title = data.get('title') or data.get('filename', 'Unknown')
        row._title_label.set_text(title)
        
        # Update subtitle (folder)
        file_path = data.get('file_path', '')
        if file_path:
            folder = Path(file_path).parent.name
            row._subtitle_label.set_text(folder)
        
        # Update sample rate
        sr = data.get('sample_rate', 0)
        if sr:
            sr_text = f"{sr // 1000}kHz" if sr >= 1000 else f"{sr}Hz"
            row._sr_label.set_text(sr_text)
        else:
            row._sr_label.set_text("")
        
        # Update format
        fmt = data.get('format', '').upper()
        row._format_label.set_text(fmt)
        
        # Update duration
        duration = data.get('duration', 0)
        row._duration_label.set_text(format_duration(duration))
        
        # Update playing state
        is_playing = file_path == self._playing_path
        if is_playing:
            row._icon.set_from_icon_name("media-playback-start-symbolic")
            row._icon.remove_css_class("dim-label")
            row._icon.add_css_class("accent")
        else:
            row._icon.set_from_icon_name("audio-x-generic-symbolic")
            row._icon.remove_css_class("accent")
            row._icon.add_css_class("dim-label")
    
    def _on_factory_unbind(self, factory: Gtk.SignalListItemFactory,
                           list_item: Gtk.ListItem) -> None:
        """Unbind data from a list item widget."""
        pass
    
    def _on_row_right_click(self, gesture: Gtk.GestureClick, n_press: int,
                            x: float, y: float, list_item: Gtk.ListItem) -> None:
        """Handle right-click on a row."""
        item = list_item.get_item()
        if item:
            self.emit('context-menu', item.data, x, y)
    
    def _on_selection_changed(self, selection: Gtk.MultiSelection,
                              position: int, n_items: int) -> None:
        """Handle selection changes."""
        selected = self.get_selected_items()
        self.emit('selection-changed', selected)
    
    def _on_item_activated(self, list_view: Gtk.ListView, position: int) -> None:
        """Handle item activation (double-click or Enter)."""
        item = self._model.get_item(position)
        if item:
            self.emit('file-activated', item.data)
            self.emit('play-requested', item.data)
    
    def _on_key_pressed(self, controller: Gtk.EventControllerKey,
                        keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle keyboard events."""
        # Space to play/pause
        if keyval == Gdk.KEY_space:
            selected = self.get_selected_items()
            if selected:
                self.emit('play-requested', selected[0])
            return True
        
        # Delete to remove from selection (not implemented yet)
        if keyval == Gdk.KEY_Delete:
            return True
        
        # Ctrl+A to select all
        if keyval == Gdk.KEY_a and state & Gdk.ModifierType.CONTROL_MASK:
            self._selection_model.select_all()
            return True
        
        return False
    
    def _update_status(self) -> None:
        """Update the status bar."""
        count = self._model.get_n_items() if self._model else 0
        self._count_label.set_text(f"{count} 个文件")
        
        # Calculate total duration
        total_duration = 0.0
        for i in range(count):
            item = self._model.get_item(i)
            if item:
                total_duration += item.duration
        
        self._duration_label.set_text(f"总时长: {format_duration(total_duration)}")
    
    # Public API
    def set_items(self, items: List[Dict[str, Any]]) -> None:
        """Set the list items."""
        if not self._model:
            return
        
        self._model.remove_all()
        for item_data in items:
            obj = AudioFileObject(item_data)
            self._model.append(obj)
        
        self._update_status()
    
    def add_item(self, item_data: Dict[str, Any]) -> None:
        """Add a single item."""
        if self._model:
            obj = AudioFileObject(item_data)
            self._model.append(obj)
            self._update_status()
    
    def remove_item(self, file_path: str) -> None:
        """Remove an item by file path."""
        if not self._model:
            return
        
        for i in range(self._model.get_n_items()):
            item = self._model.get_item(i)
            if item and item.file_path == file_path:
                self._model.remove(i)
                break
        
        self._update_status()
    
    def clear(self) -> None:
        """Clear all items."""
        if self._model:
            self._model.remove_all()
            self._update_status()
    
    def get_selected_items(self) -> List[Dict[str, Any]]:
        """Get selected items."""
        if not self._selection_model:
            return []
        
        selected = []
        bitset = self._selection_model.get_selection()
        
        iter_val = Gtk.BitsetIter()
        valid, pos = bitset.init_first(iter_val)
        while valid:
            item = self._model.get_item(pos)
            if item:
                selected.append(item.data)
            valid, pos = iter_val.next()
        
        return selected
    
    def select_by_path(self, file_path: str) -> None:
        """Select an item by file path."""
        if not self._model or not self._selection_model:
            return
        
        for i in range(self._model.get_n_items()):
            item = self._model.get_item(i)
            if item and item.file_path == file_path:
                self._selection_model.select_item(i, True)
                # Scroll to item
                self._list_view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
                break
    
    def set_playing(self, file_path: Optional[str]) -> None:
        """Set the currently playing file."""
        self._playing_path = file_path
        # Force refresh of visible items
        if self._model:
            # Trigger a refresh by emitting items-changed
            n = self._model.get_n_items()
            if n > 0:
                self._model.items_changed(0, n, n)
    
    def get_item_count(self) -> int:
        """Get the number of items."""
        return self._model.get_n_items() if self._model else 0
    
    def get_all_items(self) -> List[Dict[str, Any]]:
        """Get all items."""
        if not self._model:
            return []
        
        items = []
        for i in range(self._model.get_n_items()):
            item = self._model.get_item(i)
            if item:
                items.append(item.data)
        return items
    
    def reload_items(self, items: List[Dict[str, Any]]) -> None:
        """
        重新加载所有项目（用于批量操作后刷新）
        
        这个方法会清空当前列表并重新加载，确保显示最新的数据
        """
        self.set_items(items)
