"""
File Details Panel Widget

A GTK4 panel for displaying detailed audio file information.
Inspired by Quod Libet's Information dialog but as a sidebar panel.
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
    from gi.repository import Gtk, Adw, GObject, Pango
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


def format_sample_rate(rate: int) -> str:
    """Format sample rate to human readable format."""
    if rate >= 1000:
        return f"{rate / 1000:.1f} kHz"
    return f"{rate} Hz"


class FileDetailsPanel(Gtk.Box):
    """
    A panel for displaying detailed audio file information.
    
    Features:
    - File metadata display
    - Audio properties (duration, sample rate, bit depth, channels)
    - Tags display and editing
    - Waveform preview (placeholder)
    - Quick actions (play, rename, delete)
    """
    
    __gtype_name__ = 'FileDetailsPanel'
    
    __gsignals__ = {
        'play-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'edit-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'rename-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'delete-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'show-in-folder': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'tag-changed': (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        if not GTK_AVAILABLE:
            return
        
        self._audio_data: Optional[Dict[str, Any]] = None
        self._editable = False
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Set up the panel UI."""
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        
        # Scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        # Main content box
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        
        # Header with filename and actions
        self._header = self._create_header()
        content.append(self._header)
        
        # Waveform preview placeholder
        self._waveform_box = self._create_waveform_placeholder()
        content.append(self._waveform_box)
        
        # Audio properties group
        self._properties_group = self._create_properties_group()
        content.append(self._properties_group)
        
        # File info group
        self._file_group = self._create_file_group()
        content.append(self._file_group)
        
        # Tags group
        self._tags_group = self._create_tags_group()
        content.append(self._tags_group)
        
        scrolled.set_child(content)
        self.append(scrolled)
        
        # Empty state
        self._empty_state = Adw.StatusPage()
        self._empty_state.set_icon_name("audio-x-generic-symbolic")
        self._empty_state.set_title("未选择文件")
        self._empty_state.set_description("选择一个音效文件查看详情")
        self._empty_state.set_vexpand(True)
        
        # Initially show empty state
        self._show_empty_state()
    
    def _create_header(self) -> Gtk.Box:
        """Create the header section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Filename
        self._filename_label = Gtk.Label()
        self._filename_label.set_halign(Gtk.Align.START)
        self._filename_label.set_wrap(True)
        self._filename_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._filename_label.add_css_class("title-2")
        box.append(self._filename_label)
        
        # Folder path
        self._path_label = Gtk.Label()
        self._path_label.set_halign(Gtk.Align.START)
        self._path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._path_label.add_css_class("dim-label")
        self._path_label.add_css_class("caption")
        box.append(self._path_label)
        
        # Action buttons
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_margin_top(8)
        
        play_btn = Gtk.Button()
        play_btn.set_icon_name("media-playback-start-symbolic")
        play_btn.set_tooltip_text("播放")
        play_btn.connect("clicked", lambda b: self.emit('play-requested'))
        actions_box.append(play_btn)
        
        folder_btn = Gtk.Button()
        folder_btn.set_icon_name("folder-open-symbolic")
        folder_btn.set_tooltip_text("在文件夹中显示")
        folder_btn.connect("clicked", lambda b: self.emit('show-in-folder'))
        actions_box.append(folder_btn)
        
        rename_btn = Gtk.Button()
        rename_btn.set_icon_name("document-edit-symbolic")
        rename_btn.set_tooltip_text("重命名")
        rename_btn.connect("clicked", lambda b: self.emit('rename-requested'))
        actions_box.append(rename_btn)
        
        box.append(actions_box)
        
        return box
    
    def _create_waveform_placeholder(self) -> Gtk.Box:
        """Create a placeholder for waveform visualization."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class("card")
        box.set_margin_top(8)
        
        # Placeholder drawing area
        self._waveform_area = Gtk.DrawingArea()
        self._waveform_area.set_size_request(-1, 80)
        self._waveform_area.set_draw_func(self._draw_waveform_placeholder)
        
        box.append(self._waveform_area)
        
        return box
    
    def _draw_waveform_placeholder(self, area: Gtk.DrawingArea, cr, 
                                    width: int, height: int) -> None:
        """Draw a placeholder waveform."""
        # Get theme colors
        style = area.get_style_context()
        
        # Draw background
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.1)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Draw center line
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.3)
        cr.set_line_width(1)
        cr.move_to(0, height / 2)
        cr.line_to(width, height / 2)
        cr.stroke()
        
        # Draw placeholder text
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.5)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        text = "波形预览"
        extents = cr.text_extents(text)
        cr.move_to((width - extents.width) / 2, (height + extents.height) / 2)
        cr.show_text(text)
    
    def _create_properties_group(self) -> Adw.PreferencesGroup:
        """Create the audio properties group."""
        group = Adw.PreferencesGroup()
        group.set_title("音频属性")
        
        # Duration
        self._duration_row = Adw.ActionRow()
        self._duration_row.set_title("时长")
        self._duration_value = Gtk.Label()
        self._duration_value.add_css_class("numeric")
        self._duration_row.add_suffix(self._duration_value)
        group.add(self._duration_row)
        
        # Sample rate
        self._sr_row = Adw.ActionRow()
        self._sr_row.set_title("采样率")
        self._sr_value = Gtk.Label()
        self._sr_value.add_css_class("numeric")
        self._sr_row.add_suffix(self._sr_value)
        group.add(self._sr_row)
        
        # Bit depth
        self._bits_row = Adw.ActionRow()
        self._bits_row.set_title("位深度")
        self._bits_value = Gtk.Label()
        self._bits_value.add_css_class("numeric")
        self._bits_row.add_suffix(self._bits_value)
        group.add(self._bits_row)
        
        # Channels
        self._channels_row = Adw.ActionRow()
        self._channels_row.set_title("声道")
        self._channels_value = Gtk.Label()
        self._channels_row.add_suffix(self._channels_value)
        group.add(self._channels_row)
        
        # Bitrate
        self._bitrate_row = Adw.ActionRow()
        self._bitrate_row.set_title("比特率")
        self._bitrate_value = Gtk.Label()
        self._bitrate_value.add_css_class("numeric")
        self._bitrate_row.add_suffix(self._bitrate_value)
        group.add(self._bitrate_row)
        
        return group
    
    def _create_file_group(self) -> Adw.PreferencesGroup:
        """Create the file info group."""
        group = Adw.PreferencesGroup()
        group.set_title("文件信息")
        
        # Format
        self._format_row = Adw.ActionRow()
        self._format_row.set_title("格式")
        self._format_value = Gtk.Label()
        self._format_row.add_suffix(self._format_value)
        group.add(self._format_row)
        
        # File size
        self._size_row = Adw.ActionRow()
        self._size_row.set_title("文件大小")
        self._size_value = Gtk.Label()
        self._size_value.add_css_class("numeric")
        self._size_row.add_suffix(self._size_value)
        group.add(self._size_row)
        
        return group
    
    def _create_tags_group(self) -> Adw.PreferencesGroup:
        """Create the tags group."""
        group = Adw.PreferencesGroup()
        group.set_title("标签")
        group.set_description("音频文件的元数据标签")
        
        # Title
        self._title_row = Adw.EntryRow()
        self._title_row.set_title("标题")
        self._title_row.connect("changed", lambda r: self._on_tag_changed("title", r.get_text()))
        group.add(self._title_row)
        
        # Artist
        self._artist_row = Adw.EntryRow()
        self._artist_row.set_title("艺术家")
        self._artist_row.connect("changed", lambda r: self._on_tag_changed("artist", r.get_text()))
        group.add(self._artist_row)
        
        # Album
        self._album_row = Adw.EntryRow()
        self._album_row.set_title("专辑")
        self._album_row.connect("changed", lambda r: self._on_tag_changed("album", r.get_text()))
        group.add(self._album_row)
        
        # Genre
        self._genre_row = Adw.EntryRow()
        self._genre_row.set_title("类型")
        self._genre_row.connect("changed", lambda r: self._on_tag_changed("genre", r.get_text()))
        group.add(self._genre_row)
        
        # Comment
        self._comment_row = Adw.EntryRow()
        self._comment_row.set_title("备注")
        self._comment_row.connect("changed", lambda r: self._on_tag_changed("comment", r.get_text()))
        group.add(self._comment_row)
        
        return group
    
    def _on_tag_changed(self, tag: str, value: str) -> None:
        """Handle tag value changes."""
        if self._editable and self._audio_data:
            self.emit('tag-changed', tag, value)
    
    def _show_empty_state(self) -> None:
        """Show the empty state."""
        # Hide content, show empty state
        for child in list(self):
            self.remove(child)
        self.append(self._empty_state)
    
    def _show_content(self) -> None:
        """Show the content."""
        # Remove empty state if present
        for child in list(self):
            self.remove(child)
        
        # Rebuild content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.append(self._header)
        content.append(self._waveform_box)
        content.append(self._properties_group)
        content.append(self._file_group)
        content.append(self._tags_group)
        
        scrolled.set_child(content)
        self.append(scrolled)
    
    # Public API
    def set_audio_data(self, data: Optional[Dict[str, Any]]) -> None:
        """Set the audio file data to display."""
        self._audio_data = data
        
        if data is None:
            self._show_empty_state()
            return
        
        self._show_content()
        
        # Update header
        filename = data.get('filename', 'Unknown')
        self._filename_label.set_text(filename)
        
        file_path = data.get('file_path', '')
        if file_path:
            folder = str(Path(file_path).parent)
            self._path_label.set_text(folder)
        
        # Update properties
        duration = data.get('duration', 0)
        self._duration_value.set_text(format_duration(duration))
        
        sample_rate = data.get('sample_rate', 0)
        self._sr_value.set_text(format_sample_rate(sample_rate))
        
        bit_depth = data.get('bit_depth', 0)
        self._bits_value.set_text(f"{bit_depth} bit" if bit_depth else "-")
        
        channels = data.get('channels', 0)
        channel_text = {1: "单声道", 2: "立体声"}.get(channels, f"{channels} 声道")
        self._channels_value.set_text(channel_text if channels else "-")
        
        bitrate = data.get('bitrate', 0)
        self._bitrate_value.set_text(f"{bitrate} kbps" if bitrate else "-")
        
        # Update file info
        fmt = data.get('format', '').upper()
        self._format_value.set_text(fmt)
        
        file_size = data.get('file_size', 0)
        self._size_value.set_text(format_size(file_size))
        
        # Update tags (without triggering change signals)
        self._editable = False
        
        self._title_row.set_text(data.get('title', '') or '')
        self._artist_row.set_text(data.get('artist', '') or '')
        self._album_row.set_text(data.get('album', '') or '')
        self._genre_row.set_text(data.get('genre', '') or '')
        self._comment_row.set_text(data.get('comment', '') or '')
        
        self._editable = True
    
    def clear(self) -> None:
        """Clear the panel."""
        self.set_audio_data(None)
    
    def get_audio_data(self) -> Optional[Dict[str, Any]]:
        """Get the current audio data."""
        return self._audio_data
    
    @property
    def file_path(self) -> Optional[str]:
        """Get the current file path."""
        if self._audio_data:
            return self._audio_data.get('file_path')
        return None
