"""
Freesound Sound Card

Card widget for displaying a single Freesound sound in search results.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundSound,
    FreesoundLicense,
    LICENSE_INFO,
)


class FreesoundSoundCard(Gtk.ListBoxRow):
    """
    Card widget for displaying a Freesound sound.
    
    Shows:
    - Sound name (Chinese + English)
    - Duration, format, sample rate
    - License badge
    - Play and download buttons
    """
    
    __gsignals__ = {
        'play-clicked': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'download-clicked': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'details-clicked': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self, sound: FreesoundSound):
        super().__init__()
        
        self.sound = sound
        self._is_playing = False
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the card UI."""
        # Main container
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Play button
        self.play_btn = Gtk.Button()
        self.play_btn.set_icon_name('media-playback-start-symbolic')
        self.play_btn.add_css_class('circular')
        self.play_btn.set_valign(Gtk.Align.CENTER)
        self.play_btn.connect('clicked', self._on_play_clicked)
        box.append(self.play_btn)
        
        # Info section
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_hexpand(True)
        
        # Name row
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Chinese name (if available)
        if self.sound.name_zh:
            name_zh = Gtk.Label(label=self.sound.name_zh)
            name_zh.set_xalign(0)
            name_zh.add_css_class('heading')
            name_zh.set_ellipsize(Pango.EllipsizeMode.END)
            name_box.append(name_zh)
        
        # English name
        name_en = Gtk.Label(label=self.sound.name)
        name_en.set_xalign(0)
        if self.sound.name_zh:
            name_en.add_css_class('dim-label')
        else:
            name_en.add_css_class('heading')
        name_en.set_ellipsize(Pango.EllipsizeMode.END)
        name_box.append(name_en)
        
        info_box.append(name_box)
        
        # Details row
        details_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        # Duration
        duration_label = Gtk.Label(label=f"⏱ {self.sound.duration_formatted}")
        duration_label.add_css_class('caption')
        duration_label.add_css_class('dim-label')
        details_box.append(duration_label)
        
        # Format
        format_label = Gtk.Label(label=f"📁 {self.sound.type.upper()}")
        format_label.add_css_class('caption')
        format_label.add_css_class('dim-label')
        details_box.append(format_label)
        
        # Sample rate
        sr_label = Gtk.Label(label=f"🎵 {self.sound.samplerate} Hz")
        sr_label.add_css_class('caption')
        sr_label.add_css_class('dim-label')
        details_box.append(sr_label)
        
        # Rating
        if self.sound.avg_rating > 0:
            rating_label = Gtk.Label(label=f"⭐ {self.sound.avg_rating:.1f}")
            rating_label.add_css_class('caption')
            rating_label.add_css_class('dim-label')
            details_box.append(rating_label)
        
        # Author
        author_label = Gtk.Label(label=f"👤 {self.sound.username}")
        author_label.add_css_class('caption')
        author_label.add_css_class('dim-label')
        details_box.append(author_label)
        
        info_box.append(details_box)
        
        box.append(info_box)
        
        # License badge
        license_badge = self._create_license_badge()
        license_badge.set_valign(Gtk.Align.CENTER)
        box.append(license_badge)
        
        # Download button
        download_btn = Gtk.Button()
        download_btn.set_icon_name('folder-download-symbolic')
        download_btn.add_css_class('flat')
        download_btn.set_valign(Gtk.Align.CENTER)
        download_btn.set_tooltip_text('下载')
        download_btn.connect('clicked', self._on_download_clicked)
        box.append(download_btn)
        
        # Details button
        details_btn = Gtk.Button()
        details_btn.set_icon_name('view-more-symbolic')
        details_btn.add_css_class('flat')
        details_btn.set_valign(Gtk.Align.CENTER)
        details_btn.set_tooltip_text('详情')
        details_btn.connect('clicked', self._on_details_clicked)
        box.append(details_btn)
        
        self.set_child(box)
    
    def _create_license_badge(self) -> Gtk.Widget:
        """Create license badge widget."""
        license_type = self.sound.license_type
        info = LICENSE_INFO.get(license_type, LICENSE_INFO[FreesoundLicense.CC_BY])
        
        badge = Gtk.Label(label=info['name_zh'])
        badge.add_css_class('caption')
        badge.add_css_class('pill')
        
        # Color based on license type
        if license_type == FreesoundLicense.CC0:
            badge.add_css_class('success')
        elif license_type in (FreesoundLicense.CC_BY, FreesoundLicense.CC_BY_SA):
            badge.add_css_class('accent')
        else:
            badge.add_css_class('warning')
        
        badge.set_tooltip_text(info['description_zh'])
        
        return badge
    
    def _on_play_clicked(self, button):
        """Handle play button click."""
        self._is_playing = not self._is_playing
        
        if self._is_playing:
            button.set_icon_name('media-playback-pause-symbolic')
        else:
            button.set_icon_name('media-playback-start-symbolic')
        
        self.emit('play-clicked', self.sound)
    
    def _on_download_clicked(self, button):
        """Handle download button click."""
        self.emit('download-clicked', self.sound)
    
    def _on_details_clicked(self, button):
        """Handle details button click."""
        self.emit('details-clicked', self.sound)
    
    def set_playing(self, playing: bool):
        """Set playing state."""
        self._is_playing = playing
        if playing:
            self.play_btn.set_icon_name('media-playback-pause-symbolic')
        else:
            self.play_btn.set_icon_name('media-playback-start-symbolic')
