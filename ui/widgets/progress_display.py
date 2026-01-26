"""
Playback Progress Display Widget

GTK4 播放进度显示组件，显示当前播放的文件信息和进度。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject, Pango

logger = logging.getLogger(__name__)


def format_time(ms: int) -> str:
    """格式化毫秒为时间字符串"""
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    
    if hours > 0:
        return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"
    return f"{minutes}:{seconds % 60:02d}"


class NowPlayingInfo(Gtk.Box):
    """
    当前播放信息显示
    
    显示：
    - 文件名/标题
    - 艺术家/描述
    - 专辑/分类
    """
    
    __gtype_name__ = "NowPlayingInfo"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        
        # 标题
        self._title_label = Gtk.Label(label="未播放")
        self._title_label.set_halign(Gtk.Align.START)
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._title_label.add_css_class("heading")
        self.append(self._title_label)
        
        # 副标题（艺术家/描述）
        self._subtitle_label = Gtk.Label(label="")
        self._subtitle_label.set_halign(Gtk.Align.START)
        self._subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._subtitle_label.add_css_class("dim-label")
        self._subtitle_label.add_css_class("caption")
        self.append(self._subtitle_label)
    
    def set_info(self, title: str, subtitle: str = "") -> None:
        """设置播放信息"""
        self._title_label.set_label(title or "未知")
        self._subtitle_label.set_label(subtitle)
        self._subtitle_label.set_visible(bool(subtitle))
    
    def clear(self) -> None:
        """清除信息"""
        self._title_label.set_label("未播放")
        self._subtitle_label.set_label("")
        self._subtitle_label.set_visible(False)


class ProgressDisplay(Gtk.Box):
    """
    播放进度显示组件
    
    包含：
    - 当前播放信息
    - 进度条
    - 时间显示
    """
    
    __gtype_name__ = "ProgressDisplay"
    
    __gsignals__ = {
        "seek-requested": (GObject.SignalFlags.RUN_LAST, None, (int,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("progress-display")
        
        self._duration_ms = 0
        self._position_ms = 0
        self._seeking = False
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 播放信息
        self._now_playing = NowPlayingInfo()
        self.append(self._now_playing)
        
        # 进度条区域
        progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # 当前时间
        self._current_time = Gtk.Label(label="0:00")
        self._current_time.add_css_class("monospace")
        self._current_time.add_css_class("dim-label")
        self._current_time.set_width_chars(6)
        progress_box.append(self._current_time)
        
        # 进度滑块
        self._progress_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 0.1
        )
        self._progress_scale.set_hexpand(True)
        self._progress_scale.set_draw_value(False)
        self._progress_scale.connect("change-value", self._on_seek)
        progress_box.append(self._progress_scale)
        
        # 总时长
        self._total_time = Gtk.Label(label="0:00")
        self._total_time.add_css_class("monospace")
        self._total_time.add_css_class("dim-label")
        self._total_time.set_width_chars(6)
        progress_box.append(self._total_time)
        
        self.append(progress_box)
    
    def _on_seek(self, scale: Gtk.Scale, scroll: Gtk.ScrollType, value: float) -> bool:
        """进度跳转"""
        if self._duration_ms > 0:
            position_ms = int(value / 100 * self._duration_ms)
            self._seeking = True
            self._update_time_display(position_ms)
            self.emit("seek-requested", position_ms)
            GLib.timeout_add(200, self._reset_seeking)
        return False
    
    def _reset_seeking(self) -> bool:
        """重置seeking状态"""
        self._seeking = False
        return False
    
    def _update_time_display(self, position_ms: int) -> None:
        """更新时间显示"""
        self._current_time.set_label(format_time(position_ms))
    
    def set_now_playing(self, title: str, subtitle: str = "") -> None:
        """设置当前播放信息"""
        self._now_playing.set_info(title, subtitle)
    
    def set_duration(self, duration_ms: int) -> None:
        """设置总时长"""
        self._duration_ms = duration_ms
        self._total_time.set_label(format_time(duration_ms))
    
    def set_position(self, position_ms: int) -> None:
        """设置当前位置"""
        if not self._seeking:
            self._position_ms = position_ms
            self._update_time_display(position_ms)
            
            if self._duration_ms > 0:
                progress = position_ms / self._duration_ms * 100
                self._progress_scale.set_value(progress)
    
    def clear(self) -> None:
        """清除显示"""
        self._now_playing.clear()
        self._duration_ms = 0
        self._position_ms = 0
        self._current_time.set_label("0:00")
        self._total_time.set_label("0:00")
        self._progress_scale.set_value(0)
    
    def set_disabled(self, disabled: bool) -> None:
        """禁用组件"""
        self._progress_scale.set_sensitive(not disabled)


class MiniProgressBar(Gtk.ProgressBar):
    """
    迷你进度条
    
    用于在紧凑空间显示播放进度。
    """
    
    __gtype_name__ = "MiniProgressBar"
    
    def __init__(self):
        super().__init__()
        self._duration_ms = 0
        self.add_css_class("osd")
    
    def set_duration(self, duration_ms: int) -> None:
        """设置总时长"""
        self._duration_ms = duration_ms
    
    def set_position(self, position_ms: int) -> None:
        """设置当前位置"""
        if self._duration_ms > 0:
            fraction = position_ms / self._duration_ms
            self.set_fraction(min(1.0, max(0.0, fraction)))
        else:
            self.set_fraction(0)
    
    def clear(self) -> None:
        """清除进度"""
        self._duration_ms = 0
        self.set_fraction(0)


class TimeDisplay(Gtk.Box):
    """
    时间显示组件
    
    显示 当前时间 / 总时长 格式。
    """
    
    __gtype_name__ = "TimeDisplay"
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        self._current = Gtk.Label(label="0:00")
        self._current.add_css_class("monospace")
        self.append(self._current)
        
        separator = Gtk.Label(label="/")
        separator.add_css_class("dim-label")
        self.append(separator)
        
        self._total = Gtk.Label(label="0:00")
        self._total.add_css_class("monospace")
        self._total.add_css_class("dim-label")
        self.append(self._total)
        
        self._duration_ms = 0
        self._show_remaining = False
    
    def set_duration(self, duration_ms: int) -> None:
        """设置总时长"""
        self._duration_ms = duration_ms
        self._total.set_label(format_time(duration_ms))
    
    def set_position(self, position_ms: int) -> None:
        """设置当前位置"""
        if self._show_remaining and self._duration_ms > 0:
            remaining = self._duration_ms - position_ms
            self._current.set_label(f"-{format_time(remaining)}")
        else:
            self._current.set_label(format_time(position_ms))
    
    def set_show_remaining(self, show: bool) -> None:
        """设置是否显示剩余时间"""
        self._show_remaining = show
    
    def toggle_remaining(self) -> None:
        """切换剩余时间显示"""
        self._show_remaining = not self._show_remaining
    
    def clear(self) -> None:
        """清除显示"""
        self._duration_ms = 0
        self._current.set_label("0:00")
        self._total.set_label("0:00")
