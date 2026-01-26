"""
Freesound Download Queue

Widget for displaying and managing download queue.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango
from typing import Optional, Dict

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundDownloadItem,
    FreesoundSound,
)


class DownloadItemRow(Gtk.ListBoxRow):
    """Row widget for a single download item."""
    
    __gsignals__ = {
        'cancel-clicked': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'retry-clicked': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'open-clicked': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(self, item: FreesoundDownloadItem):
        super().__init__()
        
        self.item = item
        self._build_ui()
    
    def _build_ui(self):
        """Build the row UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Status icon
        self.status_icon = Gtk.Image()
        self.status_icon.set_valign(Gtk.Align.CENTER)
        self._update_status_icon()
        box.append(self.status_icon)
        
        # Info section
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_hexpand(True)
        
        # Name
        name = self.item.sound.name_zh or self.item.sound.name
        name_label = Gtk.Label(label=name)
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        info_box.append(name_label)
        
        # Progress bar (for downloading state)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_fraction(self.item.progress)
        self.progress_bar.set_visible(self.item.status == 'downloading')
        info_box.append(self.progress_bar)
        
        # Status label
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0)
        self.status_label.add_css_class('caption')
        self.status_label.add_css_class('dim-label')
        self._update_status_label()
        info_box.append(self.status_label)
        
        box.append(info_box)
        
        # Action buttons
        self.action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.action_box.set_valign(Gtk.Align.CENTER)
        self._update_action_buttons()
        box.append(self.action_box)
        
        self.set_child(box)
    
    def _update_status_icon(self):
        """Update status icon based on item status."""
        status = self.item.status
        
        if status == 'pending':
            self.status_icon.set_from_icon_name('content-loading-symbolic')
        elif status == 'downloading':
            self.status_icon.set_from_icon_name('folder-download-symbolic')
        elif status == 'completed':
            self.status_icon.set_from_icon_name('emblem-ok-symbolic')
            self.status_icon.add_css_class('success')
        elif status == 'failed':
            self.status_icon.set_from_icon_name('dialog-error-symbolic')
            self.status_icon.add_css_class('error')
        elif status == 'cancelled':
            self.status_icon.set_from_icon_name('process-stop-symbolic')
            self.status_icon.add_css_class('dim-label')
    
    def _update_status_label(self):
        """Update status label text."""
        status = self.item.status
        
        if status == 'pending':
            self.status_label.set_text('等待下载...')
        elif status == 'downloading':
            percent = int(self.item.progress * 100)
            self.status_label.set_text(f'下载中 {percent}%')
        elif status == 'completed':
            self.status_label.set_text('下载完成')
        elif status == 'failed':
            error = self.item.error or '未知错误'
            self.status_label.set_text(f'下载失败: {error}')
        elif status == 'cancelled':
            self.status_label.set_text('已取消')
    
    def _update_action_buttons(self):
        """Update action buttons based on status."""
        # Clear existing buttons
        while True:
            child = self.action_box.get_first_child()
            if child is None:
                break
            self.action_box.remove(child)
        
        status = self.item.status
        
        if status in ('pending', 'downloading'):
            # Cancel button
            cancel_btn = Gtk.Button()
            cancel_btn.set_icon_name('process-stop-symbolic')
            cancel_btn.add_css_class('flat')
            cancel_btn.set_tooltip_text('取消')
            cancel_btn.connect('clicked', self._on_cancel_clicked)
            self.action_box.append(cancel_btn)
        
        elif status == 'completed':
            # Open folder button
            open_btn = Gtk.Button()
            open_btn.set_icon_name('folder-open-symbolic')
            open_btn.add_css_class('flat')
            open_btn.set_tooltip_text('打开文件夹')
            open_btn.connect('clicked', self._on_open_clicked)
            self.action_box.append(open_btn)
        
        elif status == 'failed':
            # Retry button
            retry_btn = Gtk.Button()
            retry_btn.set_icon_name('view-refresh-symbolic')
            retry_btn.add_css_class('flat')
            retry_btn.set_tooltip_text('重试')
            retry_btn.connect('clicked', self._on_retry_clicked)
            self.action_box.append(retry_btn)
    
    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit('cancel-clicked', self.item.sound.id)
    
    def _on_retry_clicked(self, button):
        """Handle retry button click."""
        self.emit('retry-clicked', self.item.sound.id)
    
    def _on_open_clicked(self, button):
        """Handle open folder button click."""
        if self.item.local_path:
            self.emit('open-clicked', self.item.local_path)
    
    def update(self, item: FreesoundDownloadItem):
        """Update the row with new item data."""
        self.item = item
        
        # Update progress bar
        self.progress_bar.set_fraction(item.progress)
        self.progress_bar.set_visible(item.status == 'downloading')
        
        # Update status
        self._update_status_icon()
        self._update_status_label()
        self._update_action_buttons()


class FreesoundDownloadQueue(Adw.Bin):
    """
    Download queue widget.
    
    Shows all downloads with progress and controls.
    """
    
    __gsignals__ = {
        'cancel-download': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'retry-download': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'clear-completed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'open-file': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(self):
        super().__init__()
        
        self._rows: Dict[int, DownloadItemRow] = {}
        self._build_ui()
    
    def _build_ui(self):
        """Build the queue UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.set_margin_top(12)
        header.set_margin_bottom(8)
        
        title = Gtk.Label(label="下载队列")
        title.add_css_class('heading')
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)
        
        # Stats
        self.stats_label = Gtk.Label(label="")
        self.stats_label.add_css_class('dim-label')
        header.append(self.stats_label)
        
        # Clear completed button
        self.clear_btn = Gtk.Button(label='清除已完成')
        self.clear_btn.add_css_class('flat')
        self.clear_btn.connect('clicked', self._on_clear_clicked)
        header.append(self.clear_btn)
        
        main_box.append(header)
        
        # Queue list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        
        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.queue_list.add_css_class('boxed-list')
        self.queue_list.set_margin_start(16)
        self.queue_list.set_margin_end(16)
        self.queue_list.set_margin_bottom(16)
        
        # Empty placeholder
        self.queue_list.set_placeholder(self._create_empty_placeholder())
        
        scrolled.set_child(self.queue_list)
        main_box.append(scrolled)
        
        self.set_child(main_box)
    
    def _create_empty_placeholder(self) -> Gtk.Widget:
        """Create empty state placeholder."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_top(32)
        box.set_margin_bottom(32)
        
        icon = Gtk.Image.new_from_icon_name('folder-download-symbolic')
        icon.set_pixel_size(48)
        icon.add_css_class('dim-label')
        box.append(icon)
        
        label = Gtk.Label(label="下载队列为空")
        label.add_css_class('dim-label')
        box.append(label)
        
        return box
    
    def add_item(self, item: FreesoundDownloadItem):
        """Add a download item to the queue."""
        if item.sound.id in self._rows:
            # Update existing row
            self._rows[item.sound.id].update(item)
        else:
            # Create new row
            row = DownloadItemRow(item)
            row.connect('cancel-clicked', self._on_cancel_clicked)
            row.connect('retry-clicked', self._on_retry_clicked)
            row.connect('open-clicked', self._on_open_clicked)
            
            self._rows[item.sound.id] = row
            self.queue_list.append(row)
        
        self._update_stats()
    
    def update_item(self, item: FreesoundDownloadItem):
        """Update a download item."""
        if item.sound.id in self._rows:
            self._rows[item.sound.id].update(item)
            self._update_stats()
    
    def remove_item(self, sound_id: int):
        """Remove a download item."""
        if sound_id in self._rows:
            row = self._rows[sound_id]
            self.queue_list.remove(row)
            del self._rows[sound_id]
            self._update_stats()
    
    def clear_completed(self):
        """Remove all completed and failed items."""
        to_remove = []
        for sound_id, row in self._rows.items():
            if row.item.status in ('completed', 'failed', 'cancelled'):
                to_remove.append(sound_id)
        
        for sound_id in to_remove:
            self.remove_item(sound_id)
    
    def _update_stats(self):
        """Update stats label."""
        total = len(self._rows)
        downloading = sum(1 for r in self._rows.values() if r.item.status == 'downloading')
        pending = sum(1 for r in self._rows.values() if r.item.status == 'pending')
        completed = sum(1 for r in self._rows.values() if r.item.status == 'completed')
        
        if total == 0:
            self.stats_label.set_text("")
        else:
            parts = []
            if downloading > 0:
                parts.append(f"{downloading} 下载中")
            if pending > 0:
                parts.append(f"{pending} 等待")
            if completed > 0:
                parts.append(f"{completed} 完成")
            self.stats_label.set_text(" | ".join(parts))
    
    def _on_cancel_clicked(self, row, sound_id: int):
        """Handle cancel button click."""
        self.emit('cancel-download', sound_id)
    
    def _on_retry_clicked(self, row, sound_id: int):
        """Handle retry button click."""
        self.emit('retry-download', sound_id)
    
    def _on_open_clicked(self, row, path: str):
        """Handle open folder button click."""
        self.emit('open-file', path)
    
    def _on_clear_clicked(self, button):
        """Handle clear completed button click."""
        self.emit('clear-completed')
