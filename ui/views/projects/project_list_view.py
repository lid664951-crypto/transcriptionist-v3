"""
Project List View

Main view for displaying and managing projects.
Inspired by Quod Libet's PlaylistsBrowser.
"""

import logging
from typing import Callable, List, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, Pango, GLib

from transcriptionist_v3.domain.models.project import Project
from transcriptionist_v3.application.project_manager import (
    ProjectManager,
    ProjectTemplate,
    ProjectTemplateManager,
)

logger = logging.getLogger(__name__)


class ProjectRow(Gtk.Box):
    """A row widget for displaying a project in the list."""
    
    __gtype_name__ = 'ProjectRow'
    
    def __init__(self, project: Project):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.project = project
        self.add_css_class('project-row')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name('folder-symbolic')
        icon.set_pixel_size(24)
        self.append(icon)
        
        # Info box
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        # Name
        self.name_label = Gtk.Label(label=project.name)
        self.name_label.set_halign(Gtk.Align.START)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.add_css_class('heading')
        info_box.append(self.name_label)
        
        # Description / file count
        desc = project.description or f'{project.file_count} files'
        self.desc_label = Gtk.Label(label=desc)
        self.desc_label.set_halign(Gtk.Align.START)
        self.desc_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.desc_label.add_css_class('dim-label')
        self.desc_label.add_css_class('caption')
        info_box.append(self.desc_label)
        
        self.append(info_box)
        
        # File count badge
        count_label = Gtk.Label(label=str(project.file_count))
        count_label.add_css_class('badge')
        count_label.set_valign(Gtk.Align.CENTER)
        self.append(count_label)
    
    def update(self, project: Project) -> None:
        """Update the row with new project data."""
        self.project = project
        self.name_label.set_label(project.name)
        desc = project.description or f'{project.file_count} files'
        self.desc_label.set_label(desc)


class ProjectListView(Gtk.Box):
    """
    Main project list view with sidebar navigation.
    
    Features:
    - Project list with selection
    - New/Import/Delete actions
    - Search filtering
    - Drag and drop support
    """
    
    __gtype_name__ = 'ProjectListView'
    
    __gsignals__ = {
        'project-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'project-activated': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'files-dropped': (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
    }
    
    def __init__(
        self,
        project_manager: Optional[ProjectManager] = None,
        template_manager: Optional[ProjectTemplateManager] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self.project_manager = project_manager
        self.template_manager = template_manager
        self._projects: List[Project] = []
        self._filter_text = ''
        
        self._setup_ui()
        self._connect_signals()
        
        # Load projects if manager available
        if project_manager:
            self.refresh()
    
    def _setup_ui(self) -> None:
        """Set up the UI components."""
        # Header with search and actions
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(6)
        header_box.set_margin_end(6)
        header_box.set_margin_top(6)
        header_box.set_margin_bottom(6)
        
        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text('Search projects...')
        self.search_entry.set_hexpand(True)
        header_box.append(self.search_entry)
        
        # New project button
        self.new_button = Gtk.Button.new_from_icon_name('list-add-symbolic')
        self.new_button.set_tooltip_text('New Project')
        self.new_button.add_css_class('flat')
        header_box.append(self.new_button)
        
        # Menu button
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_icon_name('view-more-symbolic')
        self.menu_button.add_css_class('flat')
        self._setup_menu()
        header_box.append(self.menu_button)
        
        self.append(header_box)
        
        # Separator
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Project list
        self._setup_list()
    
    def _setup_list(self) -> None:
        """Set up the project list."""
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # List box
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.set_filter_func(self._filter_func)
        
        # Placeholder for empty state
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_margin_top(24)
        placeholder.set_margin_bottom(24)
        
        icon = Gtk.Image.new_from_icon_name('folder-symbolic')
        icon.set_pixel_size(48)
        icon.add_css_class('dim-label')
        placeholder.append(icon)
        
        label = Gtk.Label(label='No Projects')
        label.add_css_class('dim-label')
        label.add_css_class('title-2')
        placeholder.append(label)
        
        hint = Gtk.Label(label='Click + to create a new project')
        hint.add_css_class('dim-label')
        placeholder.append(hint)
        
        self.list_box.set_placeholder(placeholder)
        
        scrolled.set_child(self.list_box)
        self.append(scrolled)
    
    def _setup_menu(self) -> None:
        """Set up the menu button menu."""
        menu = Gio.Menu()
        
        # Import section
        import_section = Gio.Menu()
        import_section.append('Import Project...', 'project.import')
        menu.append_section(None, import_section)
        
        # Actions section
        actions_section = Gio.Menu()
        actions_section.append('Rename', 'project.rename')
        actions_section.append('Duplicate', 'project.duplicate')
        actions_section.append('Export...', 'project.export')
        menu.append_section(None, actions_section)
        
        # Delete section
        delete_section = Gio.Menu()
        delete_section.append('Delete', 'project.delete')
        menu.append_section(None, delete_section)
        
        self.menu_button.set_menu_model(menu)
    
    def _connect_signals(self) -> None:
        """Connect signal handlers."""
        self.search_entry.connect('search-changed', self._on_search_changed)
        self.new_button.connect('clicked', self._on_new_clicked)
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
    
    def _filter_func(self, row: Gtk.ListBoxRow) -> bool:
        """Filter function for the list box."""
        if not self._filter_text:
            return True
        
        child = row.get_child()
        if isinstance(child, ProjectRow):
            project = child.project
            search = self._filter_text.lower()
            return (
                search in project.name.lower() or
                search in (project.description or '').lower()
            )
        return True
    
    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes."""
        self._filter_text = entry.get_text()
        self.list_box.invalidate_filter()
    
    def _on_new_clicked(self, button: Gtk.Button) -> None:
        """Handle new project button click."""
        self.show_create_dialog()
    
    def _on_row_selected(self, list_box: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        """Handle row selection."""
        if row:
            child = row.get_child()
            if isinstance(child, ProjectRow):
                self.emit('project-selected', child.project)
    
    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle row activation (double-click)."""
        child = row.get_child()
        if isinstance(child, ProjectRow):
            self.emit('project-activated', child.project)
    
    # Public API
    
    def refresh(self) -> None:
        """Refresh the project list from the manager."""
        if not self.project_manager:
            return
        
        self._projects = self.project_manager.get_all_projects()
        self._populate_list()
    
    def _populate_list(self) -> None:
        """Populate the list box with projects."""
        # Clear existing rows
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        
        # Add project rows
        for project in self._projects:
            row = ProjectRow(project)
            self.list_box.append(row)
    
    def get_selected_project(self) -> Optional[Project]:
        """Get the currently selected project."""
        row = self.list_box.get_selected_row()
        if row:
            child = row.get_child()
            if isinstance(child, ProjectRow):
                return child.project
        return None
    
    def select_project(self, project: Project) -> None:
        """Select a project in the list."""
        for i in range(1000):  # Safety limit
            row = self.list_box.get_row_at_index(i)
            if row is None:
                break
            child = row.get_child()
            if isinstance(child, ProjectRow) and child.project.id == project.id:
                self.list_box.select_row(row)
                break
    
    def show_create_dialog(self) -> None:
        """Show the project creation dialog."""
        from ..dialogs.project_creation_dialog import ProjectCreationDialog
        
        window = self.get_root()
        dialog = ProjectCreationDialog(
            parent=window,
            template_manager=self.template_manager,
        )
        dialog.connect('response', self._on_create_dialog_response)
        dialog.present()
    
    def _on_create_dialog_response(self, dialog, response: str) -> None:
        """Handle create dialog response."""
        if response == 'create' and self.project_manager:
            name = dialog.get_project_name()
            description = dialog.get_project_description()
            template = dialog.get_selected_template()
            
            if template:
                project = template.create_project(name)
                project.description = description
            else:
                project = Project(name=name, description=description)
            
            self.project_manager.create_project(project)
            self.refresh()
            self.select_project(project)
        
        dialog.close()
