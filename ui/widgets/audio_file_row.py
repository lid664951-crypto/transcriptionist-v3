"""
Audio File Row Widget

A GTK4 widget for displaying audio file information in a list.
Inspired by Quod Libet's songlist but adapted for GTK4/Libadwaita.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GObject, Pango, Gdk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False


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


def format_size(size_bytes: int) -> str:
    """Format file size in bytes to human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class AudioFileRow(Gtk.Box):
    """
    A widget representing a single audio file in a list.
    
    Displays:
    - File icon (based on format)
    - Filename/title
    - Duration
    - Sample rate
    - Format badge
    - Optional: waveform preview
    """
    
    __gtype_name__ = 'AudioFileRow'
    
    # Signals
    __gsignals__ = {
        'activated': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'play-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'context-menu': (GObject.SignalFlags.RUN_FIRST, None, (float, float)),
    }
    
    # Format icons
    FORMAT_ICONS = {
        'wav': 'audio-x-generic-symbolic',
        'wave': 'audio-x-generic-symbolic',
        'mp3': 'audio-x-generic-symbolic',
        'flac': 'audio-x-generic-symbolic',
        'ogg': 'audio-x-generic-symbolic',
        'm4a': 'audio-x-generic-symbolic',
        'aiff': 'audio-x-generic-symbolic',
        'aif': 'audio-x-generic-symbolic',
    }
    
    def __init__(self, audio_data: Optional[Dict[str, Any]] = None):
        """
        Initialize the audio file row.
        
        Args:
            audio_data: Dictionary with audio file metadata
        """
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        if not GTK_AVAILABLE:
            return
        
        self._audio_data = audio_data or {}
        self._selected = False
        self._playing = False
        
        self._setup_ui()
        self._setup_gestures()
        
        if audio_data:
            self.update_data(audio_data)
    
    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        # Play indicator / format icon
        self._icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        self._icon.set_pixel_size(24)
        self._icon.add_css_class("dim-label")
        self.append(self._icon)
        
        # Main info box (filename, subtitle)
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        
        # Filename/title
        self._title_label = Gtk.Label()
        self._title_label.set_halign(Gtk.Align.START)
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._title_label.add_css_class("heading")
        info_box.append(self._title_label)
        
        # Subtitle (path, tags)
        self._subtitle_label = Gtk.Label()
        self._subtitle_label.set_halign(Gtk.Align.START)
        self._subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._subtitle_label.add_css_class("dim-label")
        self._subtitle_label.add_css_class("caption")
        info_box.append(self._subtitle_label)
        
        self.append(info_box)
        
        # Technical info box
        tech_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Sample rate badge
        self._sample_rate_label = Gtk.Label()
        self._sample_rate_label.add_css_class("dim-label")
        self._sample_rate_label.add_css_class("caption")
        tech_box.append(self._sample_rate_label)
        
        # Format badge
        self._format_badge = Gtk.Label()
        self._format_badge.add_css_class("caption")
        self._format_badge.set_width_chars(5)
        tech_box.append(self._format_badge)
        
        self.append(tech_box)
        
        # Duration
        self._duration_label = Gtk.Label()
        self._duration_label.set_width_chars(7)
        self._duration_label.set_halign(Gtk.Align.END)
        self._duration_label.add_css_class("numeric")
        self.append(self._duration_label)
    
    def _setup_gestures(self) -> None:
        """Set up gesture controllers."""
        # Double-click to activate
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        
        # Right-click for context menu
        right_click = Gtk.GestureClick()
        right_click.set_button(3)  # Right mouse button
        right_click.connect("released", self._on_right_click)
        self.add_controller(right_click)
    
    def _on_click(self, gesture: Gtk.GestureClick, n_press: int, 
                  x: float, y: float) -> None:
        """Handle click events."""
        if n_press == 2:
            self.emit('activated')
            self.emit('play-requested')
    
    def _on_right_click(self, gesture: Gtk.GestureClick, n_press: int,
                        x: float, y: float) -> None:
        """Handle right-click for context menu."""
        self.emit('context-menu', x, y)
    
    def update_data(self, audio_data: Dict[str, Any]) -> None:
        """Update the row with new audio data."""
        self._audio_data = audio_data
        
        # Update title
        title = audio_data.get('title') or audio_data.get('filename', 'Unknown')
        self._title_label.set_text(title)
        
        # Update subtitle (folder path)
        file_path = audio_data.get('file_path', '')
        if file_path:
            folder = str(Path(file_path).parent.name)
            self._subtitle_label.set_text(folder)
        
        # Update format icon
        fmt = audio_data.get('format', '').lower()
        icon_name = self.FORMAT_ICONS.get(fmt, 'audio-x-generic-symbolic')
        self._icon.set_from_icon_name(icon_name)
        
        # Update format badge
        self._format_badge.set_text(fmt.upper())
        
        # Update sample rate
        sample_rate = audio_data.get('sample_rate', 0)
        if sample_rate:
            sr_text = f"{sample_rate // 1000}kHz" if sample_rate >= 1000 else f"{sample_rate}Hz"
            self._sample_rate_label.set_text(sr_text)
        
        # Update duration
        duration = audio_data.get('duration', 0)
        self._duration_label.set_text(format_duration(duration))
    
    def set_playing(self, playing: bool) -> None:
        """Set whether this file is currently playing."""
        self._playing = playing
        if playing:
            self._icon.set_from_icon_name("media-playback-start-symbolic")
            self._icon.remove_css_class("dim-label")
            self._icon.add_css_class("accent")
        else:
            fmt = self._audio_data.get('format', '').lower()
            icon_name = self.FORMAT_ICONS.get(fmt, 'audio-x-generic-symbolic')
            self._icon.set_from_icon_name(icon_name)
            self._icon.remove_css_class("accent")
            self._icon.add_css_class("dim-label")
    
    def set_selected(self, selected: bool) -> None:
        """Set selection state."""
        self._selected = selected
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
    
    @property
    def audio_data(self) -> Dict[str, Any]:
        """Get the audio data dictionary."""
        return self._audio_data
    
    @property
    def file_path(self) -> Optional[str]:
        """Get the file path."""
        return self._audio_data.get('file_path')
    
    @property
    def is_playing(self) -> bool:
        """Check if this file is playing."""
        return self._playing
