"""
Batch Operation Wizard Dialog

Multi-step wizard for batch audio processing operations.
"""

import logging
from pathlib import Path
from typing import List, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, GLib

from transcriptionist_v3.domain.models.audio_file import AudioFile
from transcriptionist_v3.application.batch_processor import (
    BatchProcessor,
    BatchOperation,
    BatchOperationType,
    BatchProgress,
    BatchResult,
)
from transcriptionist_v3.application.batch_processor.converter import (
    AudioFormat,
    ConversionOptions,
)
from transcriptionist_v3.application.batch_processor.normalizer import (
    NormalizationStandard,
    NormalizationOptions,
)

logger = logging.getLogger(__name__)


class BatchWizardDialog(Adw.Dialog):
    """
    Multi-step wizard for batch operations.
    
    Steps:
    1. Operation type selection
    2. Operation-specific options
    3. File selection/confirmation
    4. Progress
    5. Results
    """
    
    __gtype_name__ = 'BatchWizardDialog'
    
    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        files: List[AudioFile] = None,
        processor: Optional[BatchProcessor] = None,
    ):
        super().__init__()
        
        self.files = files or []
        self.processor = processor or BatchProcessor()
        self._current_step = 0
        self._operation_type = BatchOperationType.CONVERT
        self._result: Optional[BatchResult] = None
        
        self.set_title('Batch Processing')
        self.set_content_width(600)
        self.set_content_height(550)
        
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the wizard UI."""
        content = Adw.ToolbarView()
        
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        
        self.cancel_btn = Gtk.Button(label='Cancel')
        self.cancel_btn.connect('clicked', self._on_cancel)
        header.pack_start(self.cancel_btn)
        
        self.back_btn = Gtk.Button(label='Back')
        self.back_btn.connect('clicked', self._on_back)
        self.back_btn.set_visible(False)
        header.pack_start(self.back_btn)
        
        self.next_btn = Gtk.Button(label='Next')
        self.next_btn.add_css_class('suggested-action')
        self.next_btn.connect('clicked', self._on_next)
        header.pack_end(self.next_btn)
        
        content.add_top_bar(header)
        
        # Stack for wizard steps
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        
        self.stack.add_named(self._create_operation_page(), 'operation')
        self.stack.add_named(self._create_convert_options_page(), 'convert')
        self.stack.add_named(self._create_normalize_options_page(), 'normalize')
        self.stack.add_named(self._create_confirm_page(), 'confirm')
        self.stack.add_named(self._create_progress_page(), 'progress')
        self.stack.add_named(self._create_results_page(), 'results')
        
        content.set_content(self.stack)
        self.set_child(content)
    
    def _create_operation_page(self) -> Gtk.Widget:
        """Create operation type selection page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        title = Gtk.Label(label='Select Operation')
        title.add_css_class('title-1')
        page.append(title)
        
        desc = Gtk.Label(label=f'Choose an operation to perform on {len(self.files)} selected files.')
        desc.add_css_class('dim-label')
        page.append(desc)
        
        # Operation cards
        cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        cards_box.set_margin_top(24)
        
        self.convert_card = self._create_operation_card(
            'Convert Format',
            'Convert audio files to different formats (WAV, FLAC, MP3, etc.)',
            'audio-x-generic-symbolic',
            BatchOperationType.CONVERT,
        )
        cards_box.append(self.convert_card)
        
        self.normalize_card = self._create_operation_card(
            'Normalize Loudness',
            'Adjust loudness to broadcast or streaming standards',
            'audio-volume-high-symbolic',
            BatchOperationType.NORMALIZE,
        )
        cards_box.append(self.normalize_card)
        
        page.append(cards_box)
        return page

    def _create_operation_card(
        self,
        title: str,
        description: str,
        icon_name: str,
        operation: BatchOperationType,
    ) -> Gtk.Widget:
        """Create an operation selection card."""
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.add_css_class('card')
        card.set_margin_start(6)
        card.set_margin_end(6)
        
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        content.append(icon)
        
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        
        title_label = Gtk.Label(label=title)
        title_label.add_css_class('heading')
        title_label.set_halign(Gtk.Align.START)
        text_box.append(title_label)
        
        desc_label = Gtk.Label(label=description)
        desc_label.add_css_class('dim-label')
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_wrap(True)
        text_box.append(desc_label)
        
        content.append(text_box)
        
        radio = Gtk.CheckButton()
        radio.set_valign(Gtk.Align.CENTER)
        if operation == BatchOperationType.CONVERT:
            radio.set_active(True)
            self._operation_radio_group = radio
        else:
            radio.set_group(self._operation_radio_group)
        radio.connect('toggled', self._on_operation_toggled, operation)
        content.append(radio)
        
        card.append(content)
        
        # Make card clickable
        gesture = Gtk.GestureClick()
        gesture.connect('released', lambda g, n, x, y: radio.set_active(True))
        card.add_controller(gesture)
        
        return card
    
    def _on_operation_toggled(self, button: Gtk.CheckButton, operation: BatchOperationType) -> None:
        """Handle operation selection."""
        if button.get_active():
            self._operation_type = operation

    def _create_convert_options_page(self) -> Gtk.Widget:
        """Create format conversion options page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        title = Gtk.Label(label='Conversion Options')
        title.add_css_class('title-1')
        page.append(title)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        # Format group
        format_group = Adw.PreferencesGroup()
        format_group.set_title('Output Format')
        
        self.format_combo = Adw.ComboRow()
        self.format_combo.set_title('Format')
        formats = Gtk.StringList.new([
            'WAV (Uncompressed)',
            'FLAC (Lossless)',
            'MP3 (Lossy)',
            'OGG Vorbis (Lossy)',
            'M4A/AAC (Lossy)',
            'AIFF (Uncompressed)',
        ])
        self.format_combo.set_model(formats)
        format_group.add(self.format_combo)
        
        options_box.append(format_group)
        
        # Quality group
        quality_group = Adw.PreferencesGroup()
        quality_group.set_title('Quality Settings')
        
        self.bitrate_combo = Adw.ComboRow()
        self.bitrate_combo.set_title('Bitrate')
        self.bitrate_combo.set_subtitle('For lossy formats')
        bitrates = Gtk.StringList.new(['128 kbps', '192 kbps', '256 kbps', '320 kbps'])
        self.bitrate_combo.set_model(bitrates)
        self.bitrate_combo.set_selected(3)
        quality_group.add(self.bitrate_combo)
        
        self.sample_rate_combo = Adw.ComboRow()
        self.sample_rate_combo.set_title('Sample Rate')
        rates = Gtk.StringList.new(['Keep Original', '44100 Hz', '48000 Hz', '96000 Hz'])
        self.sample_rate_combo.set_model(rates)
        quality_group.add(self.sample_rate_combo)
        
        options_box.append(quality_group)
        
        # Output group
        output_group = Adw.PreferencesGroup()
        output_group.set_title('Output Location')
        
        self.output_row = Adw.ActionRow()
        self.output_row.set_title('Output Folder')
        self.output_row.set_subtitle('Same as source')
        
        browse_btn = Gtk.Button.new_from_icon_name('folder-open-symbolic')
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect('clicked', self._on_browse_output)
        self.output_row.add_suffix(browse_btn)
        output_group.add(self.output_row)
        
        self.overwrite_switch = Adw.SwitchRow()
        self.overwrite_switch.set_title('Overwrite Existing')
        output_group.add(self.overwrite_switch)
        
        options_box.append(output_group)
        
        scrolled.set_child(options_box)
        page.append(scrolled)
        
        return page

    def _create_normalize_options_page(self) -> Gtk.Widget:
        """Create loudness normalization options page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        title = Gtk.Label(label='Normalization Options')
        title.add_css_class('title-1')
        page.append(title)
        
        # Standard group
        standard_group = Adw.PreferencesGroup()
        standard_group.set_title('Loudness Standard')
        
        self.standard_combo = Adw.ComboRow()
        self.standard_combo.set_title('Standard')
        standards = Gtk.StringList.new([
            'EBU R128 (-23 LUFS) - Broadcast',
            'ATSC A/85 (-24 LUFS) - US TV',
            'Streaming (-14 LUFS) - Spotify/YouTube',
            'Custom',
        ])
        self.standard_combo.set_model(standards)
        self.standard_combo.connect('notify::selected', self._on_standard_changed)
        standard_group.add(self.standard_combo)
        
        self.target_spin = Adw.SpinRow.new_with_range(-60, 0, 0.5)
        self.target_spin.set_title('Target Loudness (LUFS)')
        self.target_spin.set_value(-23)
        self.target_spin.set_sensitive(False)
        standard_group.add(self.target_spin)
        
        page.append(standard_group)
        
        # Limiter group
        limiter_group = Adw.PreferencesGroup()
        limiter_group.set_title('Peak Limiting')
        
        self.limiter_switch = Adw.SwitchRow()
        self.limiter_switch.set_title('Apply Peak Limiter')
        self.limiter_switch.set_subtitle('Prevent clipping')
        self.limiter_switch.set_active(True)
        limiter_group.add(self.limiter_switch)
        
        self.peak_spin = Adw.SpinRow.new_with_range(-6, 0, 0.1)
        self.peak_spin.set_title('Peak Limit (dBTP)')
        self.peak_spin.set_value(-1.0)
        limiter_group.add(self.peak_spin)
        
        page.append(limiter_group)
        
        # Output group
        norm_output_group = Adw.PreferencesGroup()
        norm_output_group.set_title('Output')
        
        self.norm_output_row = Adw.ActionRow()
        self.norm_output_row.set_title('Output Folder')
        self.norm_output_row.set_subtitle('Same as source')
        
        norm_browse_btn = Gtk.Button.new_from_icon_name('folder-open-symbolic')
        norm_browse_btn.set_valign(Gtk.Align.CENTER)
        norm_browse_btn.connect('clicked', self._on_browse_norm_output)
        self.norm_output_row.add_suffix(norm_browse_btn)
        norm_output_group.add(self.norm_output_row)
        
        self.suffix_entry = Adw.EntryRow()
        self.suffix_entry.set_title('File Suffix')
        self.suffix_entry.set_text('_normalized')
        norm_output_group.add(self.suffix_entry)
        
        page.append(norm_output_group)
        
        return page
    
    def _on_standard_changed(self, combo, pspec) -> None:
        """Handle standard selection change."""
        selected = combo.get_selected()
        self.target_spin.set_sensitive(selected == 3)  # Custom
        
        targets = [-23.0, -24.0, -14.0, -23.0]
        if selected < 3:
            self.target_spin.set_value(targets[selected])

    def _create_confirm_page(self) -> Gtk.Widget:
        """Create confirmation page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        title = Gtk.Label(label='Confirm Operation')
        title.add_css_class('title-1')
        page.append(title)
        
        # Summary group
        summary_group = Adw.PreferencesGroup()
        summary_group.set_title('Summary')
        
        self.op_summary_row = Adw.ActionRow()
        self.op_summary_row.set_title('Operation')
        summary_group.add(self.op_summary_row)
        
        self.files_summary_row = Adw.ActionRow()
        self.files_summary_row.set_title('Files')
        self.files_summary_row.set_subtitle(f'{len(self.files)} files selected')
        summary_group.add(self.files_summary_row)
        
        self.output_summary_row = Adw.ActionRow()
        self.output_summary_row.set_title('Output')
        summary_group.add(self.output_summary_row)
        
        page.append(summary_group)
        
        # File list
        files_group = Adw.PreferencesGroup()
        files_group.set_title('Files to Process')
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(150)
        
        self.files_list = Gtk.ListBox()
        self.files_list.add_css_class('boxed-list')
        
        for audio_file in self.files[:10]:  # Show first 10
            row = Adw.ActionRow()
            row.set_title(audio_file.filename)
            row.set_subtitle(str(Path(audio_file.file_path).parent))
            self.files_list.append(row)
        
        if len(self.files) > 10:
            more_row = Adw.ActionRow()
            more_row.set_title(f'... and {len(self.files) - 10} more files')
            more_row.add_css_class('dim-label')
            self.files_list.append(more_row)
        
        scrolled.set_child(self.files_list)
        files_group.add(scrolled)
        
        page.append(files_group)
        
        return page
    
    def _create_progress_page(self) -> Gtk.Widget:
        """Create progress page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(48)
        page.set_margin_bottom(24)
        page.set_valign(Gtk.Align.CENTER)
        
        self.progress_spinner = Gtk.Spinner()
        self.progress_spinner.set_size_request(48, 48)
        page.append(self.progress_spinner)
        
        self.progress_title = Gtk.Label(label='Processing...')
        self.progress_title.add_css_class('title-2')
        page.append(self.progress_title)
        
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_margin_top(12)
        page.append(self.progress_bar)
        
        self.progress_detail = Gtk.Label(label='')
        self.progress_detail.add_css_class('dim-label')
        page.append(self.progress_detail)
        
        self.progress_stats = Gtk.Label(label='')
        self.progress_stats.add_css_class('caption')
        page.append(self.progress_stats)
        
        return page

    def _create_results_page(self) -> Gtk.Widget:
        """Create results page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        
        # Status icon and title
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.set_margin_top(24)
        
        self.result_icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
        self.result_icon.set_pixel_size(64)
        status_box.append(self.result_icon)
        
        self.result_title = Gtk.Label(label='Processing Complete')
        self.result_title.add_css_class('title-1')
        status_box.append(self.result_title)
        
        page.append(status_box)
        
        # Results summary
        results_group = Adw.PreferencesGroup()
        results_group.set_title('Results')
        
        self.success_row = Adw.ActionRow()
        self.success_row.set_title('Successful')
        self.success_row.set_icon_name('emblem-ok-symbolic')
        results_group.add(self.success_row)
        
        self.failed_row = Adw.ActionRow()
        self.failed_row.set_title('Failed')
        self.failed_row.set_icon_name('dialog-warning-symbolic')
        results_group.add(self.failed_row)
        
        self.time_row = Adw.ActionRow()
        self.time_row.set_title('Duration')
        self.time_row.set_icon_name('preferences-system-time-symbolic')
        results_group.add(self.time_row)
        
        page.append(results_group)
        
        # Errors (if any)
        self.errors_group = Adw.PreferencesGroup()
        self.errors_group.set_title('Errors')
        self.errors_group.set_visible(False)
        
        self.errors_list = Gtk.ListBox()
        self.errors_list.add_css_class('boxed-list')
        self.errors_group.add(self.errors_list)
        
        page.append(self.errors_group)
        
        return page
    
    def _on_browse_output(self, button: Gtk.Button) -> None:
        """Browse for output folder."""
        self._browse_folder(self.output_row)
    
    def _on_browse_norm_output(self, button: Gtk.Button) -> None:
        """Browse for normalization output folder."""
        self._browse_folder(self.norm_output_row)
    
    def _browse_folder(self, row: Adw.ActionRow) -> None:
        """Show folder browser dialog."""
        dialog = Gtk.FileDialog()
        dialog.set_title('Select Output Folder')
        
        window = self.get_root()
        dialog.select_folder(window, None, lambda d, r: self._on_folder_selected(d, r, row))
    
    def _on_folder_selected(self, dialog, result, row: Adw.ActionRow) -> None:
        """Handle folder selection."""
        try:
            folder = dialog.select_folder_finish(result)
            path = folder.get_path()
            row.set_subtitle(path)
            row._output_path = Path(path)
        except GLib.Error:
            pass

    def _on_cancel(self, button: Gtk.Button) -> None:
        """Handle cancel."""
        if self._current_step == 3:  # Progress
            self.processor.cancel()
        self.close()
    
    def _on_back(self, button: Gtk.Button) -> None:
        """Handle back."""
        if self._current_step > 0:
            self._current_step -= 1
            self._update_step()
    
    def _on_next(self, button: Gtk.Button) -> None:
        """Handle next."""
        if self._current_step == 4:  # Results - close
            self.close()
            return
        
        if self._current_step == 2:  # Confirm - start processing
            self._start_processing()
            return
        
        self._current_step += 1
        self._update_step()
    
    def _update_step(self) -> None:
        """Update UI for current step."""
        # Determine which page to show
        if self._current_step == 0:
            self.stack.set_visible_child_name('operation')
        elif self._current_step == 1:
            if self._operation_type == BatchOperationType.CONVERT:
                self.stack.set_visible_child_name('convert')
            else:
                self.stack.set_visible_child_name('normalize')
        elif self._current_step == 2:
            self._update_confirm_page()
            self.stack.set_visible_child_name('confirm')
        elif self._current_step == 3:
            self.stack.set_visible_child_name('progress')
        elif self._current_step == 4:
            self.stack.set_visible_child_name('results')
        
        # Update buttons
        self.back_btn.set_visible(self._current_step > 0 and self._current_step < 3)
        
        if self._current_step == 2:
            self.next_btn.set_label('Start')
        elif self._current_step == 3:
            self.next_btn.set_sensitive(False)
            self.cancel_btn.set_label('Cancel')
        elif self._current_step == 4:
            self.next_btn.set_label('Done')
            self.next_btn.set_sensitive(True)
            self.cancel_btn.set_visible(False)
            self.back_btn.set_visible(False)
        else:
            self.next_btn.set_label('Next')
    
    def _update_confirm_page(self) -> None:
        """Update confirmation page with current settings."""
        if self._operation_type == BatchOperationType.CONVERT:
            formats = ['WAV', 'FLAC', 'MP3', 'OGG', 'M4A', 'AIFF']
            fmt = formats[self.format_combo.get_selected()]
            self.op_summary_row.set_subtitle(f'Convert to {fmt}')
            
            output = getattr(self.output_row, '_output_path', None)
            self.output_summary_row.set_subtitle(str(output) if output else 'Same as source')
        else:
            standards = ['EBU R128', 'ATSC A/85', 'Streaming', 'Custom']
            std = standards[self.standard_combo.get_selected()]
            target = self.target_spin.get_value()
            self.op_summary_row.set_subtitle(f'Normalize to {std} ({target:.1f} LUFS)')
            
            output = getattr(self.norm_output_row, '_output_path', None)
            self.output_summary_row.set_subtitle(str(output) if output else 'Same as source')

    def _start_processing(self) -> None:
        """Start the batch processing."""
        self._current_step = 3
        self._update_step()
        
        self.progress_spinner.start()
        
        # Build operation
        operation = self._build_operation()
        
        # Run in background
        import threading
        thread = threading.Thread(
            target=self._run_processing,
            args=(operation,),
            daemon=True,
        )
        thread.start()
    
    def _build_operation(self) -> BatchOperation:
        """Build batch operation from UI settings."""
        file_paths = [Path(f.file_path) for f in self.files]
        
        if self._operation_type == BatchOperationType.CONVERT:
            formats = [
                AudioFormat.WAV, AudioFormat.FLAC, AudioFormat.MP3,
                AudioFormat.OGG, AudioFormat.M4A, AudioFormat.AIFF,
            ]
            bitrates = ['128k', '192k', '256k', '320k']
            sample_rates = [None, 44100, 48000, 96000]
            
            options = ConversionOptions(
                output_format=formats[self.format_combo.get_selected()],
                bitrate=bitrates[self.bitrate_combo.get_selected()],
                sample_rate=sample_rates[self.sample_rate_combo.get_selected()],
                output_dir=getattr(self.output_row, '_output_path', None),
                overwrite=self.overwrite_switch.get_active(),
            )
            
            return BatchOperation(
                operation_type=BatchOperationType.CONVERT,
                input_files=file_paths,
                conversion_options=options,
            )
        else:
            standards = [
                NormalizationStandard.EBU_R128,
                NormalizationStandard.ATSC_A85,
                NormalizationStandard.STREAMING,
                NormalizationStandard.CUSTOM,
            ]
            
            options = NormalizationOptions(
                standard=standards[self.standard_combo.get_selected()],
                target_loudness=self.target_spin.get_value(),
                apply_limiter=self.limiter_switch.get_active(),
                peak_limit=self.peak_spin.get_value(),
                output_dir=getattr(self.norm_output_row, '_output_path', None),
                suffix=self.suffix_entry.get_text(),
            )
            
            return BatchOperation(
                operation_type=BatchOperationType.NORMALIZE,
                input_files=file_paths,
                normalization_options=options,
            )
    
    def _run_processing(self, operation: BatchOperation) -> None:
        """Run processing in background thread."""
        import asyncio
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                self.processor.process(operation, self._on_progress)
            )
            GLib.idle_add(self._on_complete, result)
        except Exception as e:
            logger.error(f"Processing error: {e}")
            GLib.idle_add(self._on_error, str(e))
        finally:
            loop.close()
    
    def _on_progress(self, progress: BatchProgress) -> None:
        """Handle progress update."""
        GLib.idle_add(self._update_progress, progress)
    
    def _update_progress(self, progress: BatchProgress) -> None:
        """Update progress UI."""
        self.progress_bar.set_fraction(progress.overall_progress)
        self.progress_bar.set_text(f'{int(progress.overall_progress * 100)}%')
        self.progress_detail.set_label(progress.current_file)
        
        stats = f'{progress.processed_files}/{progress.total_files} files'
        if progress.estimated_remaining:
            mins = int(progress.estimated_remaining // 60)
            secs = int(progress.estimated_remaining % 60)
            stats += f' • ~{mins}:{secs:02d} remaining'
        self.progress_stats.set_label(stats)

    def _on_complete(self, result: BatchResult) -> None:
        """Handle processing complete."""
        self._result = result
        self.progress_spinner.stop()
        
        self._current_step = 4
        self._update_step()
        
        # Update results page
        if result.success:
            self.result_icon.set_from_icon_name('emblem-ok-symbolic')
            self.result_icon.add_css_class('success')
            self.result_title.set_label('Processing Complete')
        else:
            self.result_icon.set_from_icon_name('dialog-warning-symbolic')
            self.result_icon.add_css_class('warning')
            self.result_title.set_label('Completed with Errors')
        
        self.success_row.set_subtitle(f'{result.successful_files} files')
        self.failed_row.set_subtitle(f'{result.failed_files} files')
        
        mins = int(result.duration_seconds // 60)
        secs = int(result.duration_seconds % 60)
        self.time_row.set_subtitle(f'{mins}:{secs:02d}')
        
        # Show errors if any
        if result.errors:
            self.errors_group.set_visible(True)
            for error in result.errors[:5]:
                row = Adw.ActionRow()
                row.set_title(error[:50] + '...' if len(error) > 50 else error)
                row.add_css_class('error')
                self.errors_list.append(row)
    
    def _on_error(self, error: str) -> None:
        """Handle processing error."""
        self.progress_spinner.stop()
        
        self._current_step = 4
        self._update_step()
        
        self.result_icon.set_from_icon_name('dialog-error-symbolic')
        self.result_icon.add_css_class('error')
        self.result_title.set_label('Processing Failed')
        
        self.success_row.set_subtitle('0 files')
        self.failed_row.set_subtitle(f'{len(self.files)} files')
        self.time_row.set_subtitle('N/A')
        
        self.errors_group.set_visible(True)
        row = Adw.ActionRow()
        row.set_title(error)
        self.errors_list.append(row)
