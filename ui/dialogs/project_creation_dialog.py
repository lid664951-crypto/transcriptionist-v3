"""
Project Creation Dialog

Dialog for creating new projects with template selection.
"""

import logging
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango

from transcriptionist_v3.application.project_manager import ProjectTemplate, ProjectTemplateManager

logger = logging.getLogger(__name__)


class TemplateCard(Gtk.Box):
    """A card widget for displaying a template option."""
    
    def __init__(self, template: ProjectTemplate):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.template = template
        
        self.add_css_class('card')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        
        # Content box with padding
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        
        # Icon
        icon = Gtk.Image.new_from_icon_name(template.icon_name)
        icon.set_pixel_size(32)
        icon.set_halign(Gtk.Align.CENTER)
        content.append(icon)
        
        # Name
        name_label = Gtk.Label(label=template.name)
        name_label.add_css_class('heading')
        name_label.set_halign(Gtk.Align.CENTER)
        content.append(name_label)
        
        # Description
        if template.description:
            desc_label = Gtk.Label(label=template.description)
            desc_label.add_css_class('dim-label')
            desc_label.add_css_class('caption')
            desc_label.set_halign(Gtk.Align.CENTER)
            desc_label.set_wrap(True)
            desc_label.set_max_width_chars(20)
            desc_label.set_justify(Gtk.Justification.CENTER)
            content.append(desc_label)
        
        self.append(content)


class ProjectCreationDialog(Adw.Dialog):
    """
    Dialog for creating a new project.
    
    Features:
    - Template selection grid
    - Project name and description input
    - Validation
    """
    
    __gtype_name__ = 'ProjectCreationDialog'
    
    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        template_manager: Optional[ProjectTemplateManager] = None,
    ):
        super().__init__()
        
        self.template_manager = template_manager
        self._selected_template: Optional[ProjectTemplate] = None
        
        self.set_title('New Project')
        self.set_content_width(500)
        self.set_content_height(600)
        
        self._setup_ui()
        self._load_templates()
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        # Main content
        content = Adw.ToolbarView()
        
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        
        # Cancel button
        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', self._on_cancel)
        header.pack_start(cancel_btn)
        
        # Create button
        self.create_btn = Gtk.Button(label='Create')
        self.create_btn.add_css_class('suggested-action')
        self.create_btn.set_sensitive(False)
        self.create_btn.connect('clicked', self._on_create)
        header.pack_end(self.create_btn)
        
        content.add_top_bar(header)
        
        # Scrolled content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(24)
        main_box.set_margin_bottom(24)
        
        # Project info section
        info_group = Adw.PreferencesGroup()
        info_group.set_title('Project Information')
        
        # Name entry
        self.name_row = Adw.EntryRow()
        self.name_row.set_title('Name')
        self.name_row.connect('changed', self._on_name_changed)
        info_group.add(self.name_row)
        
        # Description entry
        self.desc_row = Adw.EntryRow()
        self.desc_row.set_title('Description')
        info_group.add(self.desc_row)
        
        main_box.append(info_group)
        
        # Template section
        template_group = Adw.PreferencesGroup()
        template_group.set_title('Template')
        template_group.set_description('Choose a template to start with')
        
        # Template grid
        self.template_flow = Gtk.FlowBox()
        self.template_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.template_flow.set_homogeneous(True)
        self.template_flow.set_max_children_per_line(3)
        self.template_flow.set_min_children_per_line(2)
        self.template_flow.set_column_spacing(12)
        self.template_flow.set_row_spacing(12)
        self.template_flow.connect('child-activated', self._on_template_selected)
        
        template_group.add(self.template_flow)
        main_box.append(template_group)
        
        scrolled.set_child(main_box)
        content.set_content(scrolled)
        
        self.set_child(content)
    
    def _load_templates(self) -> None:
        """Load templates into the grid."""
        if not self.template_manager:
            return
        
        templates = self.template_manager.get_all()
        for template in templates:
            card = TemplateCard(template)
            self.template_flow.append(card)
        
        # Select first template by default
        first = self.template_flow.get_child_at_index(0)
        if first:
            self.template_flow.select_child(first)
            child = first.get_child()
            if isinstance(child, TemplateCard):
                self._selected_template = child.template
    
    def _on_name_changed(self, row: Adw.EntryRow) -> None:
        """Handle name entry changes."""
        name = row.get_text().strip()
        self.create_btn.set_sensitive(bool(name))
    
    def _on_template_selected(self, flow: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        """Handle template selection."""
        card = child.get_child()
        if isinstance(card, TemplateCard):
            self._selected_template = card.template
    
    def _on_cancel(self, button: Gtk.Button) -> None:
        """Handle cancel button click."""
        self.emit('response', 'cancel')
    
    def _on_create(self, button: Gtk.Button) -> None:
        """Handle create button click."""
        self.emit('response', 'create')
    
    # Public API
    
    def get_project_name(self) -> str:
        """Get the entered project name."""
        return self.name_row.get_text().strip()
    
    def get_project_description(self) -> str:
        """Get the entered project description."""
        return self.desc_row.get_text().strip()
    
    def get_selected_template(self) -> Optional[ProjectTemplate]:
        """Get the selected template."""
        return self._selected_template
