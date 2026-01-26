"""
Project Sidebar

Sidebar component combining project list and template selection.
"""

import logging
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango

from transcriptionist_v3.domain.models.project import Project
from transcriptionist_v3.application.project_manager import (
    ProjectManager,
    ProjectTemplate,
    ProjectTemplateManager,
)
from .project_list_view import ProjectListView

logger = logging.getLogger(__name__)


class TemplateSelectionView(Gtk.Box):
    """
    View for selecting project templates.
    
    Used in the new project flow and template management.
    """
    
    __gtype_name__ = 'TemplateSelectionView'
    
    __gsignals__ = {
        'template-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'template-activated': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self, template_manager: Optional[ProjectTemplateManager] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self.template_manager = template_manager
        self._selected_template: Optional[ProjectTemplate] = None
        
        self._setup_ui()
        self._load_templates()
    
    def _setup_ui(self) -> None:
        """Set up the UI."""
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(12)
        header.set_margin_bottom(6)
        
        title = Gtk.Label(label='Templates')
        title.add_css_class('heading')
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        header.append(title)
        
        # Manage button
        manage_btn = Gtk.Button.new_from_icon_name('emblem-system-symbolic')
        manage_btn.set_tooltip_text('Manage Templates')
        manage_btn.add_css_class('flat')
        manage_btn.connect('clicked', self._on_manage_clicked)
        header.append(manage_btn)
        
        self.append(header)
        
        # Template list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
        
        scrolled.set_child(self.list_box)
        self.append(scrolled)
    
    def _load_templates(self) -> None:
        """Load templates into the list."""
        if not self.template_manager:
            return
        
        # Clear existing
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        
        # Add built-in templates section
        builtin = self.template_manager.get_builtin()
        if builtin:
            for template in builtin:
                row = self._create_template_row(template)
                self.list_box.append(row)
        
        # Add custom templates section
        custom = self.template_manager.get_custom()
        if custom:
            # Separator
            sep_row = Gtk.ListBoxRow()
            sep_row.set_selectable(False)
            sep_row.set_activatable(False)
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(6)
            sep.set_margin_bottom(6)
            sep_row.set_child(sep)
            self.list_box.append(sep_row)
            
            # Custom header
            header_row = Gtk.ListBoxRow()
            header_row.set_selectable(False)
            header_row.set_activatable(False)
            header_label = Gtk.Label(label='Custom Templates')
            header_label.add_css_class('dim-label')
            header_label.add_css_class('caption')
            header_label.set_halign(Gtk.Align.START)
            header_label.set_margin_start(12)
            header_label.set_margin_top(6)
            header_row.set_child(header_label)
            self.list_box.append(header_row)
            
            for template in custom:
                row = self._create_template_row(template)
                self.list_box.append(row)
    
    def _create_template_row(self, template: ProjectTemplate) -> Gtk.ListBoxRow:
        """Create a row for a template."""
        row = Gtk.ListBoxRow()
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name(template.icon_name)
        icon.set_pixel_size(20)
        box.append(icon)
        
        # Name
        label = Gtk.Label(label=template.name)
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        box.append(label)
        
        row.set_child(box)
        row.template = template  # Store reference
        
        return row
    
    def _on_row_selected(self, list_box: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        """Handle row selection."""
        if row and hasattr(row, 'template'):
            self._selected_template = row.template
            self.emit('template-selected', row.template)
    
    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle row activation."""
        if hasattr(row, 'template'):
            self.emit('template-activated', row.template)
    
    def _on_manage_clicked(self, button: Gtk.Button) -> None:
        """Handle manage templates button click."""
        # TODO: Show template management dialog
        pass
    
    def get_selected_template(self) -> Optional[ProjectTemplate]:
        """Get the currently selected template."""
        return self._selected_template
    
    def refresh(self) -> None:
        """Refresh the template list."""
        self._load_templates()


class ProjectSidebar(Gtk.Box):
    """
    Complete project sidebar with projects and templates.
    
    Features:
    - Project list with CRUD
    - Template selection
    - Quick actions
    """
    
    __gtype_name__ = 'ProjectSidebar'
    
    __gsignals__ = {
        'project-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'project-activated': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'template-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(
        self,
        project_manager: Optional[ProjectManager] = None,
        template_manager: Optional[ProjectTemplateManager] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self.project_manager = project_manager
        self.template_manager = template_manager
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """Set up the sidebar UI."""
        # Stack for switching between views
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        
        # Projects view
        self.project_list = ProjectListView(
            project_manager=self.project_manager,
            template_manager=self.template_manager,
        )
        self.stack.add_titled(self.project_list, 'projects', 'Projects')
        
        # Templates view
        self.template_view = TemplateSelectionView(
            template_manager=self.template_manager,
        )
        self.stack.add_titled(self.template_view, 'templates', 'Templates')
        
        # Stack switcher
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(6)
        switcher.set_margin_bottom(6)
        
        self.append(switcher)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.append(self.stack)
    
    def _connect_signals(self) -> None:
        """Connect signal handlers."""
        self.project_list.connect('project-selected', self._on_project_selected)
        self.project_list.connect('project-activated', self._on_project_activated)
        self.template_view.connect('template-selected', self._on_template_selected)
        self.template_view.connect('template-activated', self._on_template_activated)
    
    def _on_project_selected(self, view, project: Project) -> None:
        """Handle project selection."""
        self.emit('project-selected', project)
    
    def _on_project_activated(self, view, project: Project) -> None:
        """Handle project activation."""
        self.emit('project-activated', project)
    
    def _on_template_selected(self, view, template: ProjectTemplate) -> None:
        """Handle template selection."""
        self.emit('template-selected', template)
    
    def _on_template_activated(self, view, template: ProjectTemplate) -> None:
        """Handle template activation - create new project."""
        self.project_list.show_create_dialog()
    
    # Public API
    
    def refresh(self) -> None:
        """Refresh all views."""
        self.project_list.refresh()
        self.template_view.refresh()
    
    def get_selected_project(self) -> Optional[Project]:
        """Get the currently selected project."""
        return self.project_list.get_selected_project()
    
    def select_project(self, project: Project) -> None:
        """Select a project."""
        self.stack.set_visible_child_name('projects')
        self.project_list.select_project(project)
    
    def show_projects(self) -> None:
        """Switch to projects view."""
        self.stack.set_visible_child_name('projects')
    
    def show_templates(self) -> None:
        """Switch to templates view."""
        self.stack.set_visible_child_name('templates')
