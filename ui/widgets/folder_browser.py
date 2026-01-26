"""
Folder Browser Widget

A GTK4 tree view for browsing library folders.
Inspired by Quod Libet's file browser but adapted for GTK4.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GObject, Gio, Pango
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False


class FolderObject(GObject.Object):
    """GObject wrapper for folder data."""
    
    __gtype_name__ = 'FolderObject'
    
    def __init__(self, path: str, name: str, file_count: int = 0, 
                 is_root: bool = False):
        super().__init__()
        self._path = path
        self._name = name
        self._file_count = file_count
        self._is_root = is_root
        self._children: List[FolderObject] = []
    
    @GObject.Property(type=str)
    def path(self) -> str:
        return self._path
    
    @GObject.Property(type=str)
    def name(self) -> str:
        return self._name
    
    @GObject.Property(type=int)
    def file_count(self) -> int:
        return self._file_count
    
    @file_count.setter
    def file_count(self, value: int) -> None:
        self._file_count = value
    
    @GObject.Property(type=bool, default=False)
    def is_root(self) -> bool:
        return self._is_root
    
    @property
    def children(self) -> List['FolderObject']:
        return self._children
    
    def add_child(self, child: 'FolderObject') -> None:
        self._children.append(child)


class FolderBrowser(Gtk.Box):
    """
    A folder browser widget for navigating library folders.
    
    Features:
    - Tree view of library folders
    - File count per folder
    - Expand/collapse folders
    - Selection to filter library view
    - Add/remove library folders
    """
    
    __gtype_name__ = 'FolderBrowser'
    
    __gsignals__ = {
        'folder-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'folder-activated': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'add-folder-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'remove-folder-requested': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        if not GTK_AVAILABLE:
            return
        
        self._root_folders: List[str] = []
        self._folder_counts: Dict[str, int] = {}
        self._model: Optional[Gtk.TreeListModel] = None
        self._selection_model: Optional[Gtk.SingleSelection] = None
        self._list_view: Optional[Gtk.ListView] = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Set up the folder browser UI."""
        # Header with title and add button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(12)
        header_box.set_margin_end(6)
        header_box.set_margin_top(12)
        header_box.set_margin_bottom(6)
        
        title = Gtk.Label(label="文件夹")
        title.add_css_class("heading")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        header_box.append(title)
        
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.set_tooltip_text("添加文件夹")
        add_button.connect("clicked", lambda b: self.emit('add-folder-requested'))
        header_box.append(add_button)
        
        self.append(header_box)
        
        # Create root list store
        self._root_store = Gio.ListStore.new(FolderObject)
        
        # Create tree list model
        self._model = Gtk.TreeListModel.new(
            self._root_store,
            passthrough=False,
            autoexpand=False,
            create_func=self._create_children_model
        )
        
        # Create selection model
        self._selection_model = Gtk.SingleSelection.new(self._model)
        self._selection_model.connect("selection-changed", self._on_selection_changed)
        
        # Create factory
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        
        # Create list view
        self._list_view = Gtk.ListView()
        self._list_view.set_model(self._selection_model)
        self._list_view.set_factory(factory)
        self._list_view.add_css_class("navigation-sidebar")
        self._list_view.connect("activate", self._on_item_activated)
        
        # Wrap in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._list_view)
        
        self.append(scrolled)
        
        # Add "All Files" item
        self._add_all_files_item()
    
    def _create_children_model(self, item: GObject.Object) -> Optional[Gio.ListModel]:
        """Create a model for child folders."""
        tree_item = item
        if isinstance(item, Gtk.TreeListRow):
            tree_item = item.get_item()
        
        if not isinstance(tree_item, FolderObject):
            return None
        
        folder = tree_item
        if not folder.children:
            # Scan for subfolders
            self._scan_subfolders(folder)
        
        if folder.children:
            store = Gio.ListStore.new(FolderObject)
            for child in folder.children:
                store.append(child)
            return store
        
        return None
    
    def _scan_subfolders(self, folder: FolderObject) -> None:
        """Scan for subfolders in a folder."""
        try:
            path = Path(folder.path)
            if not path.is_dir():
                return
            
            for item in sorted(path.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    count = self._folder_counts.get(str(item), 0)
                    child = FolderObject(
                        path=str(item),
                        name=item.name,
                        file_count=count
                    )
                    folder.add_child(child)
        except PermissionError:
            logger.warning(f"Permission denied: {folder.path}")
        except Exception as e:
            logger.error(f"Error scanning folder {folder.path}: {e}")
    
    def _add_all_files_item(self) -> None:
        """Add the 'All Files' item at the top."""
        all_files = FolderObject(
            path="",
            name="所有文件",
            file_count=0,
            is_root=True
        )
        self._root_store.append(all_files)
    
    def _on_factory_setup(self, factory: Gtk.SignalListItemFactory,
                          list_item: Gtk.ListItem) -> None:
        """Set up a list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(12)
        
        # Expander for tree structure
        expander = Gtk.TreeExpander()
        box.append(expander)
        
        # Folder icon
        icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        icon.set_pixel_size(16)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content_box.append(icon)
        
        # Folder name
        name_label = Gtk.Label()
        name_label.set_halign(Gtk.Align.START)
        name_label.set_hexpand(True)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        content_box.append(name_label)
        
        # File count badge
        count_label = Gtk.Label()
        count_label.add_css_class("dim-label")
        count_label.add_css_class("caption")
        content_box.append(count_label)
        
        expander.set_child(content_box)
        
        # Store references
        box._expander = expander
        box._icon = icon
        box._name_label = name_label
        box._count_label = count_label
        
        list_item.set_child(box)
    
    def _on_factory_bind(self, factory: Gtk.SignalListItemFactory,
                         list_item: Gtk.ListItem) -> None:
        """Bind data to a list item widget."""
        box = list_item.get_child()
        tree_row: Gtk.TreeListRow = list_item.get_item()
        
        if not tree_row:
            return
        
        folder: FolderObject = tree_row.get_item()
        if not folder:
            return
        
        # Set up expander
        box._expander.set_list_row(tree_row)
        
        # Update icon
        if folder.is_root and not folder.path:
            box._icon.set_from_icon_name("folder-music-symbolic")
        else:
            box._icon.set_from_icon_name("folder-symbolic")
        
        # Update name
        box._name_label.set_text(folder.name)
        
        # Update count
        if folder.file_count > 0:
            box._count_label.set_text(str(folder.file_count))
        else:
            box._count_label.set_text("")
    
    def _on_selection_changed(self, selection: Gtk.SingleSelection,
                              position: int, n_items: int) -> None:
        """Handle selection changes."""
        selected = selection.get_selected_item()
        if selected:
            tree_row = selected
            if isinstance(tree_row, Gtk.TreeListRow):
                folder = tree_row.get_item()
                if folder:
                    self.emit('folder-selected', folder.path)
    
    def _on_item_activated(self, list_view: Gtk.ListView, position: int) -> None:
        """Handle item activation."""
        item = self._selection_model.get_item(position)
        if item:
            tree_row = item
            if isinstance(tree_row, Gtk.TreeListRow):
                folder = tree_row.get_item()
                if folder:
                    self.emit('folder-activated', folder.path)
    
    # Public API
    def add_root_folder(self, path: str) -> None:
        """Add a root folder to the browser."""
        if path in self._root_folders:
            return
        
        self._root_folders.append(path)
        
        folder_path = Path(path)
        if folder_path.exists():
            count = self._folder_counts.get(path, 0)
            folder = FolderObject(
                path=path,
                name=folder_path.name,
                file_count=count,
                is_root=True
            )
            self._root_store.append(folder)
    
    def remove_root_folder(self, path: str) -> None:
        """Remove a root folder from the browser."""
        if path not in self._root_folders:
            return
        
        self._root_folders.remove(path)
        
        # Find and remove from store
        for i in range(self._root_store.get_n_items()):
            item = self._root_store.get_item(i)
            if item and item.path == path:
                self._root_store.remove(i)
                break
    
    def set_folder_counts(self, counts: Dict[str, int]) -> None:
        """Set file counts for folders."""
        self._folder_counts = counts
        
        # Update "All Files" count
        total = sum(counts.values())
        all_files = self._root_store.get_item(0)
        if all_files:
            all_files.file_count = total
        
        # Refresh the view
        n = self._root_store.get_n_items()
        if n > 0:
            self._root_store.items_changed(0, n, n)
    
    def get_selected_folder(self) -> Optional[str]:
        """Get the currently selected folder path."""
        selected = self._selection_model.get_selected_item()
        if selected:
            tree_row = selected
            if isinstance(tree_row, Gtk.TreeListRow):
                folder = tree_row.get_item()
                if folder:
                    return folder.path
        return None
    
    def select_folder(self, path: str) -> None:
        """Select a folder by path."""
        for i in range(self._model.get_n_items()):
            item = self._model.get_item(i)
            if isinstance(item, Gtk.TreeListRow):
                folder = item.get_item()
                if folder and folder.path == path:
                    self._selection_model.select_item(i, True)
                    break
    
    def refresh(self) -> None:
        """Refresh the folder browser."""
        # Clear and rebuild
        paths = self._root_folders.copy()
        self._root_store.remove_all()
        self._root_folders.clear()
        
        self._add_all_files_item()
        
        for path in paths:
            self.add_root_folder(path)
