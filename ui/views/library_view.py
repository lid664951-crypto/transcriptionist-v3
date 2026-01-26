"""
Library View

The main library view combining folder browser, audio list, and details panel.
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
    from gi.repository import Gtk, Adw, GObject, Gio, Gdk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

from ..widgets.audio_list_view import AudioListView
from ..widgets.folder_browser import FolderBrowser
from ..widgets.search_bar import SearchBar
from ..widgets.file_details_panel import FileDetailsPanel


class LibraryView(Gtk.Box):
    """
    The main library view for browsing and managing audio files.
    
    Layout:
    - Left: Folder browser sidebar
    - Center: Audio file list with search bar
    - Right: File details panel (collapsible)
    """
    
    __gtype_name__ = 'LibraryView'
    
    __gsignals__ = {
        'play-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'files-imported': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        
        if not GTK_AVAILABLE:
            return
        
        self._all_files: List[Dict[str, Any]] = []
        self._filtered_files: List[Dict[str, Any]] = []
        self._current_folder: Optional[str] = None
        self._current_search: str = ""
        
        # Callbacks
        self._on_play: Optional[Callable[[Dict], None]] = None
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """Set up the library view UI."""
        # Create paned container for resizable panels
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_hexpand(True)
        self._paned.set_vexpand(True)
        
        # Left panel: Folder browser
        self._folder_browser = FolderBrowser()
        self._folder_browser.set_size_request(200, -1)
        self._paned.set_start_child(self._folder_browser)
        self._paned.set_shrink_start_child(False)
        self._paned.set_resize_start_child(False)
        
        # Right side: Content + Details
        right_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        
        # Center: Search bar + Audio list
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Search bar
        self._search_bar = SearchBar()
        center_box.append(self._search_bar)
        
        # Audio list
        self._audio_list = AudioListView()
        self._audio_list.set_hexpand(True)
        self._audio_list.set_vexpand(True)
        center_box.append(self._audio_list)
        
        right_paned.set_start_child(center_box)
        right_paned.set_shrink_start_child(False)
        
        # Right: Details panel
        self._details_panel = FileDetailsPanel()
        self._details_panel.set_size_request(280, -1)
        right_paned.set_end_child(self._details_panel)
        right_paned.set_shrink_end_child(False)
        right_paned.set_resize_end_child(False)
        
        self._paned.set_end_child(right_paned)
        
        self.append(self._paned)
    
    def _connect_signals(self) -> None:
        """Connect widget signals."""
        # Folder browser signals
        self._folder_browser.connect('folder-selected', self._on_folder_selected)
        self._folder_browser.connect('add-folder-requested', self._on_add_folder_requested)
        
        # Search bar signals
        self._search_bar.connect('search-changed', self._on_search_changed)
        self._search_bar.connect('search-activated', self._on_search_activated)
        
        # Audio list signals
        self._audio_list.connect('selection-changed', self._on_selection_changed)
        self._audio_list.connect('file-activated', self._on_file_activated)
        self._audio_list.connect('play-requested', self._on_play_requested)
        self._audio_list.connect('context-menu', self._on_context_menu)
        
        # Details panel signals
        self._details_panel.connect('play-requested', self._on_details_play)
        self._details_panel.connect('show-in-folder', self._on_show_in_folder)
    
    def _on_folder_selected(self, browser: FolderBrowser, path: str) -> None:
        """Handle folder selection."""
        self._current_folder = path if path else None
        self._apply_filters()
    
    def _on_add_folder_requested(self, browser: FolderBrowser) -> None:
        """Handle add folder request."""
        # This should be handled by the parent window
        pass
    
    def _on_search_changed(self, search_bar: SearchBar, text: str) -> None:
        """Handle search text changes."""
        self._current_search = text
        self._apply_filters()
    
    def _on_search_activated(self, search_bar: SearchBar, text: str) -> None:
        """Handle search activation."""
        self._current_search = text
        self._apply_filters()
    
    def _on_selection_changed(self, list_view: AudioListView, 
                              selected: List[Dict]) -> None:
        """Handle selection changes."""
        if selected:
            # Show first selected file in details
            self._details_panel.set_audio_data(selected[0])
        else:
            self._details_panel.clear()
    
    def _on_file_activated(self, list_view: AudioListView, 
                           data: Dict[str, Any]) -> None:
        """Handle file activation (double-click)."""
        self.emit('play-requested', data)
    
    def _on_play_requested(self, list_view: AudioListView,
                           data: Dict[str, Any]) -> None:
        """Handle play request."""
        self.emit('play-requested', data)
    
    def _on_context_menu(self, list_view: AudioListView, data: Dict,
                         x: float, y: float) -> None:
        """Handle context menu request."""
        # Create and show context menu
        menu = Gio.Menu()
        menu.append("播放", "library.play")
        menu.append("在文件夹中显示", "library.show-in-folder")
        menu.append("重命名", "library.rename")
        menu.append("删除", "library.delete")
        
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self._audio_list)
        popover.set_pointing_to(Gdk.Rectangle(int(x), int(y), 1, 1))
        popover.popup()
    
    def _on_details_play(self, panel: FileDetailsPanel) -> None:
        """Handle play request from details panel."""
        data = panel.get_audio_data()
        if data:
            self.emit('play-requested', data)
    
    def _on_show_in_folder(self, panel: FileDetailsPanel) -> None:
        """Handle show in folder request."""
        file_path = panel.file_path
        if file_path:
            # Open file manager at the file location
            import subprocess
            import sys
            
            path = Path(file_path)
            if sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', str(path)])
            elif sys.platform == 'darwin':
                subprocess.run(['open', '-R', str(path)])
            else:
                subprocess.run(['xdg-open', str(path.parent)])
    
    def _apply_filters(self) -> None:
        """Apply folder and search filters to the file list."""
        filtered = self._all_files
        
        # Filter by folder
        if self._current_folder:
            filtered = [
                f for f in filtered
                if f.get('file_path', '').startswith(self._current_folder)
            ]
        
        # Filter by search
        if self._current_search:
            search_lower = self._current_search.lower()
            filtered = [
                f for f in filtered
                if search_lower in f.get('filename', '').lower()
                or search_lower in f.get('title', '').lower()
                or search_lower in str(f.get('file_path', '')).lower()
            ]
        
        self._filtered_files = filtered
        self._audio_list.set_items(filtered)
    
    # Public API
    def set_files(self, files: List[Dict[str, Any]]) -> None:
        """Set the list of audio files."""
        self._all_files = files
        self._apply_filters()
        
        # Update folder counts
        counts = {}
        for f in files:
            path = f.get('file_path', '')
            if path:
                folder = str(Path(path).parent)
                counts[folder] = counts.get(folder, 0) + 1
        
        self._folder_browser.set_folder_counts(counts)
    
    def add_file(self, file_data: Dict[str, Any]) -> None:
        """Add a single file."""
        self._all_files.append(file_data)
        self._apply_filters()
    
    def remove_file(self, file_path: str) -> None:
        """Remove a file by path."""
        self._all_files = [f for f in self._all_files 
                          if f.get('file_path') != file_path]
        self._apply_filters()
    
    def add_library_folder(self, path: str) -> None:
        """Add a library folder."""
        self._folder_browser.add_root_folder(path)
    
    def remove_library_folder(self, path: str) -> None:
        """Remove a library folder."""
        self._folder_browser.remove_root_folder(path)
    
    def set_playing(self, file_path: Optional[str]) -> None:
        """Set the currently playing file."""
        self._audio_list.set_playing(file_path)
    
    def get_selected_files(self) -> List[Dict[str, Any]]:
        """Get selected files."""
        return self._audio_list.get_selected_items()
    
    def select_file(self, file_path: str) -> None:
        """Select a file by path."""
        self._audio_list.select_by_path(file_path)
    
    def focus_search(self) -> None:
        """Focus the search bar."""
        self._search_bar.grab_focus()
    
    def clear_search(self) -> None:
        """Clear the search."""
        self._search_bar.clear()
        self._current_search = ""
        self._apply_filters()
    
    def refresh(self) -> None:
        """Refresh the view."""
        self._apply_filters()
        self._folder_browser.refresh()
    
    def reload_from_database(self) -> None:
        """从数据库重新加载所有数据"""
        # 这个方法需要从数据库重新查询所有文件
        # 由于这个方法需要访问数据库，应该由父组件（page）来实现
        # 这里只是提供一个接口
        pass
