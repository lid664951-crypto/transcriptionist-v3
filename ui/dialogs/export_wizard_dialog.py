"""
Export Wizard Dialog

Multi-step wizard for exporting projects with various options.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, GLib

from transcriptionist_v3.domain.models.project import Project
from transcriptionist_v3.domain.models.audio_file import AudioFile
from transcriptionist_v3.application.project_manager.exporter import (
    ProjectExporter,
    ExportOptions,
    ExportFormat,
    NamingScheme,
    ExportResult,
)

logger = logging.getLogger(__name__)


class ExportWizardDialog(Adw.Dialog):
    """
    Multi-step export wizard dialog.
    
    Steps:
    1. Output location selection
    2. Export format and naming options
    3. Metadata options
    4. Progress and completion
    """
    
    __gtype_name__ = 'ExportWizardDialog'
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        project: Optional[Project] = None,
        files: List[AudioFile] = None,
        exporter: Optional[ProjectExporter] = None,
    ):
        super().__init__()
        
        self.project = project
        self.files = files or []
        self.exporter = exporter or ProjectExporter()
        self._export_task = None
        
        self.set_title('Export Project')
        self.set_content_width(550)
        self.set_content_height(500)
        
        self._current_step = 0
        self._output_path: Optional[Path] = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Set up the wizard UI."""
        # Main content
        content = Adw.ToolbarView()
        
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        
        # Cancel button
        self.cancel_btn = Gtk.Button(label='Cancel')
        self.cancel_btn.connect('clicked', self._on_cancel)
        header.pack_start(self.cancel_btn)
        
        # Back button
        self.back_btn = Gtk.Button(label='Back')
        self.back_btn.connect('clicked', self._on_back)
        self.back_btn.set_visible(False)
        header.pack_start(self.back_btn)
        
        # Next/Export button
        self.next_btn = Gtk.Button(label='Next')
        self.next_btn.add_css_class('suggested-action')
        self.next_btn.connect('clicked', self._on_next)
        header.pack_end(self.next_btn)
        
        content.add_top_bar(header)
        
        # Stack for wizard steps
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        
        # Step 1: Output location
        self.stack.add_named(self._create_location_page(), 'location')
        
        # Step 2: Format options
        self.stack.add_named(self._create_format_page(), 'format')
        
        # Step 3: Metadata options
        self.stack.add_named(self._create_metadata_page(), 'metadata')
        
        # Step 4: Progress
        self.stack.add_named(self._create_progress_page(), 'progress')
        
        # Step 5: Complete
        self.stack.add_named(self._create_complete_page(), 'complete')
        
        content.set_content(self.stack)
        self.set_child(content)
    
    def _create_location_page(self) -> Gtk.Widget:
        """Create the output location selection page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        # Title
        title = Gtk.Label(label='Choose Export Location')
        title.add_css_class('title-1')
        page.append(title)
        
        # Description
        desc = Gtk.Label(label='Select where to save the exported project files.')
        desc.add_css_class('dim-label')
        desc.set_wrap(True)
        page.append(desc)
        
        # Location selector
        location_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        location_box.set_margin_top(24)
        
        self.location_entry = Gtk.Entry()
        self.location_entry.set_hexpand(True)
        self.location_entry.set_placeholder_text('Select output folder...')
        self.location_entry.set_editable(False)
        location_box.append(self.location_entry)
        
        browse_btn = Gtk.Button(label='Browse...')
        browse_btn.connect('clicked', self._on_browse_location)
        location_box.append(browse_btn)
        
        page.append(location_box)
        
        # Project info
        info_group = Adw.PreferencesGroup()
        info_group.set_title('Export Summary')
        info_group.set_margin_top(24)
        
        # File count
        file_count = len(self.files)
        files_row = Adw.ActionRow()
        files_row.set_title('Files to Export')
        files_row.set_subtitle(f'{file_count} audio file{"s" if file_count != 1 else ""}')
        info_group.add(files_row)
        
        # Total size
        total_size = sum(f.file_size or 0 for f in self.files)
        size_str = self._format_size(total_size)
        size_row = Adw.ActionRow()
        size_row.set_title('Total Size')
        size_row.set_subtitle(size_str)
        info_group.add(size_row)
        
        page.append(info_group)
        
        return page
    
    def _create_format_page(self) -> Gtk.Widget:
        """Create the format options page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        # Title
        title = Gtk.Label(label='Export Format')
        title.add_css_class('title-1')
        page.append(title)
        
        # Format group
        format_group = Adw.PreferencesGroup()
        format_group.set_title('Directory Structure')
        
        # Format combo
        self.format_combo = Adw.ComboRow()
        self.format_combo.set_title('Organization')
        formats = Gtk.StringList.new([
            'Flat (all files in one folder)',
            'By Category (UCS categories)',
            'By Date',
        ])
        self.format_combo.set_model(formats)
        format_group.add(self.format_combo)
        
        page.append(format_group)
        
        # Naming group
        naming_group = Adw.PreferencesGroup()
        naming_group.set_title('File Naming')
        
        # Naming scheme combo
        self.naming_combo = Adw.ComboRow()
        self.naming_combo.set_title('Naming Scheme')
        schemes = Gtk.StringList.new([
            'Original filenames',
            'UCS naming convention',
            'Sequential numbering',
        ])
        self.naming_combo.set_model(schemes)
        naming_group.add(self.naming_combo)
        
        page.append(naming_group)
        
        # File handling group
        handling_group = Adw.PreferencesGroup()
        handling_group.set_title('File Handling')
        
        # Copy files switch
        self.copy_switch = Adw.SwitchRow()
        self.copy_switch.set_title('Copy Files')
        self.copy_switch.set_subtitle('Copy files to export location')
        self.copy_switch.set_active(True)
        handling_group.add(self.copy_switch)
        
        # Overwrite switch
        self.overwrite_switch = Adw.SwitchRow()
        self.overwrite_switch.set_title('Overwrite Existing')
        self.overwrite_switch.set_subtitle('Replace files if they already exist')
        self.overwrite_switch.set_active(False)
        handling_group.add(self.overwrite_switch)
        
        page.append(handling_group)
        
        return page
    
    def _create_metadata_page(self) -> Gtk.Widget:
        """Create the metadata options page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        # Title
        title = Gtk.Label(label='Metadata Options')
        title.add_css_class('title-1')
        page.append(title)
        
        # Metadata group
        meta_group = Adw.PreferencesGroup()
        meta_group.set_title('Metadata Export')
        
        # Include metadata switch
        self.metadata_switch = Adw.SwitchRow()
        self.metadata_switch.set_title('Include Metadata')
        self.metadata_switch.set_subtitle('Generate JSON sidecar files with metadata')
        self.metadata_switch.set_active(True)
        meta_group.add(self.metadata_switch)
        
        # Project info switch
        self.project_info_switch = Adw.SwitchRow()
        self.project_info_switch.set_title('Include Project Info')
        self.project_info_switch.set_subtitle('Generate project_info.json and file_list.txt')
        self.project_info_switch.set_active(True)
        meta_group.add(self.project_info_switch)
        
        page.append(meta_group)
        
        return page
    
    def _create_progress_page(self) -> Gtk.Widget:
        """Create the progress page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(48)
        page.set_margin_bottom(24)
        page.set_valign(Gtk.Align.CENTER)
        
        # Spinner
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(48, 48)
        page.append(self.spinner)
        
        # Status label
        self.progress_label = Gtk.Label(label='Preparing export...')
        self.progress_label.add_css_class('title-2')
        page.append(self.progress_label)
        
        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_margin_top(12)
        page.append(self.progress_bar)
        
        # Current file label
        self.current_file_label = Gtk.Label(label='')
        self.current_file_label.add_css_class('dim-label')
        self.current_file_label.set_ellipsize(True)
        page.append(self.current_file_label)
        
        return page
    
    def _create_complete_page(self) -> Gtk.Widget:
        """Create the completion page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(48)
        page.set_margin_bottom(24)
        page.set_valign(Gtk.Align.CENTER)
        
        # Success icon
        self.complete_icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
        self.complete_icon.set_pixel_size(64)
        self.complete_icon.add_css_class('success')
        page.append(self.complete_icon)
        
        # Title
        self.complete_title = Gtk.Label(label='Export Complete')
        self.complete_title.add_css_class('title-1')
        page.append(self.complete_title)
        
        # Summary
        self.complete_summary = Gtk.Label(label='')
        self.complete_summary.add_css_class('dim-label')
        self.complete_summary.set_wrap(True)
        page.append(self.complete_summary)
        
        # Open folder button
        self.open_folder_btn = Gtk.Button(label='Open Export Folder')
        self.open_folder_btn.set_halign(Gtk.Align.CENTER)
        self.open_folder_btn.set_margin_top(24)
        self.open_folder_btn.connect('clicked', self._on_open_folder)
        page.append(self.open_folder_btn)
        
        return page
    
    def _on_browse_location(self, button: Gtk.Button) -> None:
        """Handle browse button click."""
        dialog = Gtk.FileDialog()
        dialog.set_title('Select Export Location')
        
        window = self.get_root()
        dialog.select_folder(window, None, self._on_folder_selected)
    
    def _on_folder_selected(self, dialog: Gtk.FileDialog, result) -> None:
        """Handle folder selection result."""
        try:
            folder = dialog.select_folder_finish(result)
            self._output_path = Path(folder.get_path())
            self.location_entry.set_text(str(self._output_path))
            self.next_btn.set_sensitive(True)
        except GLib.Error as e:
            if e.code != Gtk.DialogError.DISMISSED:
                logger.error(f"Folder selection error: {e}")
    
    def _on_cancel(self, button: Gtk.Button) -> None:
        """Handle cancel button click."""
        if self._export_task:
            self.exporter.cancel()
        self.close()
    
    def _on_back(self, button: Gtk.Button) -> None:
        """Handle back button click."""
        if self._current_step > 0:
            self._current_step -= 1
            self._update_step()
    
    def _on_next(self, button: Gtk.Button) -> None:
        """Handle next button click."""
        if self._current_step < 3:
            self._current_step += 1
            self._update_step()
        elif self._current_step == 3:
            # Start export
            self._start_export()
    
    def _update_step(self) -> None:
        """Update the UI for the current step."""
        steps = ['location', 'format', 'metadata', 'progress', 'complete']
        self.stack.set_visible_child_name(steps[self._current_step])
        
        # Update buttons
        self.back_btn.set_visible(self._current_step > 0 and self._current_step < 3)
        
        if self._current_step == 2:
            self.next_btn.set_label('Export')
        elif self._current_step == 4:
            self.next_btn.set_label('Done')
            self.cancel_btn.set_visible(False)
            self.back_btn.set_visible(False)
        else:
            self.next_btn.set_label('Next')
        
        # Validate current step
        if self._current_step == 0:
            self.next_btn.set_sensitive(self._output_path is not None)
        elif self._current_step == 3:
            self.next_btn.set_sensitive(False)
    
    def _start_export(self) -> None:
        """Start the export process."""
        self._current_step = 3
        self._update_step()
        
        self.spinner.start()
        self.cancel_btn.set_label('Cancel Export')
        
        # Build export options
        format_map = {
            0: ExportFormat.FLAT,
            1: ExportFormat.BY_CATEGORY,
            2: ExportFormat.BY_DATE,
        }
        naming_map = {
            0: NamingScheme.ORIGINAL,
            1: NamingScheme.UCS,
            2: NamingScheme.SEQUENTIAL,
        }
        
        options = ExportOptions(
            output_dir=self._output_path,
            format=format_map.get(self.format_combo.get_selected(), ExportFormat.FLAT),
            naming_scheme=naming_map.get(self.naming_combo.get_selected(), NamingScheme.ORIGINAL),
            copy_files=self.copy_switch.get_active(),
            overwrite_existing=self.overwrite_switch.get_active(),
            include_metadata=self.metadata_switch.get_active(),
            include_project_info=self.project_info_switch.get_active(),
            progress_callback=self._on_progress,
        )
        
        # Run export in background
        self._run_export_async(options)
    
    def _run_export_async(self, options: ExportOptions) -> None:
        """Run export asynchronously."""
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.exporter.export_project(self.project, self.files, options)
                )
                GLib.idle_add(self._on_export_complete, result)
            except Exception as e:
                logger.error(f"Export error: {e}")
                GLib.idle_add(self._on_export_error, str(e))
            finally:
                loop.close()
        
        import threading
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
    
    def _on_progress(self, progress: float, message: str) -> None:
        """Handle progress updates."""
        GLib.idle_add(self._update_progress, progress, message)
    
    def _update_progress(self, progress: float, message: str) -> None:
        """Update progress UI (called on main thread)."""
        self.progress_bar.set_fraction(progress)
        self.progress_bar.set_text(f'{int(progress * 100)}%')
        self.current_file_label.set_label(message)
    
    def _on_export_complete(self, result: ExportResult) -> None:
        """Handle export completion."""
        self.spinner.stop()
        self._current_step = 4
        self._update_step()
        
        if result.success:
            self.complete_icon.set_from_icon_name('emblem-ok-symbolic')
            self.complete_title.set_label('Export Complete')
            self.complete_summary.set_label(
                f'Successfully exported {result.files_exported} files '
                f'({self._format_size(result.total_size)}) '
                f'in {result.duration_seconds:.1f} seconds.'
            )
        else:
            self.complete_icon.set_from_icon_name('dialog-warning-symbolic')
            self.complete_title.set_label('Export Completed with Errors')
            self.complete_summary.set_label(
                f'Exported {result.files_exported} files, '
                f'{result.files_failed} failed.\n'
                f'Errors: {", ".join(result.errors[:3])}'
            )
        
        self._result = result
    
    def _on_export_error(self, error: str) -> None:
        """Handle export error."""
        self.spinner.stop()
        self._current_step = 4
        self._update_step()
        
        self.complete_icon.set_from_icon_name('dialog-error-symbolic')
        self.complete_title.set_label('Export Failed')
        self.complete_summary.set_label(f'Error: {error}')
        self.open_folder_btn.set_visible(False)
    
    def _on_open_folder(self, button: Gtk.Button) -> None:
        """Open the export folder."""
        if hasattr(self, '_result') and self._result.output_dir:
            Gio.AppInfo.launch_default_for_uri(
                f'file://{self._result.output_dir}',
                None
            )
    
    def _format_size(self, size: int) -> str:
        """Format file size."""
        if size > 1024 * 1024 * 1024:
            return f'{size / (1024 * 1024 * 1024):.1f} GB'
        elif size > 1024 * 1024:
            return f'{size / (1024 * 1024):.1f} MB'
        elif size > 1024:
            return f'{size / 1024:.1f} KB'
        return f'{size} bytes'
