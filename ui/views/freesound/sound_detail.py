"""
Freesound Sound Detail Panel

Detailed view for a single Freesound sound.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango
from typing import Optional, List

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundSound,
    FreesoundLicense,
    LICENSE_INFO,
)


class FreesoundSoundDetail(Adw.Bin):
    """
    Detailed view panel for a Freesound sound.
    
    Shows:
    - Full name and description (bilingual)
    - Technical parameters
    - Tags
    - License information
    - Similar sounds
    """
    
    __gsignals__ = {
        'play-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'download-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'similar-clicked': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'close-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self, sound: Optional[FreesoundSound] = None):
        super().__init__()
        
        self.sound = sound
        self._similar_sounds: List[FreesoundSound] = []
        
        self._build_ui()
        
        if sound:
            self.set_sound(sound)
    
    def _build_ui(self):
        """Build the detail panel UI."""
        # Main scrolled container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.content_box.set_margin_top(16)
        self.content_box.set_margin_bottom(16)
        self.content_box.set_margin_start(16)
        self.content_box.set_margin_end(16)
        
        scrolled.set_child(self.content_box)
        self.set_child(scrolled)
    
    def set_sound(self, sound: FreesoundSound):
        """Set the sound to display."""
        self.sound = sound
        self._rebuild_content()
    
    def set_similar_sounds(self, sounds: List[FreesoundSound]):
        """Set similar sounds to display."""
        self._similar_sounds = sounds
        self._rebuild_similar_section()
    
    def _rebuild_content(self):
        """Rebuild the content for current sound."""
        # Clear existing content
        while True:
            child = self.content_box.get_first_child()
            if child is None:
                break
            self.content_box.remove(child)
        
        if not self.sound:
            return
        
        # Header with close button
        header = self._build_header()
        self.content_box.append(header)
        
        # Name section
        name_section = self._build_name_section()
        self.content_box.append(name_section)
        
        # Description section
        if self.sound.description:
            desc_section = self._build_description_section()
            self.content_box.append(desc_section)
        
        # Tags section
        if self.sound.tags:
            tags_section = self._build_tags_section()
            self.content_box.append(tags_section)
        
        # Technical parameters
        params_section = self._build_params_section()
        self.content_box.append(params_section)
        
        # License section
        license_section = self._build_license_section()
        self.content_box.append(license_section)
        
        # Action buttons
        actions = self._build_actions()
        self.content_box.append(actions)
        
        # Similar sounds section (placeholder)
        self.similar_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.content_box.append(self.similar_section)
    
    def _build_header(self) -> Gtk.Widget:
        """Build the header with close button."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title = Gtk.Label(label="音效详情")
        title.add_css_class('title-4')
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)
        
        close_btn = Gtk.Button()
        close_btn.set_icon_name('window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.connect('clicked', lambda b: self.emit('close-clicked'))
        header.append(close_btn)
        
        return header
    
    def _build_name_section(self) -> Gtk.Widget:
        """Build the name section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        # Chinese name
        if self.sound.name_zh:
            name_zh = Gtk.Label(label=self.sound.name_zh)
            name_zh.add_css_class('title-1')
            name_zh.set_xalign(0)
            name_zh.set_wrap(True)
            box.append(name_zh)
        
        # English name
        name_en = Gtk.Label(label=self.sound.name)
        if self.sound.name_zh:
            name_en.add_css_class('dim-label')
        else:
            name_en.add_css_class('title-1')
        name_en.set_xalign(0)
        name_en.set_wrap(True)
        box.append(name_en)
        
        return box
    
    def _build_description_section(self) -> Gtk.Widget:
        """Build the description section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        label = Gtk.Label(label="📝 描述")
        label.add_css_class('heading')
        label.set_xalign(0)
        box.append(label)
        
        # Chinese description
        if self.sound.description_zh:
            desc_zh = Gtk.Label(label=self.sound.description_zh)
            desc_zh.set_xalign(0)
            desc_zh.set_wrap(True)
            box.append(desc_zh)
        
        # English description
        desc_en = Gtk.Label(label=self.sound.description)
        desc_en.set_xalign(0)
        desc_en.set_wrap(True)
        if self.sound.description_zh:
            desc_en.add_css_class('dim-label')
        box.append(desc_en)
        
        return box
    
    def _build_tags_section(self) -> Gtk.Widget:
        """Build the tags section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        label = Gtk.Label(label="🏷️ 标签")
        label.add_css_class('heading')
        label.set_xalign(0)
        box.append(label)
        
        # Tags flow box
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(10)
        flow.set_row_spacing(4)
        flow.set_column_spacing(4)
        
        for tag in self.sound.tags[:20]:  # Limit to 20 tags
            tag_label = Gtk.Label(label=tag)
            tag_label.add_css_class('pill')
            tag_label.add_css_class('caption')
            flow.append(tag_label)
        
        box.append(flow)
        
        return box
    
    def _build_params_section(self) -> Gtk.Widget:
        """Build the technical parameters section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        label = Gtk.Label(label="📊 技术参数")
        label.add_css_class('heading')
        label.set_xalign(0)
        box.append(label)
        
        # Parameters grid
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        
        params = [
            ("⏱️ 时长", self.sound.duration_formatted),
            ("🎵 采样率", f"{self.sound.samplerate} Hz"),
            ("📀 位深", f"{self.sound.bitdepth} bit"),
            ("📁 格式", self.sound.type.upper()),
            ("🔊 声道", f"{self.sound.channels}ch"),
            ("💾 大小", self.sound.filesize_formatted),
            ("👤 作者", self.sound.username),
            ("⭐ 评分", f"{self.sound.avg_rating:.1f}/5 ({self.sound.num_ratings})"),
            ("⬇️ 下载", f"{self.sound.num_downloads:,}"),
        ]
        
        for i, (name, value) in enumerate(params):
            row = i // 3
            col = (i % 3) * 2
            
            name_label = Gtk.Label(label=name)
            name_label.add_css_class('dim-label')
            name_label.set_xalign(0)
            grid.attach(name_label, col, row, 1, 1)
            
            value_label = Gtk.Label(label=value)
            value_label.set_xalign(0)
            grid.attach(value_label, col + 1, row, 1, 1)
        
        box.append(grid)
        
        return box
    
    def _build_license_section(self) -> Gtk.Widget:
        """Build the license section."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        label = Gtk.Label(label="⚖️ 协议")
        label.add_css_class('heading')
        label.set_xalign(0)
        box.append(label)
        
        license_type = self.sound.license_type
        info = LICENSE_INFO.get(license_type, LICENSE_INFO[FreesoundLicense.CC_BY])
        
        # License name
        license_label = Gtk.Label(label=info['name_zh'])
        license_label.set_xalign(0)
        box.append(license_label)
        
        # License description
        desc_label = Gtk.Label(label=info['description_zh'])
        desc_label.add_css_class('dim-label')
        desc_label.set_xalign(0)
        desc_label.set_wrap(True)
        box.append(desc_label)
        
        return box
    
    def _build_actions(self) -> Gtk.Widget:
        """Build action buttons."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        
        # Play button
        play_btn = Gtk.Button()
        play_btn.set_icon_name('media-playback-start-symbolic')
        play_btn.set_label('试听')
        play_btn.connect('clicked', lambda b: self.emit('play-clicked'))
        box.append(play_btn)
        
        # Download button
        download_btn = Gtk.Button()
        download_btn.set_icon_name('folder-download-symbolic')
        download_btn.set_label('下载')
        download_btn.add_css_class('suggested-action')
        download_btn.connect('clicked', lambda b: self.emit('download-clicked'))
        box.append(download_btn)
        
        return box
    
    def _rebuild_similar_section(self):
        """Rebuild the similar sounds section."""
        # Clear existing
        while True:
            child = self.similar_section.get_first_child()
            if child is None:
                break
            self.similar_section.remove(child)
        
        if not self._similar_sounds:
            return
        
        # Header
        label = Gtk.Label(label="🔗 相似音效推荐")
        label.add_css_class('heading')
        label.set_xalign(0)
        self.similar_section.append(label)
        
        # Similar sounds list
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        
        for sound in self._similar_sounds[:6]:
            card = self._create_mini_card(sound)
            flow.append(card)
        
        self.similar_section.append(flow)
    
    def _create_mini_card(self, sound: FreesoundSound) -> Gtk.Widget:
        """Create a mini card for similar sound."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class('card')
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        
        # Name
        name = sound.name_zh or sound.name
        if len(name) > 20:
            name = name[:17] + "..."
        name_label = Gtk.Label(label=name)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(name_label)
        
        # Duration
        duration_label = Gtk.Label(label=f"⏱️ {sound.duration_formatted}")
        duration_label.add_css_class('caption')
        duration_label.add_css_class('dim-label')
        box.append(duration_label)
        
        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.set_halign(Gtk.Align.CENTER)
        
        play_btn = Gtk.Button()
        play_btn.set_icon_name('media-playback-start-symbolic')
        play_btn.add_css_class('flat')
        play_btn.add_css_class('circular')
        btn_box.append(play_btn)
        
        download_btn = Gtk.Button()
        download_btn.set_icon_name('folder-download-symbolic')
        download_btn.add_css_class('flat')
        download_btn.add_css_class('circular')
        download_btn.connect('clicked', lambda b: self.emit('similar-clicked', sound))
        btn_box.append(download_btn)
        
        box.append(btn_box)
        
        return box
