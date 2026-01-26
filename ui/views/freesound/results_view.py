"""
Freesound Results View

Displays search results with preview playback support.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, GLib
from typing import Optional, List

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundSound,
    FreesoundSearchResult,
)
from .sound_card import FreesoundSoundCard


class FreesoundResultsView(Adw.Bin):
    """
    View for displaying Freesound search results.
    
    Features:
    - Virtual scrolling for large result sets
    - Preview playback
    - Batch selection for download
    """
    
    __gsignals__ = {
        'sound-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'sound-play': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'sound-download': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'batch-download': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'load-more': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self):
        super().__init__()
        
        self._sounds: List[FreesoundSound] = []
        self._selected_sounds: List[FreesoundSound] = []
        self._current_playing: Optional[FreesoundSound] = None
        self._has_more = False
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the results view UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Toolbar
        toolbar = self._build_toolbar()
        main_box.append(toolbar)
        
        # Results list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Connect to edge-reached for infinite scroll
        scrolled.connect('edge-reached', self._on_edge_reached)
        
        self.results_list = Gtk.ListBox()
        self.results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.results_list.add_css_class('boxed-list')
        self.results_list.set_margin_start(16)
        self.results_list.set_margin_end(16)
        self.results_list.set_margin_bottom(16)
        
        scrolled.set_child(self.results_list)
        main_box.append(scrolled)
        
        # Loading indicator at bottom
        self.loading_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.loading_box.set_halign(Gtk.Align.CENTER)
        self.loading_box.set_margin_bottom(16)
        self.loading_box.set_visible(False)
        
        spinner = Gtk.Spinner()
        spinner.start()
        self.loading_box.append(spinner)
        
        loading_label = Gtk.Label(label="加载更多...")
        loading_label.add_css_class('dim-label')
        self.loading_box.append(loading_label)
        
        main_box.append(self.loading_box)
        
        self.set_child(main_box)
    
    def _build_toolbar(self) -> Gtk.Widget:
        """Build the toolbar."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(16)
        toolbar.set_margin_end(16)
        toolbar.set_margin_top(8)
        toolbar.set_margin_bottom(8)
        
        # Results count
        self.count_label = Gtk.Label(label="")
        self.count_label.set_xalign(0)
        self.count_label.set_hexpand(True)
        toolbar.append(self.count_label)
        
        # Selection info
        self.selection_label = Gtk.Label(label="")
        self.selection_label.add_css_class('dim-label')
        toolbar.append(self.selection_label)
        
        # Select all button
        self.select_all_btn = Gtk.Button(label='全选')
        self.select_all_btn.add_css_class('flat')
        self.select_all_btn.connect('clicked', self._on_select_all)
        toolbar.append(self.select_all_btn)
        
        # Batch download button
        self.batch_download_btn = Gtk.Button(label='批量下载')
        self.batch_download_btn.add_css_class('suggested-action')
        self.batch_download_btn.set_sensitive(False)
        self.batch_download_btn.connect('clicked', self._on_batch_download)
        toolbar.append(self.batch_download_btn)
        
        return toolbar
    
    def set_results(self, result: FreesoundSearchResult, append: bool = False):
        """
        Set or append search results.
        
        Args:
            result: FreesoundSearchResult
            append: If True, append to existing results
        """
        if not append:
            self._clear_results()
            self._sounds = []
            self._selected_sounds = []
        
        self._sounds.extend(result.results)
        self._has_more = result.next_page is not None
        
        # Add sound cards
        for sound in result.results:
            card = self._create_sound_card(sound)
            self.results_list.append(card)
        
        # Update count label
        self.count_label.set_text(f"共 {result.count:,} 个结果")
        self._update_selection_label()
        
        # Hide loading indicator
        self.loading_box.set_visible(False)
    
    def _clear_results(self):
        """Clear all results."""
        while True:
            row = self.results_list.get_first_child()
            if row is None:
                break
            self.results_list.remove(row)
    
    def _create_sound_card(self, sound: FreesoundSound) -> Gtk.Widget:
        """Create a sound card widget."""
        # Create a box with checkbox and card
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Checkbox for selection
        checkbox = Gtk.CheckButton()
        checkbox.set_valign(Gtk.Align.CENTER)
        checkbox.connect('toggled', self._on_sound_toggled, sound)
        row.append(checkbox)
        
        # Sound card
        card = FreesoundSoundCard(sound)
        card.set_hexpand(True)
        card.connect('play-clicked', self._on_play_clicked)
        card.connect('download-clicked', self._on_download_clicked)
        card.connect('details-clicked', self._on_details_clicked)
        row.append(card)
        
        # Wrap in ListBoxRow
        list_row = Gtk.ListBoxRow()
        list_row.set_child(row)
        list_row.sound = sound
        list_row.checkbox = checkbox
        list_row.card = card
        
        return list_row
    
    def _on_sound_toggled(self, checkbox, sound: FreesoundSound):
        """Handle sound selection toggle."""
        if checkbox.get_active():
            if sound not in self._selected_sounds:
                self._selected_sounds.append(sound)
        else:
            if sound in self._selected_sounds:
                self._selected_sounds.remove(sound)
        
        self._update_selection_label()
    
    def _update_selection_label(self):
        """Update selection info label."""
        count = len(self._selected_sounds)
        if count > 0:
            self.selection_label.set_text(f"已选择 {count} 个")
            self.batch_download_btn.set_sensitive(True)
        else:
            self.selection_label.set_text("")
            self.batch_download_btn.set_sensitive(False)
    
    def _on_select_all(self, button):
        """Select or deselect all sounds."""
        all_selected = len(self._selected_sounds) == len(self._sounds)
        
        # Iterate through rows
        row = self.results_list.get_first_child()
        while row:
            if hasattr(row, 'checkbox'):
                row.checkbox.set_active(not all_selected)
            row = row.get_next_sibling()
        
        if all_selected:
            self._selected_sounds = []
            self.select_all_btn.set_label('全选')
        else:
            self._selected_sounds = self._sounds.copy()
            self.select_all_btn.set_label('取消全选')
        
        self._update_selection_label()
    
    def _on_batch_download(self, button):
        """Handle batch download button click."""
        if self._selected_sounds:
            self.emit('batch-download', self._selected_sounds)
    
    def _on_play_clicked(self, card, sound: FreesoundSound):
        """Handle play button click."""
        # Stop current playing
        if self._current_playing and self._current_playing != sound:
            self._set_sound_playing(self._current_playing, False)
        
        if self._current_playing == sound:
            self._current_playing = None
        else:
            self._current_playing = sound
        
        self.emit('sound-play', sound)
    
    def _on_download_clicked(self, card, sound: FreesoundSound):
        """Handle download button click."""
        self.emit('sound-download', sound)
    
    def _on_details_clicked(self, card, sound: FreesoundSound):
        """Handle details button click."""
        self.emit('sound-selected', sound)
    
    def _on_edge_reached(self, scrolled, pos):
        """Handle scroll edge reached for infinite scroll."""
        if pos == Gtk.PositionType.BOTTOM and self._has_more:
            self.loading_box.set_visible(True)
            self.emit('load-more')
    
    def _set_sound_playing(self, sound: FreesoundSound, playing: bool):
        """Set playing state for a sound."""
        row = self.results_list.get_first_child()
        while row:
            if hasattr(row, 'sound') and row.sound.id == sound.id:
                if hasattr(row, 'card'):
                    row.card.set_playing(playing)
                break
            row = row.get_next_sibling()
    
    def stop_all_playback(self):
        """Stop all playback."""
        if self._current_playing:
            self._set_sound_playing(self._current_playing, False)
            self._current_playing = None
