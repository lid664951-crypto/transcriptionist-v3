"""
Player Controls Widget

GTK4 播放器控制组件，包含播放/暂停/停止/跳转按钮和进度条。
参考 Quod Libet 的 controls.py 实现。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Callable

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject

if TYPE_CHECKING:
    from transcriptionist_v3.lib.quodlibet_adapter.player_adapter import GStreamerPlayer, PlayerState

logger = logging.getLogger(__name__)


def format_time(ms: int) -> str:
    """格式化毫秒为 mm:ss 或 hh:mm:ss"""
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    
    if hours > 0:
        return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"
    return f"{minutes}:{seconds % 60:02d}"


class TimeLabel(Gtk.Label):
    """时间显示标签"""
    
    def __init__(self, time_ms: int = 0):
        super().__init__()
        self.add_css_class("monospace")
        self.add_css_class("dim-label")
        self._time_ms = time_ms
        self._disabled = False
        self.set_time(time_ms)
    
    def set_time(self, time_ms: int) -> None:
        """设置时间（毫秒）"""
        self._time_ms = time_ms
        if not self._disabled:
            self.set_label(format_time(time_ms))
    
    def set_disabled(self, disabled: bool) -> None:
        """禁用时间显示"""
        self._disabled = disabled
        if disabled:
            self.set_label("--:--")
        else:
            self.set_time(self._time_ms)


class PlayPauseButton(Gtk.Button):
    """播放/暂停切换按钮"""
    
    __gtype_name__ = "PlayPauseButton"
    
    __gsignals__ = {
        "toggled": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }
    
    def __init__(self):
        super().__init__()
        self._is_playing = False
        self.add_css_class("circular")
        self.add_css_class("suggested-action")
        self._update_icon()
        self.connect("clicked", self._on_clicked)
    
    def _update_icon(self) -> None:
        """更新按钮图标"""
        icon_name = "media-playback-pause-symbolic" if self._is_playing else "media-playback-start-symbolic"
        self.set_icon_name(icon_name)
    
    def _on_clicked(self, button: Gtk.Button) -> None:
        """点击处理"""
        self.set_playing(not self._is_playing)
    
    def set_playing(self, is_playing: bool) -> None:
        """设置播放状态"""
        if self._is_playing != is_playing:
            self._is_playing = is_playing
            self._update_icon()
            self.emit("toggled", is_playing)
    
    def get_playing(self) -> bool:
        """获取播放状态"""
        return self._is_playing


class SeekBar(Gtk.Box):
    """进度条组件"""
    
    __gtype_name__ = "SeekBar"
    
    __gsignals__ = {
        "seek-requested": (GObject.SignalFlags.RUN_LAST, None, (int,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self._duration_ms = 0
        self._position_ms = 0
        self._seeking = False
        
        # 当前时间标签
        self._current_label = TimeLabel(0)
        self.append(self._current_label)
        
        # 进度滑块
        self._scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self._scale.set_hexpand(True)
        self._scale.set_draw_value(False)
        self._scale.connect("change-value", self._on_change_value)
        self.append(self._scale)
        
        # 总时长标签
        self._duration_label = TimeLabel(0)
        self.append(self._duration_label)
    
    def _on_change_value(self, scale: Gtk.Scale, scroll: Gtk.ScrollType, value: float) -> bool:
        """滑块值改变"""
        if self._duration_ms > 0:
            position_ms = int(value / 100 * self._duration_ms)
            self._current_label.set_time(position_ms)
            self._seeking = True
            self.emit("seek-requested", position_ms)
            GLib.timeout_add(100, self._reset_seeking)
        return False
    
    def _reset_seeking(self) -> bool:
        """重置seeking状态"""
        self._seeking = False
        return False
    
    def set_duration(self, duration_ms: int) -> None:
        """设置总时长"""
        self._duration_ms = duration_ms
        self._duration_label.set_time(duration_ms)
    
    def set_position(self, position_ms: int) -> None:
        """设置当前位置"""
        if not self._seeking and self._duration_ms > 0:
            self._position_ms = position_ms
            self._current_label.set_time(position_ms)
            progress = position_ms / self._duration_ms * 100
            self._scale.set_value(progress)
    
    def set_disabled(self, disabled: bool) -> None:
        """禁用进度条"""
        self._scale.set_sensitive(not disabled)
        self._current_label.set_disabled(disabled)
        self._duration_label.set_disabled(disabled)


class PlayerControls(Gtk.Box):
    """
    完整的播放器控制组件
    
    包含：
    - 上一曲/播放暂停/下一曲按钮
    - 进度条
    - 音量控制
    """
    
    __gtype_name__ = "PlayerControls"
    
    __gsignals__ = {
        "play-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
        "pause-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
        "stop-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
        "previous-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
        "next-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
        "seek-requested": (GObject.SignalFlags.RUN_LAST, None, (int,)),
        "volume-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("player-controls")
        
        self._player: Optional[GStreamerPlayer] = None
        self._update_timer_id: Optional[int] = None
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建UI"""
        # 主控制区域
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        controls_box.set_halign(Gtk.Align.CENTER)
        
        # 上一曲按钮
        self._prev_button = Gtk.Button(icon_name="media-skip-backward-symbolic")
        self._prev_button.add_css_class("flat")
        self._prev_button.connect("clicked", lambda b: self.emit("previous-clicked"))
        controls_box.append(self._prev_button)
        
        # 停止按钮
        self._stop_button = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self._stop_button.add_css_class("flat")
        self._stop_button.connect("clicked", lambda b: self.emit("stop-clicked"))
        controls_box.append(self._stop_button)
        
        # 播放/暂停按钮
        self._play_pause_button = PlayPauseButton()
        self._play_pause_button.connect("toggled", self._on_play_pause_toggled)
        controls_box.append(self._play_pause_button)
        
        # 下一曲按钮
        self._next_button = Gtk.Button(icon_name="media-skip-forward-symbolic")
        self._next_button.add_css_class("flat")
        self._next_button.connect("clicked", lambda b: self.emit("next-clicked"))
        controls_box.append(self._next_button)
        
        self.append(controls_box)
        
        # 进度条区域
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_box.set_margin_start(12)
        seek_box.set_margin_end(12)
        
        self._seek_bar = SeekBar()
        self._seek_bar.set_hexpand(True)
        self._seek_bar.connect("seek-requested", self._on_seek_requested)
        seek_box.append(self._seek_bar)
        
        # 音量按钮
        self._volume_button = Gtk.VolumeButton()
        self._volume_button.set_value(1.0)
        self._volume_button.connect("value-changed", self._on_volume_changed)
        seek_box.append(self._volume_button)
        
        self.append(seek_box)
    
    def _on_play_pause_toggled(self, button: PlayPauseButton, is_playing: bool) -> None:
        """播放/暂停切换"""
        if is_playing:
            self.emit("play-clicked")
        else:
            self.emit("pause-clicked")
    
    def _on_seek_requested(self, seek_bar: SeekBar, position_ms: int) -> None:
        """进度跳转请求"""
        self.emit("seek-requested", position_ms)
        if self._player:
            self._player.seek(position_ms)
    
    def _on_volume_changed(self, button: Gtk.VolumeButton, value: float) -> None:
        """音量改变"""
        self.emit("volume-changed", value)
        if self._player:
            self._player.volume = value
    
    def bind_player(self, player: GStreamerPlayer) -> None:
        """绑定播放器"""
        self._player = player
        
        # 设置回调
        player.set_on_state_changed(self._on_player_state_changed)
        player.set_on_eos(self._on_player_eos)
        
        # 启动位置更新定时器
        self._start_position_timer()
    
    def unbind_player(self) -> None:
        """解绑播放器"""
        self._stop_position_timer()
        self._player = None
    
    def _start_position_timer(self) -> None:
        """启动位置更新定时器"""
        if self._update_timer_id is None:
            self._update_timer_id = GLib.timeout_add(250, self._update_position)
    
    def _stop_position_timer(self) -> None:
        """停止位置更新定时器"""
        if self._update_timer_id is not None:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None
    
    def _update_position(self) -> bool:
        """更新播放位置"""
        if self._player and self._player.is_playing:
            position = self._player.get_position()
            duration = self._player.get_duration()
            self._seek_bar.set_position(position)
            if duration > 0:
                self._seek_bar.set_duration(duration)
        return True
    
    def _on_player_state_changed(self, state: PlayerState) -> None:
        """播放器状态改变"""
        from transcriptionist_v3.lib.quodlibet_adapter.player_adapter import PlayerState
        is_playing = state == PlayerState.PLAYING
        self._play_pause_button.set_playing(is_playing)
    
    def _on_player_eos(self) -> None:
        """播放结束"""
        self._play_pause_button.set_playing(False)
        self._seek_bar.set_position(0)
    
    def set_duration(self, duration_ms: int) -> None:
        """设置时长"""
        self._seek_bar.set_duration(duration_ms)
    
    def set_position(self, position_ms: int) -> None:
        """设置位置"""
        self._seek_bar.set_position(position_ms)
    
    def set_playing(self, is_playing: bool) -> None:
        """设置播放状态"""
        self._play_pause_button.set_playing(is_playing)
    
    def set_volume(self, volume: float) -> None:
        """设置音量"""
        self._volume_button.set_value(volume)
    
    def set_disabled(self, disabled: bool) -> None:
        """禁用控件"""
        self._prev_button.set_sensitive(not disabled)
        self._stop_button.set_sensitive(not disabled)
        self._play_pause_button.set_sensitive(not disabled)
        self._next_button.set_sensitive(not disabled)
        self._seek_bar.set_disabled(disabled)
