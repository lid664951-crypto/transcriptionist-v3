"""
Project Files View

View for displaying and managing files within a project.
Inspired by Quod Libet's song list patterns.
"""

import logging
from typing import Callable, List, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, Pango, Gdk, GLib

from transcriptionist_v3.domain.models.project import Project
from transcriptionist_v3.domain.models.audio_file import AudioFile

logger = logging.getLogger(__name__)


class AudioFileRow(Gtk.Box):
    """A row widget for displaying an audio file in the project."""
    
    def __init__(self, audio_file: AudioFile):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.audio_file = audio_file
        
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        
        # Play indicator / checkbox
        self.check = Gtk.CheckButton()
        self.check.set_valign(Gtk.Align.CENTER)
        self.append(self.check)
        
        # File icon based on format
        icon_name = self._get_icon_for_format(audio_file.format)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(24)
        self.append(icon)
        
        # Info box
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        # Filename
        self.name_label = Gtk.Label(label=audio_file.filename)
        self.name_label.set_halign(Gtk.Align.START)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        info_box.append(self.name_label)
        
        # Metadata line
        meta_parts = []
        if audio_file.duration:
            meta_parts.append(self._format_duration(audio_file.duration))
        if audio_file.sample_rate:
            meta_parts.append(f'{audio_file.sample_rate // 1000}kHz')
        if audio_file.channels:
            meta_parts.append('Stereo' if audio_file.channels == 2 else 'Mono')
        
        meta_text = ' • '.join(meta_parts) if meta_parts else ''
        self.meta_label = Gtk.Label(label=meta_text)
        self.meta_label.set_halign(Gtk.Align.START)
        self.meta_label.add_css_class('dim-label')
        self.meta_label.add_css_class('caption')
        info_box.append(self.meta_label)
        
        self.append(info_box)
        
        # Duration label
        if audio_file.duration:
            duration_label = Gtk.Label(label=self._format_duration(audio_file.duration))
            duration_label.add_css_class('dim-label')
            duration_label.set_valign(Gtk.Align.CENTER)
            self.append(duration_label)
    
    def _get_icon_for_format(self, format_str: Optional[str]) -> str:
        """Get icon name for audio format."""
        format_icons = {
            'wav': 'audio-x-generic-symbolic',
            'flac': 'audio-x-generic-symbolic',
            'mp3': 'audio-x-generic-symbolic',
            'ogg': 'audio-x-generic-symbolic',
            'aiff': 'audio-x-generic-symbolic',
            'm4a': 'audio-x-generic-symbolic',
        }
        return format_icons.get(format_str or '', 'audio-x-generic-symbolic')
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to MM:SS."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f'{mins}:{secs:02d}'


class ProjectFilesView(Gtk.Box):
    """
    View for displaying files in a project.
    
    Features:
    - File list with selection
    - Add/Remove files
    - Drag and drop reordering
    - Search filtering
    - Batch operations
    """
    
    __gtype_name__ = 'ProjectFilesView'
    
    __gsignals__ = {
        'file-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'file-activated': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'files-removed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self._project: Optional[Project] = None
        self._files: List[AudioFile] = []
        self._filter_text = ''
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """Set up the UI components."""
        # Header
        header = self._create_header()
        self.append(header)
        
        # Separator
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Toolbar
        toolbar = self._create_toolbar()
        self.append(toolbar)
        
        # File list
        self._setup_list()
        
        # Status bar
        self.status_bar = self._create_status_bar()
        self.append(self.status_bar)
    
    def _create_header(self) -> Gtk.Box:
        """Create the header with project info."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(12)
        header.set_margin_bottom(12)
        
        # Project icon
        icon = Gtk.Image.new_from_icon_name('folder-symbolic')
        icon.set_pixel_size(32)
        header.append(icon)
        
        # Project info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        self.title_label = Gtk.Label(label='No Project Selected')
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.add_css_class('title-2')
        info_box.append(self.title_label)
        
        self.subtitle_label = Gtk.Label(label='Select a project to view files')
        self.subtitle_label.set_halign(Gtk.Align.START)
        self.subtitle_label.add_css_class('dim-label')
        info_box.append(self.subtitle_label)
        
        header.append(info_box)
        
        # Export button
        self.export_btn = Gtk.Button.new_from_icon_name('document-save-symbolic')
        self.export_btn.set_tooltip_text('Export Project')
        self.export_btn.add_css_class('flat')
        self.export_btn.set_sensitive(False)
        header.append(self.export_btn)
        
        return header
    
    def _create_toolbar(self) -> Gtk.Box:
        """Create the toolbar with actions."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        
        # Add files button
        self.add_btn = Gtk.Button()
        add_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_content.append(Gtk.Image.new_from_icon_name('list-add-symbolic'))
        add_content.append(Gtk.Label(label='Add Files'))
        self.add_btn.set_child(add_content)
        self.add_btn.set_sensitive(False)
        toolbar.append(self.add_btn)
        
        # Remove button
        self.remove_btn = Gtk.Button.new_from_icon_name('list-remove-symbolic')
        self.remove_btn.set_tooltip_text('Remove Selected')
        self.remove_btn.set_sensitive(False)
        toolbar.append(self.remove_btn)
        
        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)
        
        # Search
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text('Filter files...')
        self.search_entry.set_width_chars(20)
        toolbar.append(self.search_entry)
        
        return toolbar
    
    def _setup_list(self) -> None:
        """Set up the file list."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # List box
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.list_box.set_filter_func(self._filter_func)
        
        # Placeholder
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_margin_top(48)
        placeholder.set_margin_bottom(48)
        
        icon = Gtk.Image.new_from_icon_name('audio-x-generic-symbolic')
        icon.set_pixel_size(48)
        icon.add_css_class('dim-label')
        placeholder.append(icon)
        
        label = Gtk.Label(label='No Files')
        label.add_css_class('dim-label')
        label.add_css_class('title-3')
        placeholder.append(label)
        
        hint = Gtk.Label(label='Add files to this project or drag and drop')
        hint.add_css_class('dim-label')
        placeholder.append(hint)
        
        self.list_box.set_placeholder(placeholder)
        
        scrolled.set_child(self.list_box)
        self.append(scrolled)
        
        # Set up drag and drop
        self._setup_dnd()
    
    def _setup_dnd(self) -> None:
        """Set up drag and drop for file import."""
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect('drop', self._on_drop)
        self.list_box.add_controller(drop_target)
    
    def _create_status_bar(self) -> Gtk.Box:
        """Create the status bar."""
        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status.set_margin_start(12)
        status.set_margin_end(12)
        status.set_margin_top(6)
        status.set_margin_bottom(6)
        status.add_css_class('dim-label')
        
        self.file_count_label = Gtk.Label(label='0 files')
        status.append(self.file_count_label)
        
        self.duration_label = Gtk.Label(label='')
        status.append(self.duration_label)
        
        self.size_label = Gtk.Label(label='')
        status.append(self.size_label)
        
        return status
    
    def _connect_signals(self) -> None:
        """Connect signal handlers."""
        self.search_entry.connect('search-changed', self._on_search_changed)
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
        self.add_btn.connect('clicked', self._on_add_clicked)
        self.remove_btn.connect('clicked', self._on_remove_clicked)
        self.export_btn.connect('clicked', self._on_export_clicked)
    
    def _filter_func(self, row: Gtk.ListBoxRow) -> bool:
        """Filter function for the list."""
        if not self._filter_text:
            return True
        
        child = row.get_child()
        if isinstance(child, AudioFileRow):
            return self._filter_text.lower() in child.audio_file.filename.lower()
        return True
    
    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes."""
        self._filter_text = entry.get_text()
        self.list_box.invalidate_filter()
    
    def _on_row_selected(self, list_box: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        """Handle row selection."""
        selected = self.get_selected_files()
        self.remove_btn.set_sensitive(bool(selected))
        self.emit('selection-changed', selected)
        
        if row:
            child = row.get_child()
            if isinstance(child, AudioFileRow):
                self.emit('file-selected', child.audio_file)
    
    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle row activation."""
        child = row.get_child()
        if isinstance(child, AudioFileRow):
            self.emit('file-activated', child.audio_file)
    
    def _on_add_clicked(self, button: Gtk.Button) -> None:
        """Handle add files button click."""
        self._show_file_chooser()
    
    def _on_remove_clicked(self, button: Gtk.Button) -> None:
        """Handle remove button click."""
        selected = self.get_selected_files()
        if selected:
            self.emit('files-removed', selected)
    
    def _on_export_clicked(self, button: Gtk.Button) -> None:
        """Handle export button click."""
        if self._project:
            self.show_export_wizard()
    
    def _on_drop(self, target: Gtk.DropTarget, value, x: float, y: float) -> bool:
        """Handle file drop."""
        if isinstance(value, Gio.File):
            # Handle single file
            logger.info(f"File dropped: {value.get_path()}")
            return True
        return False
    
    def _show_file_chooser(self) -> None:
        """Show file chooser for adding files."""
        dialog = Gtk.FileDialog()
        dialog.set_title('Add Files to Project')
        
        # Set up filters
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        audio_filter = Gtk.FileFilter()
        audio_filter.set_name('Audio Files')
        audio_filter.add_mime_type('audio/*')
        audio_filter.add_pattern('*.wav')
        audio_filter.add_pattern('*.flac')
        audio_filter.add_pattern('*.mp3')
        audio_filter.add_pattern('*.ogg')
        audio_filter.add_pattern('*.aiff')
        audio_filter.add_pattern('*.m4a')
        filters.append(audio_filter)
        
        all_filter = Gtk.FileFilter()
        all_filter.set_name('All Files')
        all_filter.add_pattern('*')
        filters.append(all_filter)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(audio_filter)
        
        window = self.get_root()
        dialog.open_multiple(window, None, self._on_files_selected)
    
    def _on_files_selected(self, dialog: Gtk.FileDialog, result) -> None:
        """Handle file selection result."""
        try:
            files = dialog.open_multiple_finish(result)
            paths = [f.get_path() for f in files]
            logger.info(f"Selected {len(paths)} files")
            # TODO: Add files to project
        except GLib.Error as e:
            if e.code != Gtk.DialogError.DISMISSED:
                logger.error(f"File selection error: {e}")
    
    # Public API
    
    def set_project(self, project: Optional[Project], files: List[AudioFile] = None) -> None:
        """Set the current project and its files."""
        self._project = project
        self._files = files or []
        
        if project:
            self.title_label.set_label(project.name)
            self.subtitle_label.set_label(project.description or f'{project.file_count} files')
            self.add_btn.set_sensitive(True)
            self.export_btn.set_sensitive(True)
        else:
            self.title_label.set_label('No Project Selected')
            self.subtitle_label.set_label('Select a project to view files')
            self.add_btn.set_sensitive(False)
            self.export_btn.set_sensitive(False)
        
        self._populate_list()
        self._update_status()
    
    def _populate_list(self) -> None:
        """Populate the list with files."""
        # Clear existing
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        
        # Add file rows
        for audio_file in self._files:
            row = AudioFileRow(audio_file)
            self.list_box.append(row)
    
    def _update_status(self) -> None:
        """Update the status bar."""
        count = len(self._files)
        self.file_count_label.set_label(f'{count} file{"s" if count != 1 else ""}')
        
        total_duration = sum(f.duration or 0 for f in self._files)
        if total_duration > 0:
            mins = int(total_duration // 60)
            secs = int(total_duration % 60)
            self.duration_label.set_label(f'{mins}:{secs:02d} total')
        else:
            self.duration_label.set_label('')
        
        total_size = sum(f.file_size or 0 for f in self._files)
        if total_size > 0:
            if total_size > 1024 * 1024 * 1024:
                size_str = f'{total_size / (1024 * 1024 * 1024):.1f} GB'
            elif total_size > 1024 * 1024:
                size_str = f'{total_size / (1024 * 1024):.1f} MB'
            else:
                size_str = f'{total_size / 1024:.1f} KB'
            self.size_label.set_label(size_str)
        else:
            self.size_label.set_label('')
    
    def get_selected_files(self) -> List[AudioFile]:
        """Get the currently selected files."""
        selected = []
        for row in self.list_box.get_selected_rows():
            child = row.get_child()
            if isinstance(child, AudioFileRow):
                selected.append(child.audio_file)
        return selected
    
    def show_export_wizard(self) -> None:
        """Show the export wizard dialog."""
        from ..dialogs.export_wizard_dialog import ExportWizardDialog
        
        window = self.get_root()
        dialog = ExportWizardDialog(
            parent=window,
            project=self._project,
            files=self._files,
        )
        dialog.present()
